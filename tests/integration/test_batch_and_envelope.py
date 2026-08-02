"""Integration tests for batch + envelope endpoints — spec 07-batch-and-envelope.md.

Covers TC-B-01..21.
"""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import jsonschema
import pytest
from httpx import ASGITransport, AsyncClient

from inkprint.core.db import session_scope
from inkprint.main import app
from inkprint.provenance.envelope_builder import canonical_bundle_bytes
from inkprint.repositories import certificate_repo
from inkprint.services import certificate_service, envelope_service

pytestmark = pytest.mark.integration

# Certificates, leak scans AND dossier envelopes all persist to the per-test
# SQLite database (autouse ``db_tables`` fixture), so isolation comes from the
# fresh schema per test — there is no in-process store left to reset.


@pytest.fixture()
async def client():
    """Async test client against the FastAPI app."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


@pytest.fixture(autouse=True)
def _mock_embedding():
    """Default: voyage embedding succeeds with a deterministic vector.

    Patches both the single-text and batched entry points, since the single-cert
    path uses ``compute_embedding`` and the batch path uses ``compute_embeddings``.
    """

    async def _one(text: str) -> list[float]:
        return [0.1] * 768

    async def _many(texts: list[str]) -> list[list[float]]:
        return [[0.1] * 768 for _ in texts]

    with (
        patch("inkprint.fingerprint.embed.compute_embedding", new=AsyncMock(side_effect=_one)),
        patch("inkprint.fingerprint.embed.compute_embeddings", new=AsyncMock(side_effect=_many)),
    ):
        yield


# ── POST /certificates/batch ──────────────────────────────────────────────────


class TestBatchCreateCertificates:
    async def test_tc_b_01_batch_of_three_in_order(self, client: AsyncClient) -> None:
        """TC-B-01: 3-item batch returns 3 certificates in input order with unique ids."""
        payload: dict[str, Any] = {
            "items": [
                {"text": "first text", "author": "a@example.com"},
                {"text": "second text", "author": "b@example.com"},
                {"text": "third text", "author": "c@example.com"},
            ]
        }
        resp = await client.post("/certificates/batch", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["certificates"]) == 3
        ids = [c["certificate_id"] for c in body["certificates"]]
        assert len(set(ids)) == 3
        for c in body["certificates"]:
            UUID(c["certificate_id"])

    async def test_tc_b_02_fingerprints_present(self, client: AsyncClient) -> None:
        """TC-B-02: Each response certificate has sha256, simhash, embedding_id."""
        resp = await client.post(
            "/certificates/batch",
            json={"items": [{"text": "hello", "author": "a@b.com"}]},
        )
        assert resp.status_code == 200
        fp = resp.json()["certificates"][0]["fingerprints"]
        assert "sha256" in fp and len(fp["sha256"]) == 64
        assert isinstance(fp["simhash"], int)
        UUID(fp["embedding_id"])

    async def test_tc_b_03_single_item_batch(self, client: AsyncClient) -> None:
        """TC-B-03: A single-item batch works (min_length=1)."""
        resp = await client.post(
            "/certificates/batch",
            json={"items": [{"text": "single", "author": "a@b.com"}]},
        )
        assert resp.status_code == 200
        assert len(resp.json()["certificates"]) == 1

    async def test_tc_b_04_fifty_item_batch(self, client: AsyncClient) -> None:
        """TC-B-04: A 50-item batch works (max_length=50)."""
        items = [{"text": f"text #{i}", "author": "a@b.com"} for i in range(50)]
        resp = await client.post("/certificates/batch", json={"items": items})
        assert resp.status_code == 200
        assert len(resp.json()["certificates"]) == 50

    async def test_tc_b_05_metadata_passes_through(self, client: AsyncClient) -> None:
        """TC-B-05: Per-item metadata survives into the stored record."""
        resp = await client.post(
            "/certificates/batch",
            json={
                "items": [
                    {
                        "text": "with meta",
                        "author": "a@b.com",
                        "metadata": {"source": "unit-test"},
                    }
                ]
            },
        )
        assert resp.status_code == 200
        cert_id = resp.json()["certificates"][0]["certificate_id"]
        stored = await certificate_service.get_certificate(cert_id)
        assert stored is not None
        assert stored["metadata"] == {"source": "unit-test"}

    async def test_tc_b_06_empty_items_rejected(self, client: AsyncClient) -> None:
        """TC-B-06: Empty items list → 422."""
        resp = await client.post("/certificates/batch", json={"items": []})
        assert resp.status_code == 422

    async def test_tc_b_07_fifty_one_items_rejected(self, client: AsyncClient) -> None:
        """TC-B-07: 51 items → 422."""
        items = [{"text": f"t{i}", "author": "a@b.com"} for i in range(51)]
        resp = await client.post("/certificates/batch", json={"items": items})
        assert resp.status_code == 422

    async def test_tc_b_08_empty_text_rejected(self, client: AsyncClient) -> None:
        """TC-B-08: Item with empty text → 422."""
        resp = await client.post(
            "/certificates/batch",
            json={"items": [{"text": "", "author": "a@b.com"}]},
        )
        assert resp.status_code == 422

    @pytest.mark.parametrize("blank", ["   ", "\t\n", "\u00a0", "\u3000"])
    async def test_tc_b_25_whitespace_only_text_rejected(
        self, client: AsyncClient, blank: str
    ) -> None:
        """TC-B-25: whitespace-only item text → 422 (canonical bytes may not be empty).

        ``min_length=1`` alone does not close this: canonicalize() maps these to
        b"", so the batch would sign certificates over zero bytes.
        """
        resp = await client.post(
            "/certificates/batch",
            json={"items": [{"text": blank, "author": "a@b.com"}]},
        )
        assert resp.status_code == 422, resp.text

    async def test_tc_b_09_oversize_text_rejected(self, client: AsyncClient) -> None:
        """TC-B-09: Text > 1_000_000 chars → 422."""
        resp = await client.post(
            "/certificates/batch",
            json={"items": [{"text": "x" * 1_000_001, "author": "a@b.com"}]},
        )
        assert resp.status_code == 422

    async def test_tc_b_26_storage_key_reflects_r2_when_configured(
        self, client: AsyncClient
    ) -> None:
        """TC-B-26: the batch path archives to R2 and stores the real key.

        The batch path used to hardcode ``certificates/{id}.json`` while never
        uploading anything, so a batch certificate advertised a blob key for an
        object that did not exist — even with R2 fully configured.
        """
        uploaded: list[tuple[str, str]] = []

        def fake_upload(key: str, text: str) -> str:
            uploaded.append((key, text))
            return f"inkprint/{key}"

        with patch("inkprint.core.r2.upload_text", side_effect=fake_upload):
            resp = await client.post(
                "/certificates/batch",
                json={
                    "items": [
                        {"text": "batch archived one", "author": "a@b.com"},
                        {"text": "batch archived two", "author": "a@b.com"},
                    ]
                },
            )
        assert resp.status_code == 200
        cert_ids = [c["certificate_id"] for c in resp.json()["certificates"]]
        assert len(uploaded) == 2
        assert {t for _, t in uploaded} == {"batch archived one", "batch archived two"}

        for cert_id in cert_ids:
            stored = await certificate_service.get_certificate(cert_id)
            assert stored is not None
            assert stored["storage_key"] == f"inkprint/certificates/{cert_id}.json"

    async def test_tc_b_26b_storage_key_falls_back_when_r2_absent(
        self, client: AsyncClient
    ) -> None:
        """TC-B-26: with R2 unconfigured, the batch key matches the single-cert path."""

        def unconfigured(key: str, text: str) -> None:
            return None

        with patch("inkprint.core.r2.upload_text", side_effect=unconfigured):
            resp = await client.post(
                "/certificates/batch",
                json={"items": [{"text": "no r2 here", "author": "a@b.com"}]},
            )
            single = await client.post(
                "/certificates",
                json={"text": "no r2 here either", "author": "a@b.com"},
            )
        assert resp.status_code == 200
        assert single.status_code == 201

        batch_id = resp.json()["certificates"][0]["certificate_id"]
        stored = await certificate_service.get_certificate(batch_id)
        assert stored is not None
        assert stored["storage_key"] == f"certificates/{batch_id}.json"
        assert single.json()["storage_key"] == f"certificates/{single.json()['id']}.json"

    async def test_tc_b_10_embedding_failure_rolls_back(self, client: AsyncClient) -> None:
        """TC-B-10: Embedding API failure → 503 with no commits.

        The batch is embedded in a single call (OPT-1), so an embedding failure
        is all-or-nothing by construction: nothing is persisted.
        """
        async with session_scope() as s:
            baseline = await certificate_repo.count(s)

        async def failing_batch(texts: list[str]) -> list[list[float]]:
            raise RuntimeError("voyage down")

        with patch(
            "inkprint.fingerprint.embed.compute_embeddings",
            new=AsyncMock(side_effect=failing_batch),
        ):
            resp = await client.post(
                "/certificates/batch",
                json={
                    "items": [
                        {"text": "a", "author": "a@b.com"},
                        {"text": "b", "author": "a@b.com"},
                        {"text": "c", "author": "a@b.com"},
                        {"text": "d", "author": "a@b.com"},
                    ]
                },
            )

        assert resp.status_code == 503
        async with session_scope() as s:
            after = await certificate_repo.count(s)
        assert after == baseline


# ── POST /dossiers/envelope ──────────────────────────────────────────────────


async def _create_three_certs(client: AsyncClient) -> list[str]:
    resp = await client.post(
        "/certificates/batch",
        json={
            "items": [
                {"text": "ev one", "author": "a@b.com"},
                {"text": "ev two", "author": "a@b.com"},
                {"text": "ev three", "author": "a@b.com"},
            ]
        },
    )
    assert resp.status_code == 200
    return [c["certificate_id"] for c in resp.json()["certificates"]]


class TestDossierEnvelope:
    async def test_tc_b_11_valid_envelope(self, client: AsyncClient) -> None:
        """TC-B-11: Valid request with 3 existing certs → 200 with manifest + signature."""
        evidence = await _create_three_certs(client)
        dossier_id = str(uuid4())
        resp = await client.post(
            "/dossiers/envelope",
            json={
                "dossier_id": dossier_id,
                "evidence_cert_ids": evidence,
                "debate_transcript_hash": "a" * 64,
                "perf_receipt_hash": "b" * 64,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["envelope_id"] == dossier_id
        assert "envelope_manifest" in body
        assert "envelope_signature" in body
        assert "created_at" in body

    async def test_tc_b_12_signature_verifies(self, client: AsyncClient) -> None:
        """TC-B-12: envelope_signature verifies against the app public key."""
        evidence = await _create_three_certs(client)
        dossier_id = uuid4()
        resp = await client.post(
            "/dossiers/envelope",
            json={
                "dossier_id": str(dossier_id),
                "evidence_cert_ids": evidence,
                "debate_transcript_hash": "a" * 64,
                "perf_receipt_hash": "b" * 64,
                "metadata": {"topic": "safety"},
            },
        )
        assert resp.status_code == 200
        body = resp.json()

        # Reproduce canonical bundle from the stored record to verify
        stored = await envelope_service.get_envelope(str(dossier_id))
        assert stored is not None

        public_key = app.state.public_key
        sig_bytes = base64.b64decode(body["envelope_signature"])
        # Should NOT raise
        public_key.verify(sig_bytes, stored["canonical_bundle"])

    async def test_tc_b_13_envelope_persisted(self, client: AsyncClient) -> None:
        """TC-B-13: Envelope is written to the ``dossier_envelopes`` table.

        Reads the row back through the ORM rather than through the service, so
        the assertion cannot be satisfied by an in-process dict: signed envelopes
        must survive a container restart (Render's free tier restarts often).
        """
        from inkprint.models.envelope import DossierEnvelope

        evidence = await _create_three_certs(client)
        dossier_id = str(uuid4())
        resp = await client.post(
            "/dossiers/envelope",
            json={
                "dossier_id": dossier_id,
                "evidence_cert_ids": evidence,
                "debate_transcript_hash": "a" * 64,
                "perf_receipt_hash": "b" * 64,
                "metadata": {"topic": "durability"},
            },
        )
        assert resp.status_code == 200

        async with session_scope() as session:
            row = await session.get(DossierEnvelope, UUID(dossier_id))
            assert row is not None
            assert row.envelope_signature == resp.json()["envelope_signature"]
            assert row.debate_transcript_hash == "a" * 64
            assert row.perf_receipt_hash == "b" * 64
            assert [str(c) for c in row.evidence_cert_ids] == evidence
            assert row.envelope_metadata == {"topic": "durability"}
            assert row.envelope_manifest == resp.json()["envelope_manifest"]

    async def test_tc_b_29_signature_verifies_against_bundle_read_from_db(
        self, client: AsyncClient
    ) -> None:
        """TC-B-29: the canonical bundle round-trips through the DB as bytes.

        The signature must verify against bytes reloaded from storage, not bytes
        that happened to still be in memory from the request that made them.
        """
        evidence = await _create_three_certs(client)
        dossier_id = str(uuid4())
        resp = await client.post(
            "/dossiers/envelope",
            json={
                "dossier_id": dossier_id,
                "evidence_cert_ids": evidence,
                "debate_transcript_hash": "c" * 64,
                "perf_receipt_hash": "d" * 64,
                "metadata": {"k": "v"},
            },
        )
        assert resp.status_code == 200

        reloaded = await envelope_service.get_envelope(dossier_id)
        assert reloaded is not None
        assert isinstance(reloaded["canonical_bundle"], bytes)
        app.state.public_key.verify(
            base64.b64decode(resp.json()["envelope_signature"]),
            reloaded["canonical_bundle"],
        )

    async def test_tc_b_28_schema_invalid_manifest_is_not_persisted(
        self, client: AsyncClient
    ) -> None:
        """TC-B-28: validate before write — a bad manifest never reaches the table."""
        from inkprint.models.envelope import DossierEnvelope

        evidence = await _create_three_certs(client)
        dossier_id = str(uuid4())

        def broken_manifest(**_kwargs: Any) -> dict[str, Any]:
            return {"@context": "http://not-c2pa", "assertions": []}

        with patch(
            "inkprint.services.envelope_service.build_envelope_manifest",
            side_effect=broken_manifest,
        ):
            # Pinned to ValidationError, not a blanket Exception: a bare
            # `raises(Exception)` would also be satisfied by the route blowing up
            # for an unrelated reason, which would not prove validate-before-write.
            with pytest.raises(jsonschema.ValidationError):
                await client.post(
                    "/dossiers/envelope",
                    json={
                        "dossier_id": dossier_id,
                        "evidence_cert_ids": evidence,
                        "debate_transcript_hash": "a" * 64,
                        "perf_receipt_hash": "b" * 64,
                    },
                )

        async with session_scope() as session:
            assert await session.get(DossierEnvelope, UUID(dossier_id)) is None

    async def test_tc_b_14_canonicalization_stable(self, client: AsyncClient) -> None:
        """TC-B-14: Same inputs yield byte-identical signatures (pure builder)."""
        import datetime as _dt

        kw: dict[str, Any] = {
            "dossier_id": uuid4(),
            "evidence_cert_ids": [uuid4(), uuid4()],
            "debate_transcript_hash": "a" * 64,
            "perf_receipt_hash": "b" * 64,
            "metadata": {"k": "v"},
            "issued_at": _dt.datetime(2026, 4, 18, tzinfo=_dt.UTC),
        }
        first = canonical_bundle_bytes(**kw)
        second = canonical_bundle_bytes(**kw)
        assert first == second
        # Sanity: changing metadata changes the bytes.
        kw["metadata"] = {"k": "different"}
        assert canonical_bundle_bytes(**kw) != first

    async def test_tc_b_15_unknown_cert_id_rejected(self, client: AsyncClient) -> None:
        """TC-B-15: Unknown evidence cert id → 422 with detail referencing the id."""
        evidence = await _create_three_certs(client)
        unknown = str(uuid4())
        resp = await client.post(
            "/dossiers/envelope",
            json={
                "dossier_id": str(uuid4()),
                "evidence_cert_ids": [*evidence, unknown],
                "debate_transcript_hash": "a" * 64,
                "perf_receipt_hash": "b" * 64,
            },
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == f"Unknown certificate: {unknown}"

    async def test_tc_b_16_empty_evidence_rejected(self, client: AsyncClient) -> None:
        """TC-B-16: Empty evidence list → 422."""
        resp = await client.post(
            "/dossiers/envelope",
            json={
                "dossier_id": str(uuid4()),
                "evidence_cert_ids": [],
                "debate_transcript_hash": "a" * 64,
                "perf_receipt_hash": "b" * 64,
            },
        )
        assert resp.status_code == 422

    async def test_tc_b_17_malformed_hash_rejected(self, client: AsyncClient) -> None:
        """TC-B-17: debate_transcript_hash not 64 hex → 422."""
        evidence = await _create_three_certs(client)
        resp = await client.post(
            "/dossiers/envelope",
            json={
                "dossier_id": str(uuid4()),
                "evidence_cert_ids": evidence,
                "debate_transcript_hash": "not-a-hash",
                "perf_receipt_hash": "b" * 64,
            },
        )
        assert resp.status_code == 422

    async def test_tc_b_18_idempotency_and_conflict(self, client: AsyncClient) -> None:
        """TC-B-18: Same dossier_id + same bundle → idempotent 200; different bundle → 409."""
        evidence = await _create_three_certs(client)
        dossier_id = str(uuid4())
        body: dict[str, Any] = {
            "dossier_id": dossier_id,
            "evidence_cert_ids": evidence,
            "debate_transcript_hash": "a" * 64,
            "perf_receipt_hash": "b" * 64,
        }
        first = await client.post("/dossiers/envelope", json=body)
        assert first.status_code == 200

        # Same body — idempotent
        second = await client.post("/dossiers/envelope", json=body)
        assert second.status_code == 200
        assert second.json()["envelope_signature"] == first.json()["envelope_signature"]

        # Different body — conflict
        different = {**body, "perf_receipt_hash": "c" * 64}
        third = await client.post("/dossiers/envelope", json=different)
        assert third.status_code == 409


# ── POST /verify/batch ───────────────────────────────────────────────────────


class TestVerifyBatch:
    async def test_tc_b_19_three_valid_no_text(self, client: AsyncClient) -> None:
        """TC-B-19: 3 valid certs, no text → all valid with signature + hash only."""
        evidence = await _create_three_certs(client)
        resp = await client.post(
            "/verify/batch",
            json={"items": [{"certificate_id": cid} for cid in evidence]},
        )
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 3
        for r in results:
            assert r["valid"] is True
            assert r["checks"]["signature"] is True
            assert r["checks"]["hash"] is True
            assert "simhash" not in r["checks"]
            assert "embedding" not in r["checks"]

    async def test_tc_b_20_tampered_text_fails_fingerprints(self, client: AsyncClient) -> None:
        """TC-B-20: valid cert + cert with modified text — second fails simhash + embedding."""
        # Create two certs with distinct text. For test determinism:
        create = await client.post(
            "/certificates/batch",
            json={
                "items": [
                    {"text": "alpha beta gamma delta epsilon", "author": "a@b.com"},
                    {
                        "text": ("the rain in spain falls mainly on the plain"),
                        "author": "a@b.com",
                    },
                ]
            },
        )
        certs = create.json()["certificates"]
        id_first = certs[0]["certificate_id"]
        id_second = certs[1]["certificate_id"]

        # Patch embedding so tampered text returns an orthogonal vector.
        # Stored vector is [0.1]*768 (uniform); an alternating sign vector
        # sums to a dot product near zero, driving cosine below 0.99.
        orthogonal_vec = [0.1 if i % 2 == 0 else -0.1 for i in range(768)]

        async def embed(text: str) -> list[float]:
            return orthogonal_vec

        with patch(
            "inkprint.fingerprint.embed.compute_embedding",
            new=AsyncMock(side_effect=embed),
        ):
            resp = await client.post(
                "/verify/batch",
                json={
                    "items": [
                        {
                            "certificate_id": id_first,
                            "text": "alpha beta gamma delta epsilon",
                        },
                        {
                            "certificate_id": id_second,
                            "text": "totally unrelated shakespeare soliloquy content",
                        },
                    ]
                },
            )

        assert resp.status_code == 200
        results = resp.json()["results"]
        assert results[0]["checks"]["signature"] is True
        assert results[0]["checks"]["hash"] is True
        # Second: tampered text should flip simhash+embedding false
        assert results[1]["checks"]["simhash"] is False
        assert results[1]["checks"]["embedding"] is False
        assert results[1]["valid"] is False

    async def test_tc_b_21_unknown_cert_fails_softly(self, client: AsyncClient) -> None:
        """TC-B-21: Unknown cert id returns valid=false with reason; others pass."""
        evidence = await _create_three_certs(client)
        unknown = str(uuid4())
        resp = await client.post(
            "/verify/batch",
            json={
                "items": [
                    {"certificate_id": evidence[0]},
                    {"certificate_id": unknown},
                    {"certificate_id": evidence[1]},
                ]
            },
        )
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert results[0]["valid"] is True
        assert results[1]["valid"] is False
        assert results[1]["reason"] == "unknown_certificate"
        assert results[2]["valid"] is True

    async def test_empty_items_rejected(self, client: AsyncClient) -> None:
        """Envelope-level shape error: empty items list → 422."""
        resp = await client.post("/verify/batch", json={"items": []})
        assert resp.status_code == 422

    async def test_fifty_one_items_rejected(self, client: AsyncClient) -> None:
        """Envelope-level shape error: 51 items → 422."""
        items = [{"certificate_id": str(uuid4())} for _ in range(51)]
        resp = await client.post("/verify/batch", json={"items": items})
        assert resp.status_code == 422

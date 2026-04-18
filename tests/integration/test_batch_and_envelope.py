"""Integration tests for batch + envelope endpoints — spec 07-batch-and-envelope.md.

Covers TC-B-01..21.
"""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from inkprint.main import app
from inkprint.provenance.envelope_builder import canonical_bundle_bytes
from inkprint.services import certificate_service, envelope_service, leak_service

pytestmark = pytest.mark.integration


@pytest.fixture()
async def client():
    """Async test client against the FastAPI app."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean_stores():
    """Reset in-memory stores before and after each test."""
    certificate_service.reset_store()
    leak_service.reset_store()
    envelope_service.reset_store()
    yield
    certificate_service.reset_store()
    leak_service.reset_store()
    envelope_service.reset_store()


@pytest.fixture(autouse=True)
def _mock_embedding():
    """Default: voyage embedding succeeds with a deterministic vector."""
    with patch(
        "inkprint.fingerprint.embed.compute_embedding",
        new=AsyncMock(return_value=[0.1] * 768),
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
        stored = certificate_service.get_certificate(cert_id)
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

    async def test_tc_b_09_oversize_text_rejected(self, client: AsyncClient) -> None:
        """TC-B-09: Text > 1_000_000 chars → 422."""
        resp = await client.post(
            "/certificates/batch",
            json={"items": [{"text": "x" * 1_000_001, "author": "a@b.com"}]},
        )
        assert resp.status_code == 422

    async def test_tc_b_10_embedding_failure_rolls_back(
        self, client: AsyncClient
    ) -> None:
        """TC-B-10: Embedding API failure mid-batch → 503 with no commits."""
        baseline = len(certificate_service._certificates)
        call_count = {"n": 0}

        async def flaky_embed(text: str) -> list[float]:
            call_count["n"] += 1
            if call_count["n"] == 3:
                raise RuntimeError("voyage down")
            return [0.1] * 768

        with patch(
            "inkprint.fingerprint.embed.compute_embedding",
            new=AsyncMock(side_effect=flaky_embed),
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
        after = len(certificate_service._certificates)
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
        stored = envelope_service.get_envelope(str(dossier_id))
        assert stored is not None

        public_key = app.state.public_key
        sig_bytes = base64.b64decode(body["envelope_signature"])
        # Should NOT raise
        public_key.verify(sig_bytes, stored["canonical_bundle"])

    async def test_tc_b_13_envelope_persisted(self, client: AsyncClient) -> None:
        """TC-B-13: Envelope is retrievable from the envelope store."""
        evidence = await _create_three_certs(client)
        dossier_id = str(uuid4())
        await client.post(
            "/dossiers/envelope",
            json={
                "dossier_id": dossier_id,
                "evidence_cert_ids": evidence,
                "debate_transcript_hash": "a" * 64,
                "perf_receipt_hash": "b" * 64,
            },
        )
        stored = envelope_service.get_envelope(dossier_id)
        assert stored is not None
        assert str(stored["envelope_id"]) == dossier_id

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

    async def test_tc_b_18_idempotency_and_conflict(
        self, client: AsyncClient
    ) -> None:
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

    async def test_tc_b_20_tampered_text_fails_fingerprints(
        self, client: AsyncClient
    ) -> None:
        """TC-B-20: valid cert + cert with modified text — second fails simhash + embedding."""
        # Create two certs with distinct text. For test determinism:
        create = await client.post(
            "/certificates/batch",
            json={
                "items": [
                    {"text": "alpha beta gamma delta epsilon", "author": "a@b.com"},
                    {
                        "text": (
                            "the rain in spain falls mainly on the plain"
                        ),
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

    async def test_tc_b_21_unknown_cert_fails_softly(
        self, client: AsyncClient
    ) -> None:
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

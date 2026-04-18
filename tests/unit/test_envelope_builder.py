"""Tests for inkprint.provenance.envelope_builder — spec 07-batch-and-envelope.md.

Pure builder; no I/O, no signing, no DB. Covers test cases TC-B-22..24.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from inkprint.provenance.envelope_builder import (
    CLAIM_GENERATOR,
    DEBATE_HASH_LABEL,
    INGREDIENT_LABEL,
    PERF_HASH_LABEL,
    build_envelope_manifest,
    canonical_bundle_bytes,
)


def _fixed_time() -> datetime:
    return datetime(2026, 4, 18, 12, 0, 0, tzinfo=UTC)


def _sample_bundle_kwargs() -> dict:
    return {
        "dossier_id": uuid4(),
        "evidence_cert_ids": [uuid4(), uuid4(), uuid4()],
        "debate_transcript_hash": "a" * 64,
        "perf_receipt_hash": "b" * 64,
        "metadata": {"topic": "AI safety"},
        "issued_at": _fixed_time(),
    }


class TestCanonicalBundleBytes:
    def test_tc_b_22_canonical_bundle_is_deterministic(self) -> None:
        """TC-B-22: Same inputs yield byte-identical canonical bytes across calls."""
        kwargs = _sample_bundle_kwargs()
        first = canonical_bundle_bytes(**kwargs)
        second = canonical_bundle_bytes(**kwargs)
        assert first == second

    def test_tc_b_23_different_metadata_yields_different_bytes(self) -> None:
        """TC-B-23: Changing metadata changes the canonical bytes."""
        kwargs = _sample_bundle_kwargs()
        baseline = canonical_bundle_bytes(**kwargs)
        kwargs["metadata"] = {"topic": "different"}
        changed = canonical_bundle_bytes(**kwargs)
        assert baseline != changed

    def test_metadata_none_vs_empty_dict_equivalent(self) -> None:
        """Metadata=None and metadata={} normalize to the same canonical bytes."""
        kwargs = _sample_bundle_kwargs()
        kwargs["metadata"] = None
        none_bytes = canonical_bundle_bytes(**kwargs)
        kwargs["metadata"] = {}
        empty_bytes = canonical_bundle_bytes(**kwargs)
        assert none_bytes == empty_bytes

    def test_metadata_order_insensitive(self) -> None:
        """Metadata key order does not affect canonical bytes."""
        kwargs = _sample_bundle_kwargs()
        kwargs["metadata"] = {"a": "1", "b": "2"}
        first = canonical_bundle_bytes(**kwargs)
        kwargs["metadata"] = {"b": "2", "a": "1"}
        second = canonical_bundle_bytes(**kwargs)
        assert first == second


class TestBuildEnvelopeManifest:
    def test_tc_b_24_manifest_structure(self) -> None:
        """TC-B-24: Manifest contains correct ingredient + custom assertions."""
        dossier_id = uuid4()
        evidence_ids = [uuid4(), uuid4()]
        manifest = build_envelope_manifest(
            dossier_id=dossier_id,
            evidence_cert_ids=evidence_ids,
            debate_transcript_hash="c" * 64,
            perf_receipt_hash="d" * 64,
            bundle_hash_hex="e" * 64,
            signature_b64="c2ln",
            key_id="inkprint-test",
            issued_at=_fixed_time(),
        )

        assert manifest["claim_generator"] == CLAIM_GENERATOR
        assert manifest["instance_id"] == f"urn:uuid:{dossier_id}"

        assertions = manifest["assertions"]
        ingredient_assertions = [a for a in assertions if a["label"] == INGREDIENT_LABEL]
        assert len(ingredient_assertions) == len(evidence_ids)
        assert {a["data"]["instance_id"] for a in ingredient_assertions} == {
            f"urn:uuid:{cid}" for cid in evidence_ids
        }
        assert any(a["label"] == DEBATE_HASH_LABEL for a in assertions)
        assert any(a["label"] == PERF_HASH_LABEL for a in assertions)

        sig = manifest["signature"]
        assert sig["alg"] == "Ed25519"
        assert sig["value"] == "c2ln"
        assert sig["key_id"] == "inkprint-test"

    def test_manifest_rejects_non_uuid_dossier_id(self) -> None:
        """Non-UUID dossier_id raises TypeError."""
        with pytest.raises(TypeError):
            build_envelope_manifest(
                dossier_id="not-a-uuid",  # type: ignore[arg-type]
                evidence_cert_ids=[uuid4()],
                debate_transcript_hash="a" * 64,
                perf_receipt_hash="b" * 64,
                bundle_hash_hex="c" * 64,
                signature_b64="sig",
                key_id="k",
                issued_at=_fixed_time(),
            )

    def test_manifest_rejects_empty_evidence(self) -> None:
        """Empty evidence list raises ValueError."""
        with pytest.raises(ValueError):
            build_envelope_manifest(
                dossier_id=uuid4(),
                evidence_cert_ids=[],
                debate_transcript_hash="a" * 64,
                perf_receipt_hash="b" * 64,
                bundle_hash_hex="c" * 64,
                signature_b64="sig",
                key_id="k",
                issued_at=_fixed_time(),
            )

    def test_manifest_rejects_empty_bundle_hash(self) -> None:
        """Empty bundle_hash_hex raises ValueError."""
        with pytest.raises(ValueError):
            build_envelope_manifest(
                dossier_id=uuid4(),
                evidence_cert_ids=[uuid4()],
                debate_transcript_hash="a" * 64,
                perf_receipt_hash="b" * 64,
                bundle_hash_hex="",
                signature_b64="sig",
                key_id="k",
                issued_at=_fixed_time(),
            )

    def test_manifest_rejects_empty_signature(self) -> None:
        """Empty signature_b64 raises ValueError."""
        with pytest.raises(ValueError):
            build_envelope_manifest(
                dossier_id=uuid4(),
                evidence_cert_ids=[uuid4()],
                debate_transcript_hash="a" * 64,
                perf_receipt_hash="b" * 64,
                bundle_hash_hex="c" * 64,
                signature_b64="",
                key_id="k",
                issued_at=_fixed_time(),
            )

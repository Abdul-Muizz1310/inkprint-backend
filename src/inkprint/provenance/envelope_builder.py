"""Pure functions for building a dossier envelope bundle and C2PA manifest.

This module is pure — no I/O, no signing, no DB. It produces canonical bytes for
signing and a C2PA-aligned manifest dictionary from primitive inputs. Any side
effect (Ed25519 signing, persistence) happens in the service layer.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

CLAIM_GENERATOR = "bastion/dossier-envelope"

INGREDIENT_LABEL = "c2pa.ingredient.v2"
DEBATE_HASH_LABEL = "bastion.debate_transcript_hash"
PERF_HASH_LABEL = "bastion.perf_receipt_hash"


def canonical_bundle_bytes(
    *,
    dossier_id: UUID,
    evidence_cert_ids: list[UUID],
    debate_transcript_hash: str,
    perf_receipt_hash: str,
    metadata: dict[str, str] | None,
    issued_at: datetime,
) -> bytes:
    """Return canonical UTF-8 bytes representing the envelope bundle.

    Stable across runs: keys are sorted, evidence cert ids are serialized in the
    order supplied (they are already a list because order matters to the caller),
    metadata is sorted, and datetimes are isoformat-serialized.
    """
    bundle: dict[str, Any] = {
        "dossier_id": str(dossier_id),
        "evidence_cert_ids": [str(cid) for cid in evidence_cert_ids],
        "debate_transcript_hash": debate_transcript_hash,
        "perf_receipt_hash": perf_receipt_hash,
        "metadata": dict(sorted((metadata or {}).items())),
        "issued_at": issued_at.isoformat(),
    }
    return json.dumps(
        bundle,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def build_envelope_manifest(
    *,
    dossier_id: UUID,
    evidence_cert_ids: list[UUID],
    debate_transcript_hash: str,
    perf_receipt_hash: str,
    bundle_hash_hex: str,
    signature_b64: str,
    key_id: str,
    issued_at: datetime,
) -> dict[str, Any]:
    """Return a C2PA-aligned dossier envelope manifest.

    Produces the dict — signing itself happens elsewhere; this function only
    wires the pre-computed signature + hash into the manifest structure.
    """
    if not isinstance(dossier_id, UUID):
        raise TypeError(f"dossier_id must be UUID, got {type(dossier_id).__name__}")
    if not evidence_cert_ids:
        raise ValueError("evidence_cert_ids must not be empty")
    if not bundle_hash_hex:
        raise ValueError("bundle_hash_hex must not be empty")
    if not signature_b64:
        raise ValueError("signature_b64 must not be empty")

    assertions: list[dict[str, Any]] = [
        {
            "label": INGREDIENT_LABEL,
            "data": {
                "relationship": "inputTo",
                "url": f"/certificates/{cert_id}/manifest",
                "instance_id": f"urn:uuid:{cert_id}",
            },
        }
        for cert_id in evidence_cert_ids
    ]
    assertions.append(
        {
            "label": DEBATE_HASH_LABEL,
            "data": {"alg": "sha256", "hash": debate_transcript_hash},
        }
    )
    assertions.append(
        {
            "label": PERF_HASH_LABEL,
            "data": {"alg": "sha256", "hash": perf_receipt_hash},
        }
    )
    assertions.append(
        {
            "label": "c2pa.hash.data",
            "data": {"alg": "sha256", "hash": bundle_hash_hex, "pad": ""},
        }
    )

    return {
        "@context": "https://c2pa.org/statements/v1",
        "version": "2.2",
        "title": f"Dossier envelope {dossier_id}",
        "instance_id": f"urn:uuid:{dossier_id}",
        "format": "application/json",
        "claim_generator": CLAIM_GENERATOR,
        "claim_generator_info": [{"name": "bastion", "version": "0.1.0"}],
        "issued_at": issued_at.isoformat(),
        "assertions": assertions,
        "signature": {
            "alg": "Ed25519",
            "key_id": key_id,
            "value": signature_b64,
            "signed_assertions": [
                INGREDIENT_LABEL,
                DEBATE_HASH_LABEL,
                PERF_HASH_LABEL,
                "c2pa.hash.data",
            ],
        },
    }

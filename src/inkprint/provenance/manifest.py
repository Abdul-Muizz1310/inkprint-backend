"""C2PA v2.2-aligned content credential manifest builder."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import UUID

import jsonschema

_SCHEMA_PATH = Path(__file__).parent / "c2pa_schema.json"
_SCHEMA: dict | None = None

LEGAL_NOTICE = (
    "This certificate is issued by inkprint for informational purposes only. "
    "It does not constitute legal proof of authorship or copyright ownership. "
    "Consult qualified legal counsel for copyright matters."
)


def _load_schema() -> dict:
    global _SCHEMA
    if _SCHEMA is None:
        with open(_SCHEMA_PATH) as f:
            _SCHEMA = json.load(f)
    return _SCHEMA


def build_manifest(
    *,
    certificate_id: UUID,
    author: str,
    content_hash: str,
    signature_b64: str,
    key_id: str,
    content_length: int,
    language: str | None,
    issued_at: datetime,
) -> dict:
    """Build a C2PA v2.2-aligned manifest for a certificate."""
    if not isinstance(certificate_id, UUID):
        raise TypeError(f"certificate_id must be UUID, got {type(certificate_id).__name__}")
    if not content_hash:
        raise ValueError("content_hash must not be empty")
    if not author:
        raise ValueError("author must not be empty")

    return {
        "@context": "https://c2pa.org/statements/v1",
        "version": "2.2",
        "title": f"Content Credential for {certificate_id}",
        "instance_id": f"urn:uuid:{certificate_id}",
        "format": "text/plain",
        "claim_generator": "inkprint/0.1.0",
        "claim_generator_info": [
            {"name": "inkprint", "version": "0.1.0"},
        ],
        "legal_notice": LEGAL_NOTICE,
        "assertions": [
            {
                "label": "c2pa.actions.v2",
                "data": {
                    "actions": [
                        {
                            "action": "c2pa.created",
                            "when": issued_at.isoformat(),
                            "digitalSourceType": (
                                "http://cv.iptc.org/newscodes/digitalsourcetype/humanEdits"
                            ),
                        }
                    ]
                },
            },
            {
                "label": "c2pa.hash.data",
                "data": {
                    "alg": "sha256",
                    "hash": content_hash,
                    "pad": "",
                },
            },
            {
                "label": "stds.schema-org.CreativeWork",
                "data": {
                    "@context": "https://schema.org",
                    "@type": "CreativeWork",
                    "author": {"@type": "Person", "identifier": author},
                    "dateCreated": issued_at.isoformat(),
                    "inLanguage": language or "und",
                    "contentSize": content_length,
                },
            },
        ],
        "signature": {
            "alg": "Ed25519",
            "key_id": key_id,
            "value": signature_b64,
            "signed_assertions": ["c2pa.hash.data", "stds.schema-org.CreativeWork"],
        },
    }


def validate_manifest(manifest: dict) -> None:
    """Validate a manifest against the C2PA JSON Schema. Raises on failure."""
    schema = _load_schema()
    jsonschema.validate(instance=manifest, schema=schema)

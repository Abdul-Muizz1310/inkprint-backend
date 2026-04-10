#!/usr/bin/env python3
"""Generate an Ed25519 keypair for inkprint provenance signing.

Outputs base64-encoded PEM values suitable for pasting into .env:
    INKPRINT_SIGNING_KEY_PRIVATE=<base64>
    INKPRINT_SIGNING_KEY_PUBLIC=<base64>
    INKPRINT_KEY_ID=inkprint-ed25519-2026-04

Also writes raw PEM files to keys/ (gitignored).
"""

from __future__ import annotations

import base64
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

KEYS_DIR = Path(__file__).resolve().parent.parent / "keys"


def generate() -> None:
    """Generate an Ed25519 keypair and write to keys/ and stdout."""
    KEYS_DIR.mkdir(exist_ok=True)

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    )
    public_pem = public_key.public_bytes(
        encoding=Encoding.PEM,
        format=PublicFormat.SubjectPublicKeyInfo,
    )

    (KEYS_DIR / "private.pem").write_bytes(private_pem)
    (KEYS_DIR / "public.pem").write_bytes(public_pem)

    private_b64 = base64.b64encode(private_pem).decode()
    public_b64 = base64.b64encode(public_pem).decode()

    print("Keys written to keys/private.pem and keys/public.pem")
    print()
    print("Paste these into .env:")
    print()
    print(f"INKPRINT_SIGNING_KEY_PRIVATE={private_b64}")
    print(f"INKPRINT_SIGNING_KEY_PUBLIC={public_b64}")
    print("INKPRINT_KEY_ID=inkprint-ed25519-2026-04")


if __name__ == "__main__":
    generate()

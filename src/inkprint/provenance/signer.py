"""Ed25519 signing and verification."""

from __future__ import annotations

import base64

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def sign(data: bytes, private_key: Ed25519PrivateKey) -> str:
    """Sign data with Ed25519 and return base64-encoded signature."""
    signature = private_key.sign(data)
    return base64.b64encode(signature).decode("ascii")


def verify(data: bytes, signature_b64: str, public_key: Ed25519PublicKey) -> bool:
    """Verify an Ed25519 signature. Returns True if valid, False otherwise."""
    if not signature_b64:
        return False
    try:
        sig_bytes = base64.b64decode(signature_b64)
        public_key.verify(sig_bytes, data)
        return True
    except (InvalidSignature, Exception):
        return False

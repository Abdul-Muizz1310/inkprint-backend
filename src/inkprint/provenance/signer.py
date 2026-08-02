"""Ed25519 signing and verification."""

from __future__ import annotations

import base64

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def sign(data: bytes, private_key: Ed25519PrivateKey) -> str:
    """Sign data with Ed25519 and return base64-encoded signature.

    Refuses empty input (spec 01-signing, invariant 6). Ed25519 will happily sign
    zero bytes, but such a signature binds nothing: ``canonicalize()`` maps every
    whitespace-only text to ``b""``, so an empty-input signature would make all of
    them share one content hash and one "proof". This is the last line of defence
    behind the HTTP-boundary validators — a caller that skips them still cannot
    mint a certificate over nothing.
    """
    if not data:
        raise ValueError("Refusing to sign empty data: canonical bytes must not be empty")
    signature = private_key.sign(data)
    return base64.b64encode(signature).decode("ascii")


def verify(data: bytes, signature_b64: str, public_key: Ed25519PublicKey) -> bool:
    """Verify an Ed25519 signature. Returns True if valid, False otherwise.

    Never raises (spec 01-signing). Empty ``data`` is always invalid — the mirror
    of :func:`sign`'s guard, so a signature minted over ``b""`` out-of-band can
    never be talked into a ``valid: true`` verdict.
    """
    if not data or not signature_b64:
        return False
    try:
        sig_bytes = base64.b64decode(signature_b64)
        public_key.verify(sig_bytes, data)
        return True
    except (InvalidSignature, Exception):
        return False

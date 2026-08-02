"""The canonical-bytes-never-empty guard — specs 01-signing (invariant 6) and 05-api (TC-A-31).

``canonicalize()`` legitimately maps whitespace-only text to ``b""`` (spec 00, TC-C-07).
Nothing downstream may therefore assume "non-empty string in" means "non-empty canonical
bytes out": a certificate signed over ``b""`` binds nothing, and every such certificate
collides on ``sha256(b"") = e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855``.

This module pins the guard at both layers it must hold:

* the HTTP-boundary DTOs (single + batch) reject text whose canonical form is empty;
* ``sign()`` refuses empty input outright, so a future caller cannot reintroduce the bug
  by bypassing the DTOs.
"""

from __future__ import annotations

import hashlib

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from inkprint.provenance.canonicalize import canonicalize
from inkprint.provenance.signer import sign, verify
from inkprint.schemas.batch import BatchCertificateItem
from inkprint.schemas.certificate import CertificateCreate

# The SHA-256 of the empty byte string — the collision every whitespace-only
# submission used to land on.
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

# Inputs that are non-empty strings but canonicalize to b"".
BLANK_TEXTS = [
    " ",
    "   ",
    "\t",
    "\n",
    "\r\n",
    " \t\n\r\n  ",
    "\u00a0",  # NBSP - matched by canonicalize as whitespace
    "\u2028\u2029",  # line + paragraph separator
    "\u3000",  # ideographic space
]


class TestCanonicalizeBlankPremise:
    """The premise the guard exists for: these really do canonicalize to b""."""

    @pytest.mark.parametrize("text", BLANK_TEXTS)
    def test_blank_text_canonicalizes_to_empty(self, text: str) -> None:
        assert canonicalize(text) == b""

    def test_empty_canonical_hash_is_the_known_collision(self) -> None:
        assert hashlib.sha256(canonicalize("   ")).hexdigest() == EMPTY_SHA256


class TestCertificateCreateRejectsBlank:
    """Spec 05-api TC-A-31 — the single-certificate DTO."""

    @pytest.mark.parametrize("text", BLANK_TEXTS)
    def test_blank_text_rejected(self, text: str) -> None:
        with pytest.raises(ValidationError, match="canonical"):
            CertificateCreate(text=text, author="a@b.c")

    def test_empty_text_still_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CertificateCreate(text="", author="a@b.c")

    def test_text_with_content_still_accepted_and_preserved(self) -> None:
        model = CertificateCreate(text="  real content  ", author="a@b.c")
        # The validator must not mutate the submitted text — canonicalization is
        # the signer's job, and the raw text is what gets archived.
        assert model.text == "  real content  "


class TestBatchItemRejectsBlank:
    """Spec 07-batch-and-envelope TC-B-22 — the batch DTO has the same hole."""

    @pytest.mark.parametrize("text", BLANK_TEXTS)
    def test_blank_batch_item_text_rejected(self, text: str) -> None:
        with pytest.raises(ValidationError, match="canonical"):
            BatchCertificateItem(text=text, author="a@b.c")

    def test_batch_item_with_content_accepted(self) -> None:
        assert BatchCertificateItem(text=" ok ", author="a@b.c").text == " ok "


class TestSignerRefusesEmpty:
    """Spec 01-signing invariant 6 / TC-S-05."""

    @pytest.fixture()
    def keypair(self) -> tuple[Ed25519PrivateKey, object]:
        priv = Ed25519PrivateKey.generate()
        return priv, priv.public_key()

    def test_sign_empty_bytes_raises(self, keypair: tuple[Ed25519PrivateKey, object]) -> None:
        priv, _ = keypair
        with pytest.raises(ValueError, match="empty"):
            sign(b"", priv)

    def test_verify_empty_bytes_returns_false(
        self, keypair: tuple[Ed25519PrivateKey, object]
    ) -> None:
        """TC-S-05b: verify keeps its never-raise contract."""
        priv, pub = keypair
        sig = sign(b"non-empty", priv)
        assert verify(b"", sig, pub) is False

    def test_verify_rejects_a_genuine_signature_over_empty_bytes(
        self, keypair: tuple[Ed25519PrivateKey, object]
    ) -> None:
        """A signature minted over b"" out-of-band must still verify as False.

        Signs with the raw key object, bypassing ``sign()``'s guard — this is the
        only way an empty-canonical signature can reach the verifier, and the
        verifier must refuse it on its own rather than trusting the signer.
        """
        import base64

        priv, pub = keypair
        raw_sig = base64.b64encode(priv.sign(b"")).decode("ascii")
        assert verify(b"", raw_sig, pub) is False

    def test_sign_single_byte_still_works(self, keypair: tuple[Ed25519PrivateKey, object]) -> None:
        priv, pub = keypair
        assert verify(b"a", sign(b"a", priv), pub) is True

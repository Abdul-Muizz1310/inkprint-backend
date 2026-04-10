"""Tests for inkprint.provenance.signer + inkprint.core.keys — spec 01-signing.md."""

import base64
import os
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from inkprint.core.keys import load_signing_keys
from inkprint.provenance.signer import sign, verify


@pytest.fixture()
def keypair() -> tuple[Ed25519PrivateKey, object]:
    """Generate a fresh Ed25519 keypair for testing."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    return private_key, public_key


@pytest.fixture()
def other_keypair() -> tuple[Ed25519PrivateKey, object]:
    """Generate a second keypair (wrong key scenarios)."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    return private_key, public_key


# ── Happy path ───────────────────────────────────────────────────────────────


class TestSignerHappy:
    def test_tc_s_01_sign_verify_roundtrip(self, keypair):
        """TC-S-01: Sign then verify with matching keypair returns True."""
        priv, pub = keypair
        data = b"hello world"
        sig = sign(data, priv)
        assert verify(data, sig, pub) is True

    def test_tc_s_02_signature_format(self, keypair):
        """TC-S-02: Signature is valid base64, expected length."""
        priv, _ = keypair
        sig = sign(b"test data", priv)
        decoded = base64.b64decode(sig)
        assert len(decoded) == 64  # Ed25519 signature is 64 bytes

    def test_tc_s_03_deterministic(self, keypair):
        """TC-S-03: Same input + same key produces same signature."""
        priv, _ = keypair
        data = b"deterministic test"
        sig1 = sign(data, priv)
        sig2 = sign(data, priv)
        assert sig1 == sig2

    def test_tc_s_04_load_signing_keys_valid(self, keypair):
        """TC-S-04: load_signing_keys() with valid env vars returns usable key objects."""
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            NoEncryption,
            PrivateFormat,
            PublicFormat,
        )

        priv, pub = keypair
        priv_pem = priv.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        pub_pem = pub.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)

        env = {
            "INKPRINT_SIGNING_KEY_PRIVATE": base64.b64encode(priv_pem).decode(),
            "INKPRINT_SIGNING_KEY_PUBLIC": base64.b64encode(pub_pem).decode(),
            "INKPRINT_KEY_ID": "test-key-id",
        }
        with patch.dict(os.environ, env):
            loaded_priv, loaded_pub, _key_id = load_signing_keys()

        # Verify loaded keys work
        sig = sign(b"test", loaded_priv)
        assert verify(b"test", sig, loaded_pub) is True


# ── Edge cases ───────────────────────────────────────────────────────────────


class TestSignerEdge:
    def test_tc_s_05_sign_empty_bytes(self, keypair):
        """TC-S-05: Sign empty bytes succeeds and verifies."""
        priv, pub = keypair
        sig = sign(b"", priv)
        assert verify(b"", sig, pub) is True

    def test_tc_s_06_sign_large_input(self, keypair):
        """TC-S-06: Sign very large input (500 KB) succeeds and verifies."""
        priv, pub = keypair
        data = b"x" * 500_000
        sig = sign(data, priv)
        assert verify(data, sig, pub) is True

    def test_tc_s_07_key_id_stable(self, keypair):
        """TC-S-07: Key ID derivation is stable across multiple calls."""
        from inkprint.core.keys import derive_key_id

        _, pub = keypair
        id1 = derive_key_id(pub)
        id2 = derive_key_id(pub)
        assert id1 == id2
        assert len(id1) == 16


# ── Failure cases ────────────────────────────────────────────────────────────


class TestSignerFailure:
    def test_tc_s_08_tampered_data(self, keypair):
        """TC-S-08: Verify with tampered data returns False."""
        priv, pub = keypair
        sig = sign(b"original", priv)
        assert verify(b"tampered", sig, pub) is False

    def test_tc_s_09_wrong_public_key(self, keypair, other_keypair):
        """TC-S-09: Verify with wrong public key returns False."""
        priv, _ = keypair
        _, wrong_pub = other_keypair
        sig = sign(b"test", priv)
        assert verify(b"test", sig, wrong_pub) is False

    def test_tc_s_10_corrupted_signature(self, keypair):
        """TC-S-10: Verify with corrupted signature returns False."""
        priv, pub = keypair
        sig = sign(b"test", priv)
        # Flip one character in the base64 signature
        corrupted = ("A" if sig[0] != "A" else "B") + sig[1:]
        assert verify(b"test", corrupted, pub) is False

    def test_tc_s_11_empty_signature(self, keypair):
        """TC-S-11: Verify with empty signature string returns False."""
        _, pub = keypair
        assert verify(b"test", "", pub) is False

    def test_tc_s_12_missing_env_vars(self):
        """TC-S-12: load_signing_keys() with missing env vars raises clear error."""
        env = {
            "INKPRINT_SIGNING_KEY_PRIVATE": "",
            "INKPRINT_SIGNING_KEY_PUBLIC": "",
            "INKPRINT_KEY_ID": "",
        }
        with patch.dict(os.environ, env, clear=False), pytest.raises((ValueError, KeyError)):
            load_signing_keys()

    def test_tc_s_13_malformed_base64(self):
        """TC-S-13: load_signing_keys() with malformed base64 raises clear error."""
        env = {
            "INKPRINT_SIGNING_KEY_PRIVATE": "not-valid-base64!!!",
            "INKPRINT_SIGNING_KEY_PUBLIC": "not-valid-base64!!!",
            "INKPRINT_KEY_ID": "test",
        }
        with patch.dict(os.environ, env, clear=False), pytest.raises((ValueError, Exception)):
            load_signing_keys()

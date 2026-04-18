"""Coverage for batch_service.py edge branches.

Targets:
- Lines 84-85: langdetect failure fallback (language=None).
- Lines 179-180: verify_batch embedding recompute failure fallback.
- Lines 186-188: zero-vector unit conversion branch.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from inkprint.services import batch_service, certificate_service


@pytest.fixture(autouse=True)
def _clean() -> None:
    certificate_service.reset_store()
    yield
    certificate_service.reset_store()


@pytest.fixture()
def keys() -> tuple[Ed25519PrivateKey, object, str]:
    priv = Ed25519PrivateKey.generate()
    return priv, priv.public_key(), "test-key"


class TestLangdetectFallback:
    @pytest.mark.asyncio
    async def test_langdetect_failure_sets_language_none(
        self, keys: tuple[Ed25519PrivateKey, object, str]
    ) -> None:
        """If langdetect.detect raises, language is set to None (lines 84-85)."""
        priv, pub, kid = keys
        with (
            patch(
                "inkprint.fingerprint.embed.compute_embedding",
                new=AsyncMock(return_value=[0.1] * 768),
            ),
            patch("langdetect.detect", side_effect=RuntimeError("no features")),
        ):
            await batch_service.create_batch(
                [{"text": "short", "author": "a@b.com", "metadata": None}],
                private_key=priv,
                public_key=pub,  # type: ignore[arg-type]
                key_id=kid,
            )
        stored = next(iter(certificate_service._certificates.values()))
        assert stored["language"] is None


class TestVerifyBatchEmbeddingFallback:
    @pytest.mark.asyncio
    async def test_embedding_failure_falls_back_to_stored(
        self, keys: tuple[Ed25519PrivateKey, object, str]
    ) -> None:
        """verify_batch: re-embed failure falls back to the stored embedding."""
        priv, pub, kid = keys
        # Seed one cert with a stored [0.1]*768 embedding.
        with patch(
            "inkprint.fingerprint.embed.compute_embedding",
            new=AsyncMock(return_value=[0.1] * 768),
        ):
            created = await batch_service.create_batch(
                [{"text": "alpha", "author": "a@b.com", "metadata": None}],
                private_key=priv,
                public_key=pub,  # type: ignore[arg-type]
                key_id=kid,
            )
        cert_id = created[0]["certificate_id"]

        # Now make re-embedding fail; verify_batch should still return results.
        with patch(
            "inkprint.fingerprint.embed.compute_embedding",
            new=AsyncMock(side_effect=RuntimeError("voyage down")),
        ):
            results = await batch_service.verify_batch(
                [{"certificate_id": cert_id, "text": "alpha"}],
                public_key=pub,  # type: ignore[arg-type]
            )

        # Falls back to stored embedding, so cosine == 1.0, embedding check True.
        assert results[0]["checks"]["embedding"] is True

    @pytest.mark.asyncio
    async def test_zero_vectors_trigger_unit_substitution(
        self, keys: tuple[Ed25519PrivateKey, object, str]
    ) -> None:
        """When both embeddings are zero, unit-vector substitution kicks in."""
        priv, pub, kid = keys
        # Seed with zero embedding.
        with patch(
            "inkprint.fingerprint.embed.compute_embedding",
            new=AsyncMock(return_value=[0.0] * 768),
        ):
            created = await batch_service.create_batch(
                [{"text": "beta gamma", "author": "a@b.com", "metadata": None}],
                private_key=priv,
                public_key=pub,  # type: ignore[arg-type]
                key_id=kid,
            )
        cert_id = created[0]["certificate_id"]

        # Re-embed with zero vector also — triggers the unit-vector branch.
        with patch(
            "inkprint.fingerprint.embed.compute_embedding",
            new=AsyncMock(return_value=[0.0] * 768),
        ):
            results = await batch_service.verify_batch(
                [{"certificate_id": cert_id, "text": "beta gamma"}],
                public_key=pub,  # type: ignore[arg-type]
            )
        # With unit substitution both vectors match → cosine == 1.0.
        assert results[0]["checks"]["embedding"] is True

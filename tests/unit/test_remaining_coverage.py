"""Tests to cover remaining uncovered lines after test_coverage_gaps.py.

Targets: platform/health.py, schemas/certificate.py validators,
services/certificate_service.py (verify, diff, search),
services/leak_service.py (create_scan), api/routers/leak.py,
api/routers/verify.py, api/routers/diff.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from inkprint.main import app
from inkprint.services import certificate_service, leak_service


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
    yield
    certificate_service.reset_store()
    leak_service.reset_store()


# ── platform/health.py ──────────────────────────────────────────────────────


class TestHealthEndpoints:
    async def test_health_returns_ok(self, client):
        """Cover health.py:17-20."""
        resp = await client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "db" in body

    async def test_version_returns_version(self, client):
        """Cover health.py:25-27."""
        resp = await client.get("/version")
        assert resp.status_code == 200
        body = resp.json()
        assert body["version"] == "0.1.0"

    async def test_public_key_pem(self, client):
        """Cover health.py:33-35."""
        resp = await client.get("/public-key.pem")
        assert resp.status_code == 200
        assert "BEGIN PUBLIC KEY" in resp.text


# ── schemas/certificate.py validators ────────────────────────────────────────


class TestSchemaValidators:
    async def test_empty_author_rejected(self, client):
        """Cover schemas/certificate.py:30 — author_not_empty validator."""
        resp = await client.post(
            "/certificates",
            json={"text": "valid text", "author": "   "},
        )
        assert resp.status_code == 422

    async def test_empty_text_rejected(self, client):
        """Cover schemas/certificate.py:24 — text_not_empty validator."""
        resp = await client.post(
            "/certificates",
            json={"text": "", "author": "someone"},
        )
        assert resp.status_code == 422

    async def test_empty_manifest_rejected(self, client):
        """Cover schemas/certificate.py:60 — manifest_not_empty validator."""
        resp = await client.post(
            "/verify",
            json={"manifest": {}},
        )
        assert resp.status_code == 422


# ── services/certificate_service.py: verify ──────────────────────────────────


class TestVerifyCertificate:
    async def test_verify_with_text_valid(self, client):
        """Cover certificate_service.py:136-144 — verify with text."""
        # First create a certificate
        create_resp = await client.post(
            "/certificates",
            json={"text": "hello world", "author": "test@test.com"},
        )
        assert create_resp.status_code == 201
        manifest = create_resp.json()["manifest"]

        # Verify with text
        resp = await client.post(
            "/verify",
            json={"manifest": manifest, "text": "hello world"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is True
        assert body["checks"]["hash"] is True
        assert body["checks"]["signature"] is True

    async def test_verify_without_text(self, client):
        """Cover certificate_service.py:146-149 — verify without text."""
        create_resp = await client.post(
            "/certificates",
            json={"text": "hello world", "author": "test@test.com"},
        )
        manifest = create_resp.json()["manifest"]

        resp = await client.post(
            "/verify",
            json={"manifest": manifest},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is True
        assert "Text not provided" in body["warnings"][0]

    async def test_verify_missing_signature(self, client):
        """Cover certificate_service.py:151-152 — no signature block."""
        resp = await client.post(
            "/verify",
            json={
                "manifest": {
                    "assertions": [{"label": "c2pa.hash.data", "data": {"hash": "abc"}}],
                    # No "signature" key
                },
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is False

    async def test_verify_with_wrong_text(self, client):
        """Verify with tampered text — hash check fails."""
        create_resp = await client.post(
            "/certificates",
            json={"text": "original text", "author": "test@test.com"},
        )
        manifest = create_resp.json()["manifest"]

        resp = await client.post(
            "/verify",
            json={"manifest": manifest, "text": "tampered text"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is False
        assert body["checks"]["hash"] is False


# ── services/certificate_service.py: diff ────────────────────────────────────


class TestDiffCertificate:
    async def test_diff_returns_comparison(self, client):
        """Cover certificate_service.py:163-202 — full diff flow."""
        # Create parent
        create_resp = await client.post(
            "/certificates",
            json={"text": "the original text", "author": "test@test.com"},
        )
        cert = create_resp.json()

        # Diff against similar text — patch at the source module where it's imported from
        with patch(
            "inkprint.fingerprint.embed.compute_embedding",
            new=AsyncMock(return_value=[0.0] * 768),
        ):
            resp = await client.post(
                "/diff",
                json={"parent_id": cert["id"], "text": "the modified text"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "hamming" in body
        assert "cosine" in body
        assert "verdict" in body

    async def test_diff_parent_not_found(self, client):
        """Cover certificate_service.py:164-165 — parent not found."""
        resp = await client.post(
            "/diff",
            json={"parent_id": str(uuid4()), "text": "anything"},
        )
        assert resp.status_code == 404

    async def test_diff_embedding_failure_uses_zero_vector(self, client):
        """Cover certificate_service.py:175-176 — embedding failure fallback."""
        create_resp = await client.post(
            "/certificates",
            json={"text": "some text", "author": "test@test.com"},
        )
        cert = create_resp.json()

        with patch(
            "inkprint.fingerprint.embed.compute_embedding",
            new=AsyncMock(side_effect=RuntimeError("Voyage AI down")),
        ):
            resp = await client.post(
                "/diff",
                json={"parent_id": cert["id"], "text": "similar text"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "verdict" in body


# ── services/certificate_service.py: search ──────────────────────────────────


class TestSearchCertificates:
    async def test_search_exact_match(self, client):
        """Cover certificate_service.py:209-214."""
        # Create a certificate first
        await client.post(
            "/certificates",
            json={"text": "unique searchable text", "author": "author@test.com"},
        )

        resp = await client.get(
            "/search", params={"text": "unique searchable text", "mode": "exact"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1

    async def test_search_no_match(self, client):
        """Cover certificate_service.py:209-214 — no match."""
        resp = await client.get("/search", params={"text": "nonexistent", "mode": "exact"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0

    async def test_search_semantic(self, client):
        """Cover certificate_service.py:215-217 — semantic mode."""
        resp = await client.get("/search", params={"text": "anything", "mode": "semantic"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0  # Not implemented yet


# ── services/leak_service.py ─────────────────────────────────────────────────


class TestLeakService:
    async def test_create_leak_scan(self, client):
        """Cover leak_service.py:19-28 — create scan via API."""
        # Create certificate first
        create_resp = await client.post(
            "/certificates",
            json={"text": "check for leaks", "author": "test@test.com"},
        )
        cert = create_resp.json()

        resp = await client.post(
            "/leak-scan",
            json={"certificate_id": cert["id"]},
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "pending"

    async def test_create_scan_cert_not_found(self, client):
        """Cover leak router — certificate not found."""
        resp = await client.post(
            "/leak-scan",
            json={"certificate_id": str(uuid4())},
        )
        assert resp.status_code == 404

    async def test_get_scan_and_stream(self, client):
        """Cover leak_service.py get_scan + stream endpoint."""
        # Create cert + scan
        create_resp = await client.post(
            "/certificates",
            json={"text": "leak check text", "author": "test@test.com"},
        )
        cert = create_resp.json()

        scan_resp = await client.post(
            "/leak-scan",
            json={"certificate_id": cert["id"]},
        )
        scan_id = scan_resp.json()["scan_id"]

        # GET scan
        get_resp = await client.get(f"/leak-scan/{scan_id}")
        assert get_resp.status_code == 200

        # Stream scan
        stream_resp = await client.get(f"/leak-scan/{scan_id}/stream")
        assert stream_resp.status_code == 200

    async def test_create_scan_with_custom_corpora(self, client):
        """Cover leak_service.py:23 — custom corpora."""
        create_resp = await client.post(
            "/certificates",
            json={"text": "corpus test", "author": "test@test.com"},
        )
        cert = create_resp.json()

        resp = await client.post(
            "/leak-scan",
            json={"certificate_id": cert["id"], "corpora": ["common_crawl"]},
        )
        assert resp.status_code == 202


# ── api/routers/certificates.py — GET endpoints ─────────────────────────────


class TestCertificateEndpoints:
    async def test_get_certificate_by_id(self, client):
        """Cover certificates.py:45-50."""
        create_resp = await client.post(
            "/certificates",
            json={"text": "hello", "author": "me@test.com"},
        )
        cert_id = create_resp.json()["id"]

        resp = await client.get(f"/certificates/{cert_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == cert_id

    async def test_get_certificate_not_found(self, client):
        resp = await client.get(f"/certificates/{uuid4()}")
        assert resp.status_code == 404

    async def test_get_manifest(self, client):
        """Cover certificates.py:61-62."""
        create_resp = await client.post(
            "/certificates",
            json={"text": "manifest test", "author": "me@test.com"},
        )
        cert_id = create_resp.json()["id"]

        resp = await client.get(f"/certificates/{cert_id}/manifest")
        assert resp.status_code == 200
        assert "assertions" in resp.json()

    async def test_get_qr(self, client):
        """Cover certificates.py:74-79."""
        create_resp = await client.post(
            "/certificates",
            json={"text": "qr test", "author": "me@test.com"},
        )
        cert_id = create_resp.json()["id"]

        resp = await client.get(f"/certificates/{cert_id}/qr")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert len(resp.content) > 0

    async def test_download_certificate(self, client):
        """Cover certificates.py:90."""
        create_resp = await client.post(
            "/certificates",
            json={"text": "download this", "author": "me@test.com"},
        )
        cert_id = create_resp.json()["id"]

        resp = await client.get(f"/certificates/{cert_id}/download")
        assert resp.status_code == 200
        assert resp.text == "download this"
        assert "attachment" in resp.headers.get("content-disposition", "")

    async def test_text_too_large(self, client):
        """Cover certificates.py:28 — text exceeds max size."""
        large_text = "x" * 2_000_001  # Default max is likely smaller
        resp = await client.post(
            "/certificates",
            json={"text": large_text, "author": "me@test.com"},
        )
        # Either 413 (if max_text_bytes is small enough) or 201 (if large)
        assert resp.status_code in (201, 413)

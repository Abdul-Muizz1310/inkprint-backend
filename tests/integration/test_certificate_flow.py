"""Integration tests for the full API — spec 05-api.md.

These tests hit the FastAPI app via httpx/TestClient. They cover
certificates, verify, diff, leak-scan, search, and platform endpoints.

Marked as integration because they require the app to be wired up
(though they use a test DB, not production).
"""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from inkprint.main import app

pytestmark = pytest.mark.integration


@pytest.fixture()
async def client():
    """Async test client against the FastAPI app."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


# ── Certificates ─────────────────────────────────────────────────────────────


class TestCertificates:
    @pytest.mark.asyncio
    async def test_tc_a_01_create_certificate(self, client):
        """TC-A-01: POST /certificates with valid body returns 201."""
        resp = await client.post(
            "/certificates",
            json={"text": "Hello world", "author": "test@example.com"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert "signature" in data
        assert "manifest" in data
        assert data["author"] == "test@example.com"

    @pytest.mark.asyncio
    async def test_tc_a_02_missing_text(self, client):
        """TC-A-02: POST /certificates with missing text returns 422."""
        resp = await client.post(
            "/certificates",
            json={"author": "test@example.com"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_tc_a_03_text_too_large(self, client):
        """TC-A-03: POST /certificates with text > MAX_TEXT_BYTES returns 413."""
        resp = await client.post(
            "/certificates",
            json={"text": "x" * 600_000, "author": "test@example.com"},
        )
        assert resp.status_code == 413

    @pytest.mark.asyncio
    async def test_tc_a_04_empty_author(self, client):
        """TC-A-04: POST /certificates with empty author returns 422."""
        resp = await client.post(
            "/certificates",
            json={"text": "hello", "author": ""},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_tc_a_05_get_certificate(self, client):
        """TC-A-05: GET /certificates/{id} for existing cert returns 200."""
        create = await client.post(
            "/certificates",
            json={"text": "Test text", "author": "a@b.com"},
        )
        cert_id = create.json()["id"]
        resp = await client.get(f"/certificates/{cert_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == cert_id

    @pytest.mark.asyncio
    async def test_tc_a_06_get_nonexistent(self, client):
        """TC-A-06: GET /certificates/{id} for non-existent returns 404."""
        resp = await client.get(f"/certificates/{uuid4()}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_tc_a_07_get_manifest(self, client):
        """TC-A-07: GET /certificates/{id}/manifest returns valid C2PA JSON."""
        create = await client.post(
            "/certificates",
            json={"text": "Test", "author": "a@b.com"},
        )
        cert_id = create.json()["id"]
        resp = await client.get(f"/certificates/{cert_id}/manifest")
        assert resp.status_code == 200
        data = resp.json()
        assert "@context" in data
        assert data["version"] == "2.2"

    @pytest.mark.asyncio
    async def test_tc_a_08_get_qr(self, client):
        """TC-A-08: GET /certificates/{id}/qr returns image/png."""
        create = await client.post(
            "/certificates",
            json={"text": "Test", "author": "a@b.com"},
        )
        cert_id = create.json()["id"]
        resp = await client.get(f"/certificates/{cert_id}/qr")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert len(resp.content) > 0

    @pytest.mark.asyncio
    async def test_tc_a_09_download(self, client):
        """TC-A-09: GET /certificates/{id}/download returns original text."""
        create = await client.post(
            "/certificates",
            json={"text": "Original text here", "author": "a@b.com"},
        )
        cert_id = create.json()["id"]
        resp = await client.get(f"/certificates/{cert_id}/download")
        assert resp.status_code == 200
        assert "Original text here" in resp.text


# ── Verify ───────────────────────────────────────────────────────────────────


class TestVerify:
    @pytest.mark.asyncio
    async def test_tc_a_10_verify_valid(self, client):
        """TC-A-10: POST /verify with valid manifest returns {valid: true}."""
        create = await client.post(
            "/certificates",
            json={"text": "Verify me", "author": "a@b.com"},
        )
        manifest = create.json()["manifest"]
        resp = await client.post(
            "/verify",
            json={"manifest": manifest, "text": "Verify me"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["checks"]["signature"] is True
        assert data["checks"]["hash"] is True

    @pytest.mark.asyncio
    async def test_tc_a_11_verify_tampered(self, client):
        """TC-A-11: POST /verify with tampered manifest returns {valid: false}."""
        create = await client.post(
            "/certificates",
            json={"text": "Original", "author": "a@b.com"},
        )
        manifest = create.json()["manifest"]
        # Tamper with the hash
        for a in manifest["assertions"]:
            if a["label"] == "c2pa.hash.data":
                a["data"]["hash"] = "0" * 64
        resp = await client.post(
            "/verify",
            json={"manifest": manifest, "text": "Original"},
        )
        assert resp.status_code == 200
        assert resp.json()["valid"] is False

    @pytest.mark.asyncio
    async def test_tc_a_12_verify_manifest_only(self, client):
        """TC-A-12: POST /verify with manifest only (no text) checks signature structure."""
        create = await client.post(
            "/certificates",
            json={"text": "Test", "author": "a@b.com"},
        )
        manifest = create.json()["manifest"]
        resp = await client.post("/verify", json={"manifest": manifest})
        assert resp.status_code == 200
        # Should at least check signature validity
        assert "valid" in resp.json()

    @pytest.mark.asyncio
    async def test_tc_a_13_verify_empty_body(self, client):
        """TC-A-13: POST /verify with empty body returns 422."""
        resp = await client.post("/verify", json={})
        assert resp.status_code == 422


# ── Diff ─────────────────────────────────────────────────────────────────────


class TestDiff:
    @pytest.mark.asyncio
    async def test_tc_a_14_diff_modified(self, client):
        """TC-A-14: POST /diff with modified text returns verdict + spans."""
        create = await client.post(
            "/certificates",
            json={"text": "The quick brown fox", "author": "a@b.com"},
        )
        parent_id = create.json()["id"]
        resp = await client.post(
            "/diff",
            json={"parent_id": parent_id, "text": "The slow brown cat"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "verdict" in data
        assert "hamming" in data
        assert "cosine" in data

    @pytest.mark.asyncio
    async def test_tc_a_15_diff_nonexistent_parent(self, client):
        """TC-A-15: POST /diff with non-existent parent_id returns 404."""
        resp = await client.post(
            "/diff",
            json={"parent_id": str(uuid4()), "text": "something"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_tc_a_16_diff_identical(self, client):
        """TC-A-16: POST /diff with identical text returns verdict 'identical'."""
        text = "Exactly the same text"
        create = await client.post(
            "/certificates",
            json={"text": text, "author": "a@b.com"},
        )
        parent_id = create.json()["id"]
        resp = await client.post(
            "/diff",
            json={"parent_id": parent_id, "text": text},
        )
        assert resp.status_code == 200
        assert resp.json()["verdict"] == "identical"


# ── Leak scan ────────────────────────────────────────────────────────────────


class TestLeakScanAPI:
    @pytest.mark.asyncio
    async def test_tc_a_17_create_scan(self, client):
        """TC-A-17: POST /leak-scan returns 202 with scan_id."""
        create = await client.post(
            "/certificates",
            json={"text": "Test", "author": "a@b.com"},
        )
        cert_id = create.json()["id"]
        resp = await client.post(
            "/leak-scan",
            json={"certificate_id": cert_id},
        )
        assert resp.status_code == 202
        assert "scan_id" in resp.json()

    @pytest.mark.asyncio
    async def test_tc_a_18_get_scan(self, client):
        """TC-A-18: GET /leak-scan/{id} returns scan status."""
        create = await client.post(
            "/certificates",
            json={"text": "Test", "author": "a@b.com"},
        )
        cert_id = create.json()["id"]
        scan_resp = await client.post(
            "/leak-scan",
            json={"certificate_id": cert_id},
        )
        scan_id = scan_resp.json()["scan_id"]
        resp = await client.get(f"/leak-scan/{scan_id}")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_tc_a_19_scan_sse(self, client):
        """TC-A-19: GET /leak-scan/{id}/stream returns SSE content type."""
        create = await client.post(
            "/certificates",
            json={"text": "Test", "author": "a@b.com"},
        )
        cert_id = create.json()["id"]
        scan_resp = await client.post(
            "/leak-scan",
            json={"certificate_id": cert_id},
        )
        scan_id = scan_resp.json()["scan_id"]
        resp = await client.get(f"/leak-scan/{scan_id}/stream")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_tc_a_20_scan_nonexistent_cert(self, client):
        """TC-A-20: POST /leak-scan with non-existent cert returns 404."""
        resp = await client.post(
            "/leak-scan",
            json={"certificate_id": str(uuid4())},
        )
        assert resp.status_code == 404


# ── Search ───────────────────────────────────────────────────────────────────


class TestSearch:
    @pytest.mark.asyncio
    async def test_tc_a_21_semantic_search(self, client):
        """TC-A-21: GET /search?text=...&mode=semantic returns results."""
        resp = await client.get("/search", params={"text": "hello", "mode": "semantic"})
        assert resp.status_code == 200
        assert "results" in resp.json()

    @pytest.mark.asyncio
    async def test_tc_a_22_exact_search(self, client):
        """TC-A-22: GET /search?text=...&mode=exact returns hash matches."""
        resp = await client.get("/search", params={"text": "hello", "mode": "exact"})
        assert resp.status_code == 200
        assert "results" in resp.json()

    @pytest.mark.asyncio
    async def test_tc_a_23_search_missing_text(self, client):
        """TC-A-23: GET /search without text param returns 422."""
        resp = await client.get("/search")
        assert resp.status_code == 422


# ── Platform ─────────────────────────────────────────────────────────────────


class TestPlatform:
    @pytest.mark.asyncio
    async def test_tc_a_24_health(self, client):
        """TC-A-24: GET /health returns 200 with status ok."""
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_tc_a_25_public_key(self, client):
        """TC-A-25: GET /public-key.pem returns PEM-encoded public key."""
        resp = await client.get("/public-key.pem")
        assert resp.status_code == 200
        assert "BEGIN PUBLIC KEY" in resp.text

    @pytest.mark.asyncio
    async def test_tc_a_26_request_id_header(self, client):
        """TC-A-26: Response includes X-Request-Id header."""
        resp = await client.get("/health")
        assert "x-request-id" in resp.headers

    @pytest.mark.asyncio
    async def test_tc_a_27_cors_allowed(self, client):
        """TC-A-27: CORS preflight for allowed origin succeeds."""
        resp = await client.options(
            "/health",
            headers={
                "Origin": "https://inkprint-frontend.vercel.app",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code in (200, 204)
        assert "access-control-allow-origin" in resp.headers

    @pytest.mark.asyncio
    async def test_tc_a_28_cors_disallowed(self, client):
        """TC-A-28: CORS preflight for disallowed origin is rejected."""
        resp = await client.options(
            "/health",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") != "https://evil.example.com"

    @pytest.mark.asyncio
    async def test_tc_a_29_non_uuid_path(self, client):
        """TC-A-29: Non-UUID path parameter returns 422, not 500."""
        resp = await client.get("/certificates/not-a-uuid")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_tc_a_30_oversized_body(self, client):
        """TC-A-30: Request body > 1 MB is rejected."""
        resp = await client.post(
            "/certificates",
            json={"text": "x" * 1_100_000, "author": "a@b.com"},
        )
        assert resp.status_code in (413, 422)

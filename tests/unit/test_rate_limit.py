"""Tests for the per-IP rate-limit middleware (platform/rate_limit.py)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from inkprint.platform.rate_limit import install_rate_limit


def _make_app(*, per_minute: int, enabled: bool) -> TestClient:
    app = FastAPI()
    install_rate_limit(app, per_minute=per_minute, enabled=enabled)

    @app.post("/certificates")
    async def _create() -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/certificates/x")
    async def _get() -> dict[str, str]:
        return {"ok": "yes"}

    return TestClient(app)


def test_allows_up_to_limit_then_429() -> None:
    client = _make_app(per_minute=3, enabled=True)
    for _ in range(3):
        assert client.post("/certificates").status_code == 200
    resp = client.post("/certificates")
    assert resp.status_code == 429
    assert resp.json() == {"error": "rate limit exceeded"}
    assert "Retry-After" in resp.headers


def test_only_limits_configured_endpoints() -> None:
    client = _make_app(per_minute=1, enabled=True)
    # A non-limited (method, path) is never throttled.
    for _ in range(5):
        assert client.get("/certificates/x").status_code == 200


def test_disabled_is_noop() -> None:
    client = _make_app(per_minute=1, enabled=False)
    for _ in range(5):
        assert client.post("/certificates").status_code == 200

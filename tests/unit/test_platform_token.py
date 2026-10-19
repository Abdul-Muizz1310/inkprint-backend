"""Platform contract v2 conformance — spec 09 (PT-1..14, PT-16, PT-19, PT-24, PT-27).

Every case runs against the real application (``create_app``) built with explicit
Settings: the real middleware order, the real routers and services, in-memory
SQLite from ``tests/conftest.py``. Keys are throwaway pairs made per run.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from inkprint.core.config import Settings
from inkprint.main import create_app
from tests.platform_keys import (
    bastion_claims,
    frontend_claims,
    hs256_with_public_key,
    keypair,
    sign,
    unsigned,
    with_payload,
)

BASTION = keypair()
FRONTEND = keypair()
ORIGIN = "https://inkprint-frontend.vercel.app"
_LOGGER = "inkprint.platform.platform_token"


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "app_env": "production",
        "demo_mode": False,
        "bastion_signing_key_public": BASTION.public_b64,
        "bastion_public_key_url": "",
        "inkprint_frontend_signing_key_public": FRONTEND.public_b64,
        "rate_limit_enabled": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _client(*, address: str = "203.0.113.10", **overrides: Any) -> TestClient:
    app: FastAPI = create_app(_settings(**overrides))
    return TestClient(app, client=(address, 50000))


@pytest.fixture(autouse=True)
def _offline_leak_scan() -> Iterator[None]:
    with patch("inkprint.services.leak_service.run_scan", new=AsyncMock(return_value=None)):
        yield


def _issue(client: TestClient, token: str | None = None, **headers: str) -> Any:
    if token is not None:
        headers["X-Platform-Token"] = token
    return client.post(
        "/certificates", json={"text": "Signed callers only.", "author": "a@b.com"}, headers=headers
    )


def _invalid(resp: Any) -> None:
    assert resp.status_code == 401
    assert resp.json() == {"detail": "invalid_platform_token"}


# ── PT-1 / PT-15: authenticated ──────────────────────────────────────────────


def test_pt1_bastion_token_reaches_the_route() -> None:
    resp = _issue(_client(), sign(BASTION, bastion_claims()))
    assert resp.status_code == 201


def test_pt15_frontend_token_reaches_the_route() -> None:
    resp = _issue(_client(), sign(FRONTEND, frontend_claims()))
    assert resp.status_code == 201


# ── PT-2..PT-9: invalid tokens ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "aud", ["paper-trail", "magpie", "inkthread", "slowquery", "feathers-demo"]
)
def test_pt2_other_audience(aud: str) -> None:
    _invalid(_issue(_client(), sign(BASTION, bastion_claims(aud=aud))))


@pytest.mark.parametrize("aud", [None, ["inkprint"]])
def test_pt3_missing_or_list_audience(aud: Any) -> None:
    claims = bastion_claims(aud=aud)
    if aud is None:
        claims.pop("aud")
    _invalid(_issue(_client(), sign(BASTION, claims)))


def test_pt4_bastion_issuer_with_frontend_key() -> None:
    _invalid(_issue(_client(), sign(FRONTEND, bastion_claims())))


def test_pt4_frontend_issuer_with_bastion_key() -> None:
    _invalid(_issue(_client(), sign(BASTION, frontend_claims())))


def test_pt5_frontend_key_needs_the_frontend_role() -> None:
    _invalid(_issue(_client(), sign(FRONTEND, frontend_claims(role="admin"))))


def test_pt6_expiry_leeway() -> None:
    now = int(time.time())
    client = _client()
    ok = sign(BASTION, bastion_claims(iat=now - 65, exp=now - 5))
    assert _issue(client, ok).status_code == 201
    _invalid(_issue(client, sign(BASTION, bastion_claims(iat=now - 75, exp=now - 15))))


def test_pt7_issued_at_leeway() -> None:
    now = int(time.time())
    client = _client()
    ok = sign(BASTION, bastion_claims(iat=now + 5, exp=now + 65))
    assert _issue(client, ok).status_code == 201
    _invalid(_issue(client, sign(BASTION, bastion_claims(iat=now + 15, exp=now + 75))))


def test_pt8_alg_none_and_hs256() -> None:
    client = _client()
    _invalid(_issue(client, unsigned(bastion_claims())))
    _invalid(_issue(client, hs256_with_public_key(BASTION, bastion_claims())))


def test_pt9_tampered_payload() -> None:
    token = sign(BASTION, bastion_claims(aud="magpie"))
    _invalid(_issue(_client(), with_payload(token, bastion_claims())))


# ── PT-10 / PT-11: missing vs invalid, DEMO_MODE ─────────────────────────────


def test_pt10_missing_token_without_demo_mode() -> None:
    resp = _issue(_client())
    assert resp.status_code == 401
    assert resp.json() == {"detail": "missing_platform_token"}


def test_pt10_missing_token_with_demo_mode_proceeds_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    resp = _issue(_client(demo_mode=True))
    assert resp.status_code == 201
    assert any(
        r.levelno == logging.WARNING and "DEMO_MODE" in r.getMessage() for r in caplog.records
    )


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_header_counts_as_missing(value: str) -> None:
    resp = _issue(_client(), value)
    assert resp.json() == {"detail": "missing_platform_token"}


def test_pt11_invalid_token_is_rejected_even_in_demo_mode() -> None:
    _invalid(_issue(_client(demo_mode=True), sign(BASTION, bastion_claims(aud="magpie"))))


# ── PT-12: fail closed without a key ─────────────────────────────────────────


def _unconfigured(**overrides: Any) -> TestClient:
    return _client(
        bastion_signing_key_public="",
        bastion_public_key_url="",
        inkprint_frontend_signing_key_public="",
        **overrides,
    )


@pytest.mark.parametrize("demo_mode", [False, True])
def test_pt12_no_key_answers_503_on_protected_routes(demo_mode: bool) -> None:
    client = _unconfigured(demo_mode=demo_mode)
    for token in (None, sign(BASTION, bastion_claims())):
        resp = _issue(client, token)
        assert resp.status_code == 503
        assert resp.json() == {"detail": "platform_auth_unconfigured"}
    assert client.get("/health").status_code == 200


def test_pt12_test_settings_are_the_exception() -> None:
    assert _issue(_unconfigured(app_env="test")).status_code == 201


def test_pt24_only_malformed_keys_configured_answers_503_for_a_token() -> None:
    client = _client(bastion_signing_key_public="garbage", inkprint_frontend_signing_key_public="x")
    resp = _issue(client, sign(BASTION, bastion_claims()))
    assert resp.status_code == 503
    assert resp.json() == {"detail": "platform_auth_unconfigured"}


# ── PT-13: public and protected surfaces ─────────────────────────────────────


def _public_calls(client: TestClient) -> list[tuple[str, Any]]:
    cid = uuid4()
    return [
        ("GET /health", client.get("/health")),
        ("GET /version", client.get("/version")),
        ("GET /docs", client.get("/docs")),
        ("GET /redoc", client.get("/redoc")),
        ("GET /openapi.json", client.get("/openapi.json")),
        ("GET /metrics", client.get("/metrics")),
        ("GET /public-key.pem", client.get("/public-key.pem")),
        ("GET /certificates/{id}", client.get(f"/certificates/{cid}")),
        ("GET /certificates/{id}/manifest", client.get(f"/certificates/{cid}/manifest")),
        ("GET /certificates/{id}/qr", client.get(f"/certificates/{cid}/qr")),
        ("GET /certificates/{id}/download", client.get(f"/certificates/{cid}/download")),
        ("POST /verify", client.post("/verify", json={"manifest": {}})),
        ("POST /verify/batch", client.post("/verify/batch", json={"items": []})),
    ]


@pytest.mark.parametrize("configured", [True, False])
def test_pt13_public_routes_answer_without_a_token(configured: bool) -> None:
    client = _client() if configured else _unconfigured()
    for name, resp in _public_calls(client):
        assert resp.status_code not in (401, 403, 503), name


def test_pt13_public_reads_return_the_real_resource() -> None:
    """A certificate issued with a token is readable by anyone, binary types intact."""
    client = _client()
    cid = _issue(client, sign(BASTION, bastion_claims())).json()["id"]
    assert client.get(f"/certificates/{cid}").status_code == 200
    assert client.get(f"/certificates/{cid}/manifest").status_code == 200
    qr = client.get(f"/certificates/{cid}/qr")
    assert qr.status_code == 200 and qr.headers["content-type"] == "image/png"
    zipped = client.get(f"/certificates/{cid}/download")
    assert zipped.status_code == 200 and zipped.headers["content-type"] == "application/zip"


def test_pt13_protected_routes_demand_a_token() -> None:
    client = _client()
    cid = uuid4()
    calls = {
        "POST /certificates": lambda: _issue(client),
        "POST /certificates/batch": lambda: client.post(
            "/certificates/batch", json={"items": [{"text": "x", "author": "a@b.com"}]}
        ),
        "POST /diff": lambda: client.post("/diff", json={"parent_id": str(cid), "text": "x"}),
        "GET /search": lambda: client.get("/search", params={"text": "x"}),
        "POST /leak-scan": lambda: client.post("/leak-scan", json={"certificate_id": str(cid)}),
        "GET /leak-scan/{id}": lambda: client.get(f"/leak-scan/{cid}"),
        "GET /leak-scan/{id}/stream": lambda: client.get(f"/leak-scan/{cid}/stream"),
        "POST /dossiers/envelope": lambda: client.post("/dossiers/envelope", json={}),
    }
    for name, call in calls.items():
        resp = call()
        assert resp.status_code == 401, name
        assert resp.json() == {"detail": "missing_platform_token"}, name


# ── PT-14: rate-limit identity ───────────────────────────────────────────────


def test_pt14_bastion_requests_are_limited_per_subject() -> None:
    """``bastion:{sub}``: the visitor pseudonym is the bucket, wherever it connects from."""
    client = _client(rate_limit_enabled=True, rate_limit_per_minute=1)
    elsewhere = TestClient(client.app, client=("198.51.100.1", 50000))
    alice = sign(BASTION, bastion_claims(sub="v_alice00000"))
    bob = sign(BASTION, bastion_claims(sub="v_bob0000000"))
    assert _issue(client, alice).status_code == 201
    # Same address, another subject: its own bucket.
    assert _issue(client, bob).status_code == 201
    # Same subject from another address: the same bucket.
    alice_again = sign(BASTION, bastion_claims(sub="v_alice00000"))
    assert _issue(elsewhere, alice_again).status_code == 429


def _behind_render(**overrides: Any) -> TestClient:
    """The deployed shape: uvicorn's proxy-headers middleware ('*') in front of the app.

    Every request reaches the app from one socket peer (Render's edge), so only
    the leftmost ``X-Forwarded-For`` entry tells visitors apart.
    """
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    app = create_app(_settings(**overrides))
    return TestClient(ProxyHeadersMiddleware(app, trusted_hosts="*"), client=("10.0.0.1", 50000))


def test_pt14_two_visitors_through_the_frontend_land_in_different_buckets() -> None:
    """``{iss}:{leftmost X-Forwarded-For}``: the frontend's constant ``sub`` is not the bucket."""
    client = _behind_render(rate_limit_enabled=True, rate_limit_per_minute=1)
    alice = {"X-Forwarded-For": "203.0.113.7, 10.0.0.9"}
    bob = {"X-Forwarded-For": "198.51.100.9, 10.0.0.9"}
    assert _issue(client, sign(FRONTEND, frontend_claims()), **alice).status_code == 201
    assert _issue(client, sign(FRONTEND, frontend_claims()), **bob).status_code == 201
    # The same visitor again, with a fresh token: the same bucket.
    assert _issue(client, sign(FRONTEND, frontend_claims()), **alice).status_code == 429


def test_pt14_a_frontend_visitor_and_an_anonymous_caller_do_not_share_a_bucket() -> None:
    """The frontend bucket is prefixed with its issuer; an anonymous one is the bare address."""
    client = _behind_render(rate_limit_enabled=True, rate_limit_per_minute=1)
    alice = {"X-Forwarded-For": "203.0.113.7"}
    body = {"manifest": {}}
    # POST /verify is public, so this one is anonymous whatever it carries.
    assert client.post("/verify", json=body, headers=alice).status_code != 429
    assert _issue(client, sign(FRONTEND, frontend_claims()), **alice).status_code == 201


def test_pt14_anonymous_requests_are_limited_per_address() -> None:
    client = _client(rate_limit_enabled=True, rate_limit_per_minute=1)
    elsewhere = TestClient(client.app, client=("198.51.100.1", 50000))
    body = {"manifest": {}}
    assert client.post("/verify", json=body).status_code != 429
    assert elsewhere.post("/verify", json=body).status_code != 429
    assert client.post("/verify", json=body).status_code == 429


def test_pt14_frontend_and_bastion_subjects_do_not_share_a_bucket() -> None:
    client = _client(rate_limit_enabled=True, rate_limit_per_minute=1)
    assert _issue(client, sign(BASTION, bastion_claims(sub="inkprint-frontend"))).status_code == 201
    assert _issue(client, sign(FRONTEND, frontend_claims())).status_code == 201


# ── PT-16: where the token is read from ──────────────────────────────────────


def test_pt16_bearer_token_is_accepted() -> None:
    token = sign(BASTION, bastion_claims())
    resp = _issue(_client(), Authorization=f"Bearer {token}")
    assert resp.status_code == 201


def test_pt16_platform_header_wins_over_bearer() -> None:
    good = sign(BASTION, bastion_claims())
    bad = sign(BASTION, bastion_claims(aud="magpie"))
    _invalid(_issue(_client(), bad, Authorization=f"Bearer {good}"))


@pytest.mark.parametrize("value", ["Basic abc", "Bearer", "Bearer   ", "bearer"])
def test_pt16_non_bearer_authorization_is_no_token(value: str) -> None:
    resp = _issue(_client(), Authorization=value)
    assert resp.json() == {"detail": "missing_platform_token"}


# ── PT-19: CORS ──────────────────────────────────────────────────────────────


def test_pt19_preflight_allows_the_platform_token_header() -> None:
    resp = _client().options(
        "/certificates",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type, x-platform-token, x-request-id",
        },
    )
    assert resp.status_code == 200
    allowed = resp.headers["access-control-allow-headers"].lower()
    for header in ("content-type", "x-platform-token", "x-request-id"):
        assert header in allowed


def test_pt19_rejections_carry_cors_headers() -> None:
    resp = _issue(_client(), Origin=ORIGIN)
    assert resp.status_code == 401
    assert resp.headers["access-control-allow-origin"] == ORIGIN
    assert "x-request-id" in resp.headers


# ── PT-27: logging ───────────────────────────────────────────────────────────


def test_pt27_rejection_warning_names_the_check_never_the_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    token = sign(BASTION, bastion_claims(aud="magpie"))
    _invalid(_issue(_client(), token))
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("audience" in m for m in messages)
    assert not any(token in m or token.split(".")[1] in m for m in messages)


def test_pt12_unconfigured_rejection_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    _issue(_unconfigured())
    assert any("unconfigured" in r.getMessage() for r in caplog.records)

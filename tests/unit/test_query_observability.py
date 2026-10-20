"""Query observability — spec 10 (slowquery-detective 0.2 wired into inkprint).

The app is the real one (``create_app``) on the per-test in-memory SQLite engine
from ``tests/conftest.py``, so the statements the library observes are the ones
the real routes and repositories run. SQLite selects the in-memory store.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from slowquery_detective import InMemoryStoreWriter, PostgresStoreWriter
from slowquery_detective.tagging import RequestIdMiddleware
from sqlalchemy import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request

from inkprint.core import db
from inkprint.core.config import Settings
from inkprint.main import create_app
from inkprint.platform.public_routes import is_public
from inkprint.platform.query_observability import authorize_bastion, store_url_for
from inkprint.platform.token_verifier import Principal
from tests.platform_keys import bastion_claims, frontend_claims, keypair, sign

BASTION = keypair()
FRONTEND = keypair()
REQ = "req-qo-0001"


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


@asynccontextmanager
async def _client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture(autouse=True)
def _offline_leak_scan() -> Any:
    with patch("inkprint.services.leak_service.run_scan", new=AsyncMock(return_value=None)):
        yield


def _bastion() -> dict[str, str]:
    return {"X-Platform-Token": sign(BASTION, bastion_claims())}


async def _issue(client: AsyncClient, request_id: str) -> None:
    resp = await client.post(
        "/certificates",
        json={"text": "Measured by the dossier.", "author": "a@b.com"},
        headers={**_bastion(), "X-Request-Id": request_id},
    )
    assert resp.status_code == 201, resp.text


async def _measure(client: AsyncClient, request_id: str, headers: dict[str, str]) -> Any:
    return await client.get(
        "/_slowquery/queries", params={"request_id": request_id}, headers=headers
    )


# ── QO-1..QO-5: the measure flow through the real app ────────────────────────


async def test_qo1_a_tagged_request_is_listed_for_bastion() -> None:
    app = create_app(_settings())
    async with _client(app) as client:
        await _issue(client, REQ)
        resp = await _measure(client, REQ, _bastion())
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    inserts = [r for r in rows if "insert into certificates" in r["fingerprint"].lower()]
    assert inserts, [r["fingerprint"] for r in rows]
    assert inserts[0]["call_count"] >= 1
    assert all(r["p50_ms"] is None and r["p95_ms"] is None for r in rows)


async def test_qo2_no_token_is_401() -> None:
    app = create_app(_settings())
    async with _client(app) as client:
        resp = await _measure(client, REQ, {})
    assert resp.status_code == 401
    assert resp.json() == {"detail": "missing_platform_token"}


async def test_qo3_frontend_token_is_403() -> None:
    app = create_app(_settings())
    async with _client(app) as client:
        resp = await _measure(client, REQ, {"X-Platform-Token": sign(FRONTEND, frontend_claims())})
    assert resp.status_code == 403


async def test_qo3_anonymous_demo_mode_request_is_403() -> None:
    app = create_app(_settings(demo_mode=True))
    async with _client(app) as client:
        resp = await _measure(client, REQ, {})
    assert resp.status_code == 403


async def test_qo4_invalid_token_is_401() -> None:
    app = create_app(_settings())
    async with _client(app) as client:
        bad = sign(BASTION, bastion_claims(aud="magpie"))
        resp = await _measure(client, REQ, {"X-Platform-Token": bad})
    assert resp.status_code == 401
    assert resp.json() == {"detail": "invalid_platform_token"}


async def test_qo5_requests_are_kept_apart_and_measuring_adds_nothing() -> None:
    app = create_app(_settings())
    async with _client(app) as client:
        await _issue(client, REQ)
        other = await _measure(client, "req-qo-other", _bastion())
        first = await _measure(client, REQ, {**_bastion(), "X-Request-Id": REQ})
        second = await _measure(client, REQ, {**_bastion(), "X-Request-Id": REQ})
    assert other.json() == []

    def counts(resp: Any) -> dict[str, int]:
        return {r["id"]: r["call_count"] for r in resp.json()}

    assert counts(first) == counts(second)


# ── QO-6, QO-7: the pure pieces ──────────────────────────────────────────────


def _request_with(principal: Principal | None) -> Request:
    request = Request({"type": "http", "headers": [], "state": {}})
    if principal is not None:
        request.state.platform_principal = principal
    return request


@pytest.mark.parametrize(
    ("principal", "allowed"),
    [
        (None, False),
        (Principal(iss="inkprint-frontend", sub="inkprint-frontend", role="frontend"), False),
        (Principal(iss="bastion", sub="v_abcdef1234", role="viewer"), True),
        (Principal(iss="bastion", sub="bastion", role=None), True),
    ],
)
async def test_qo6_only_a_bastion_principal_is_authorized(
    principal: Principal | None, allowed: bool
) -> None:
    assert await authorize_bastion(_request_with(principal)) is allowed


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgresql+asyncpg://u:secret@db.example:5432/inkprint?ssl=require", True),
        ("postgresql://u:secret@db.example/inkprint", True),
        ("sqlite+aiosqlite://", False),
        ("sqlite+aiosqlite:///./inkprint.db", False),
    ],
)
def test_qo7_store_url_is_the_engines_own_postgres_url(url: str, expected: bool) -> None:
    result = store_url_for(make_url(url))
    if expected:
        assert result is not None
        assert make_url(result) == make_url(url)
        assert "secret" in result  # the store must be able to log in
    else:
        assert result is None


# ── QO-8..QO-10: wiring ──────────────────────────────────────────────────────


def test_qo8_sqlite_selects_the_in_memory_store() -> None:
    app = create_app(_settings())
    assert isinstance(app.state.slowquery_store, InMemoryStoreWriter)
    assert app.state.slowquery_installed is True


async def test_qo8_a_postgres_engine_selects_the_postgres_store_without_connecting() -> None:
    engine = create_async_engine("postgresql+asyncpg://u:p@127.0.0.1:1/never")
    db.configure_engine(engine)
    app = create_app(_settings())
    assert isinstance(app.state.slowquery_store, PostgresStoreWriter)


def test_qo9_cors_stays_outermost_with_the_tagger_directly_inside() -> None:
    app = create_app(_settings())
    classes = [m.cls for m in app.user_middleware]
    assert classes[0] is CORSMiddleware
    assert classes[1] is RequestIdMiddleware
    assert classes.count(RequestIdMiddleware) == 1


@pytest.mark.parametrize(
    "path", ["/_slowquery/queries", "/_slowquery/queries/0123456789abcdef", "/_slowquery"]
)
def test_qo10_slowquery_routes_are_not_public(path: str) -> None:
    assert is_public("GET", path) is False

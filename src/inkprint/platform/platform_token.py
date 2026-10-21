"""X-Platform-Token middleware — platform contract v2 (spec 09).

The imperative shell around ``token_verifier``: it decides public vs protected
(``public_routes``), resolves the trusted keys (``trusted_keys``), reads the token
from ``X-Platform-Token`` or ``Authorization: Bearer``, and answers:

- no key source configured ⇒ 503 ``platform_auth_unconfigured`` (fail closed),
  except under the test settings;
- no token ⇒ 401 ``missing_platform_token``, unless ``DEMO_MODE`` (then anonymous,
  logged);
- a token that fails any check ⇒ 401 ``invalid_platform_token`` — in
  ``DEMO_MODE`` too;
- a valid token ⇒ the request proceeds with its ``Principal`` attached, which the
  rate limiter keys on.

The token itself is never logged; a rejection logs the check that failed.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Final

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers

from inkprint.core.config import Settings
from inkprint.platform.public_routes import is_public
from inkprint.platform.token_verifier import (
    Accepted,
    Principal,
    Rejected,
    verify_platform_token,
)
from inkprint.platform.trusted_keys import TrustedKeySource

logger = logging.getLogger(__name__)

_Handler = Callable[[Request], Awaitable[Response]]

_HEADER: Final = "x-platform-token"
_STATE_KEY: Final = "platform_principal"


def read_token(headers: Headers) -> str | None:
    """``X-Platform-Token`` first, then ``Authorization: Bearer``; blank means none."""
    direct = headers.get(_HEADER, "").strip()
    if direct:
        return direct
    scheme, _, credentials = headers.get("authorization", "").strip().partition(" ")
    if scheme.lower() == "bearer" and credentials.strip():
        return credentials.strip()
    return None


def request_principal(request: Request) -> Principal | None:
    """The authenticated caller of ``request``, or ``None`` for an anonymous one."""
    principal = getattr(request.state, _STATE_KEY, None)
    return principal if isinstance(principal, Principal) else None


def _deny(status: int, detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status)


def install_platform_token(
    app: FastAPI, *, settings: Settings, keys: TrustedKeySource | None = None
) -> None:
    """Attach the contract-v2 verification middleware to ``app``."""
    source = keys or TrustedKeySource.from_settings(settings)
    demo_mode = settings.demo_mode
    fail_open_without_keys = settings.is_test
    if demo_mode:
        logger.warning("DEMO_MODE active: requests without a platform token proceed anonymously")

    @app.middleware("http")
    async def _platform_token_middleware(request: Request, call_next: _Handler) -> Response:
        method, path = request.method, request.url.path
        if is_public(method, path):
            return await call_next(request)

        if not source.is_configured():
            if fail_open_without_keys:
                return await call_next(request)
            logger.warning("platform auth unconfigured: refusing %s %s", method, path)
            return _deny(503, "platform_auth_unconfigured")

        token = read_token(request.headers)
        if token is None:
            if demo_mode:
                logger.warning("DEMO_MODE: anonymous %s %s (no platform token)", method, path)
                return await call_next(request)
            return _deny(401, "missing_platform_token")

        trusted = await source.resolve()
        if not trusted:
            logger.warning(
                "platform auth unconfigured: no trusted key resolved for %s %s", method, path
            )
            return _deny(503, "platform_auth_unconfigured")

        match verify_platform_token(token, trusted, now=int(time.time())):
            case Rejected(reason=reason):
                logger.warning("platform token rejected (%s) on %s %s", reason, method, path)
                return _deny(401, "invalid_platform_token")
            case Accepted(principal=principal):
                setattr(request.state, _STATE_KEY, principal)
                return await call_next(request)

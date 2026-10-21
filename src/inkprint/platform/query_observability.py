"""slowquery-detective 0.2 wiring — spec 10.

``GET /_slowquery/queries?request_id=R`` lists the queries a request tagged
``X-Request-Id: R`` ran, for bastion's dossier "measure" stage. Only a request
the contract-v2 middleware authenticated with **bastion's** key may read it.
"""

from __future__ import annotations

from typing import Final

from fastapi import FastAPI, Request
from slowquery_detective import install
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine

from inkprint.platform.platform_token import request_principal
from inkprint.platform.token_verifier import BASTION_ISSUER, SERVICE_ID

MOUNT_PATH: Final = "/_slowquery"


async def authorize_bastion(request: Request) -> bool:
    """True only for a caller authenticated with bastion's key (``iss == "bastion"``).

    The route is not public (spec 09 §4), so a missing or invalid token was
    already answered 401 by the platform-token middleware; what reaches here is
    a bastion principal, a frontend principal or an anonymous ``DEMO_MODE``
    request, and only the first may read.
    """
    principal = request_principal(request)
    return principal is not None and principal.iss == BASTION_ISSUER


def store_url_for(url: URL) -> str | None:
    """The engine's own URL when it is Postgres (the store lives beside the data), else None."""
    if url.get_backend_name() != "postgresql":
        return None
    return url.render_as_string(hide_password=False)


def install_query_observability(app: FastAPI, engine: AsyncEngine) -> None:
    """Attach slowquery-detective to ``app`` and the engine every repository uses.

    Call it after every middleware that may run a statement and before CORS, so
    the host's work is attributed and CORS stays outermost (spec 10).
    """
    install(
        app,
        engine,
        service=SERVICE_ID,
        store_url=store_url_for(engine.url),
        authorize=authorize_bastion,
        mount_path=MOUNT_PATH,
    )

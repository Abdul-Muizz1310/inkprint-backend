"""The Voyage client — spec 07 TC-B-10e and TC-B-10f.

The SDK's default request timeout is 600 s; a rate-limited or hung embedding
call must not eat bastion's 60 s budget for the batch call (TC-B-10e). And a
successful answer must survive the real SDK path (TC-B-10f): every other test
replaces the SDK, and callers swallow any failure into the zero vector, so an
SDK upgrade that broke the success path would otherwise pass unnoticed.
"""

from __future__ import annotations

import base64
import struct
import time
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import voyageai
import voyageai.error
from aiohttp import web
from aiohttp.test_utils import TestServer

from inkprint.core.config import get_settings
from inkprint.fingerprint import embed


@pytest.fixture(autouse=True)
def _fresh_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("VOYAGE_API_KEY", "pa-test-not-a-real-key")
    embed._client.cache_clear()
    yield
    embed._client.cache_clear()


def test_client_never_retries_and_times_out_in_15s() -> None:
    client = embed._client()
    assert client.max_retries == 0
    assert client._params["request_timeout"] == embed.EMBED_TIMEOUT_S == 15.0


async def test_a_429_makes_one_request_and_fails_fast() -> None:
    rate_limited = AsyncMock(
        side_effect=voyageai.error.RateLimitError("reduced rate limits", http_status=429)
    )
    with patch.object(voyageai.Embedding, "acreate", new=rate_limited):
        started = time.monotonic()
        with pytest.raises(voyageai.error.RateLimitError):
            await embed.compute_embeddings(["one page", "another page"])
        elapsed = time.monotonic() - started
    assert rate_limited.await_count == 1
    assert elapsed < 2.0
    assert rate_limited.await_args.kwargs["request_timeout"] == 15.0


def _base64_float32(vector: list[float]) -> str:
    return base64.b64encode(struct.pack(f"<{len(vector)}f", *vector)).decode("ascii")


async def test_tc_b_10f_a_successful_answer_survives_the_real_sdk_path() -> None:
    vectors = [[0.5, -0.25, 1.0], [0.0, 2.0, -1.5]]
    requests: list[dict[str, Any]] = []

    async def embeddings(request: web.Request) -> web.Response:
        requests.append(await request.json())
        return web.json_response(
            {
                "object": "list",
                "data": [
                    {"object": "embedding", "embedding": _base64_float32(v), "index": i}
                    for i, v in enumerate(vectors)
                ],
                "model": get_settings().voyage_model,
                "usage": {"total_tokens": 7},
            }
        )

    app = web.Application()
    app.router.add_post("/v1/embeddings", embeddings)
    async with TestServer(app) as server:
        embed._client()._params["base_url"] = str(server.make_url("/v1"))
        result = await embed.compute_embeddings(["one page", "another page"])

    assert result == vectors
    assert len(requests) == 1
    assert requests[0]["input"] == ["one page", "another page"]
    assert requests[0]["model"] == get_settings().voyage_model

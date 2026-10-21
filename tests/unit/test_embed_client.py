"""The Voyage client fails fast — spec 07 TC-B-10e.

The SDK's default request timeout is 600 s; a rate-limited or hung embedding
call must not eat bastion's 60 s budget for the batch call.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
import voyageai
import voyageai.error

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

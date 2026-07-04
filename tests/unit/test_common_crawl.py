"""Tests for inkprint.leak.common_crawl — real WARC fetch + SimHash gate.

Pins the fix for the CRITICAL finding: the client now fetches each CDX
candidate's WARC payload and only reports it as a hit when its content clears
the SimHash near-duplicate threshold, propagating a genuine ``hamming``/``score``
(never the old hardcoded 0.5). The httpx boundary is mocked with respx — no
network, no paid APIs.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from inkprint.fingerprint.simhash import compute_simhash
from inkprint.leak.common_crawl import scan_common_crawl

_CDX = "https://index.commoncrawl.org"
_WARC = "https://data.commoncrawl.org"


def _cdx_record() -> str:
    return json.dumps(
        {
            "url": "http://example.com/leaked",
            "filename": "f.warc.gz",
            "offset": "0",
            "length": "500",
        }
    )


def _warc_payload(body_text: str) -> bytes:
    # WARC headers + HTTP headers + body, separated by blank lines; the client
    # takes everything after the last header block.
    return b"WARC/1.0\r\nWARC-Type: response\r\n\r\nHTTP/1.1 200 OK\r\n\r\n" + body_text.encode()


@respx.mock
@pytest.mark.asyncio
async def test_near_duplicate_content_is_a_scored_hit() -> None:
    leaked = (
        "the confidential draft chapter that was scraped into the training corpus verbatim " * 3
    )
    simhash = compute_simhash(leaked)

    respx.get(url__startswith=_CDX).mock(return_value=httpx.Response(200, text=_cdx_record()))
    respx.get(url__startswith=_WARC).mock(
        return_value=httpx.Response(200, content=_warc_payload(leaked))
    )

    result = await scan_common_crawl(leaked, simhash)

    assert result["hit_count"] == 1
    hit = result["hits"][0]
    # Genuine similarity, not a hardcoded 0.5.
    assert hit["hamming"] == 0
    assert hit["score"] == 1.0
    assert hit["url"] == "http://example.com/leaked"


@respx.mock
@pytest.mark.asyncio
async def test_dissimilar_candidate_is_gated_out() -> None:
    query = "the confidential draft chapter about medieval poetry and its meter " * 3
    simhash = compute_simhash(query)
    unrelated = "async event loops schedule coroutines onto a single OS thread " * 3

    respx.get(url__startswith=_CDX).mock(return_value=httpx.Response(200, text=_cdx_record()))
    respx.get(url__startswith=_WARC).mock(
        return_value=httpx.Response(200, content=_warc_payload(unrelated))
    )

    result = await scan_common_crawl(query, simhash)

    # Candidate fetched but rejected by the similarity gate — no false hit.
    assert result["hit_count"] == 0
    assert result["hits"] == []


@respx.mock
@pytest.mark.asyncio
async def test_empty_cdx_returns_no_hits() -> None:
    simhash = compute_simhash("anything at all")
    respx.get(url__startswith=_CDX).mock(return_value=httpx.Response(200, text=""))
    result = await scan_common_crawl("anything at all", simhash)
    assert result["hit_count"] == 0

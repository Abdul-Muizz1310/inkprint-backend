"""Common Crawl CDX API client for leak detection.

Strategy (spec 04-leak-scanner.md §Per-corpus clients):

1. Query the CDX index for candidate capture records.
2. Fetch each candidate's WARC payload (range request against
   ``data.commoncrawl.org``) and extract its text.
3. Compute the SimHash Hamming distance between the submitted text and the
   candidate; keep it only when it clears the near-duplicate threshold.

The similarity gate (step 3) is what makes a "hit" meaningful — the CDX index is
URL-keyed and cannot itself full-text-search, so every candidate is verified by
real content comparison before it is reported. The WARC fetch is the imperative
shell (mocked in tests); the scoring is pure and lives in
:mod:`inkprint.leak.similarity`.
"""

from __future__ import annotations

import asyncio
import contextlib
import gzip
import re
from typing import Any

import httpx

from inkprint.leak.similarity import compare_text, is_leak

_CDX_RATE_LIMIT: asyncio.Semaphore | None = None

_SNAPSHOT = "CC-MAIN-2024-50"
_MAX_CANDIDATES = 10
_WARC_BASE = "https://data.commoncrawl.org"
_TAG_RE = re.compile(rb"<[^>]+>")


def _get_rate_limit() -> asyncio.Semaphore:
    global _CDX_RATE_LIMIT
    if _CDX_RATE_LIMIT is None:
        _CDX_RATE_LIMIT = asyncio.Semaphore(1)
    return _CDX_RATE_LIMIT


def _parse_cdx(body: str) -> list[dict[str, Any]]:
    """Parse CDX JSON-lines output into candidate records."""
    records: list[dict[str, Any]] = []
    for line in body.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            import json

            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            records.append(rec)
    return records


def _extract_text(payload: bytes) -> str:
    """Best-effort plain-text extraction from a WARC HTTP payload."""
    # A WARC record range decompresses to WARC headers + HTTP headers + body,
    # separated by blank lines. Take everything after the last header block.
    parts = payload.split(b"\r\n\r\n")
    body = parts[-1] if len(parts) > 1 else payload
    stripped = _TAG_RE.sub(b" ", body)
    return stripped.decode("utf-8", errors="ignore")


async def _fetch_document_text(client: httpx.AsyncClient, record: dict[str, Any]) -> str:
    """Fetch and extract the text of a single CDX candidate via a WARC range GET.

    Returns an empty string when the record lacks WARC coordinates or the fetch
    fails — the caller then treats it as maximally distant (not a leak).
    """
    filename = record.get("filename")
    offset = record.get("offset")
    length = record.get("length")
    if not filename or offset is None or length is None:
        return ""
    try:
        start = int(offset)
        end = start + int(length) - 1
    except (TypeError, ValueError):
        return ""
    try:
        resp = await client.get(
            f"{_WARC_BASE}/{filename}",
            headers={"Range": f"bytes={start}-{end}"},
        )
        if resp.status_code not in (200, 206):
            return ""
        raw = resp.content
        # Some ranges are already plain (not gzip); tolerate both.
        with contextlib.suppress(OSError, EOFError):
            raw = gzip.decompress(raw)
        return _extract_text(raw)
    except (httpx.TimeoutException, httpx.HTTPError):
        return ""


async def scan_common_crawl(
    text: str,
    simhash: int,
    cdx_url: str = "https://index.commoncrawl.org/CC-MAIN-2024-50-index",
) -> dict[str, Any]:
    """Query Common Crawl for near-duplicates of ``text`` and score real hits.

    A candidate is reported only when its WARC content clears the SimHash
    near-duplicate threshold; each hit carries a genuine ``hamming`` distance
    and ``score``.
    """
    query_text = text[:100].strip().replace('"', "")
    empty = {"corpus": "common_crawl", "hits": [], "hit_count": 0, "snapshot": _SNAPSHOT}
    if not query_text:
        return empty

    async with _get_rate_limit():
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    cdx_url,
                    params={
                        "url": query_text,
                        "output": "json",
                        "fl": "url,filename,offset,length",
                        "limit": _MAX_CANDIDATES,
                    },
                )
                if resp.status_code != 200 or not resp.text.strip():
                    return empty

                hits: list[dict[str, Any]] = []
                for record in _parse_cdx(resp.text)[:_MAX_CANDIDATES]:
                    candidate_text = await _fetch_document_text(client, record)
                    hamming, score = compare_text(simhash, candidate_text)
                    if not is_leak(hamming):
                        continue
                    hits.append(
                        {
                            "url": str(record.get("url", "")),
                            "excerpt": candidate_text[:200],
                            "score": score,
                            "hamming": hamming,
                        }
                    )
                return {
                    "corpus": "common_crawl",
                    "hits": hits,
                    "hit_count": len(hits),
                    "snapshot": _SNAPSHOT,
                }
        except (httpx.TimeoutException, httpx.HTTPError):
            pass

    return empty

"""The Stack v2 (BigCode) index API client for leak detection."""

from __future__ import annotations

from typing import Any

import httpx


async def scan_the_stack(
    text: str,
    api_url: str = "https://huggingface.co/api/datasets/bigcode/the-stack-v2",
) -> dict[str, Any]:
    """Query The Stack v2 index for code leak matches.

    Gated: requires HuggingFace auth token + TOS acceptance.
    Raises PermissionError if unavailable.
    """
    query = text[:200].strip()
    if not query:
        return {"corpus": "the_stack_v2", "hits": [], "hit_count": 0}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{api_url}/search",
                params={"query": query, "limit": 10},
            )
            if resp.status_code == 401 or resp.status_code == 403:
                raise PermissionError("HF token not set or TOS not accepted for The Stack v2")
            if resp.status_code == 200:
                data = resp.json()
                hits = [
                    {"url": r.get("url", ""), "excerpt": "", "score": 0.5}
                    for r in data.get("rows", [])[:10]
                ]
                return {"corpus": "the_stack_v2", "hits": hits, "hit_count": len(hits)}
    except PermissionError:
        raise
    except (httpx.TimeoutException, httpx.HTTPError):
        pass

    return {"corpus": "the_stack_v2", "hits": [], "hit_count": 0}

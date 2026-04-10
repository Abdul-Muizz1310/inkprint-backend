"""HuggingFace datasets search API client for leak detection."""

from __future__ import annotations

from typing import Any

import httpx


async def scan_huggingface(
    text: str,
    api_url: str = "https://datasets-server.huggingface.co",
) -> dict[str, Any]:
    """Query HuggingFace datasets search for text matches."""
    query = text[:200].strip()
    if not query:
        return {"corpus": "huggingface", "hits": [], "hit_count": 0}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{api_url}/search",
                params={"query": query, "limit": 10},
            )
            if resp.status_code == 200:
                data = resp.json()
                hits = [
                    {"url": r.get("dataset", ""), "excerpt": "", "score": 0.5}
                    for r in data.get("rows", [])[:10]
                ]
                return {"corpus": "huggingface", "hits": hits, "hit_count": len(hits)}
    except (httpx.TimeoutException, httpx.HTTPError):
        pass

    return {"corpus": "huggingface", "hits": [], "hit_count": 0}

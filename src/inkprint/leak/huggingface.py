"""HuggingFace datasets search API client for leak detection."""

from __future__ import annotations

from typing import Any

import httpx

from inkprint.leak.similarity import compare_text, is_leak


def _row_text(row: dict[str, Any]) -> str:
    """Concatenate the string-valued columns of a datasets-server row."""
    values = row.get("row", row) if isinstance(row.get("row"), dict) else row
    parts = [str(v) for v in values.values() if isinstance(v, str)]
    return " ".join(parts)


async def scan_huggingface(
    text: str,
    simhash: int,
    api_url: str = "https://datasets-server.huggingface.co",
) -> dict[str, Any]:
    """Query HuggingFace datasets search and score real near-duplicate hits."""
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
                hits: list[dict[str, Any]] = []
                for r in data.get("rows", [])[:10]:
                    candidate_text = _row_text(r)
                    hamming, score = compare_text(simhash, candidate_text)
                    if not is_leak(hamming):
                        continue
                    hits.append(
                        {
                            "url": str(r.get("dataset", "")),
                            "excerpt": candidate_text[:200],
                            "score": score,
                            "hamming": hamming,
                        }
                    )
                return {"corpus": "huggingface", "hits": hits, "hit_count": len(hits)}
    except (httpx.TimeoutException, httpx.HTTPError):
        pass

    return {"corpus": "huggingface", "hits": [], "hit_count": 0}

"""The Stack v2 (BigCode) index API client for leak detection."""

from __future__ import annotations

from typing import Any

import httpx

from inkprint.leak.similarity import compare_text, is_leak


def _row_text(row: dict[str, Any]) -> str:
    """Concatenate the string-valued fields of a Stack v2 result row."""
    values = row.get("row", row) if isinstance(row.get("row"), dict) else row
    parts = [str(v) for v in values.values() if isinstance(v, str)]
    return " ".join(parts)


async def scan_the_stack(
    text: str,
    simhash: int,
    api_url: str = "https://huggingface.co/api/datasets/bigcode/the-stack-v2",
) -> dict[str, Any]:
    """Query The Stack v2 index and score real near-duplicate code hits.

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
                hits: list[dict[str, Any]] = []
                for r in data.get("rows", [])[:10]:
                    candidate_text = _row_text(r)
                    hamming, score = compare_text(simhash, candidate_text)
                    if not is_leak(hamming):
                        continue
                    hits.append(
                        {
                            "url": str(r.get("url", "")),
                            "excerpt": candidate_text[:200],
                            "score": score,
                            "hamming": hamming,
                        }
                    )
                return {"corpus": "the_stack_v2", "hits": hits, "hit_count": len(hits)}
    except PermissionError:
        raise
    except (httpx.TimeoutException, httpx.HTTPError):
        pass

    return {"corpus": "the_stack_v2", "hits": [], "hit_count": 0}

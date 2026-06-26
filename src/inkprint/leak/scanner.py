"""Leak scanner orchestrator — runs corpus scans in parallel."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

from inkprint.leak.common_crawl import scan_common_crawl
from inkprint.leak.huggingface import scan_huggingface
from inkprint.leak.score import ScoreResult, score
from inkprint.leak.the_stack import scan_the_stack

logger = logging.getLogger(__name__)

VALID_CORPORA = {"common_crawl", "huggingface", "the_stack_v2"}
CORPUS_TIMEOUT = 30.0  # seconds per corpus


@dataclass
class ScanResult:
    """Aggregated result from all corpora."""

    corpus_results: list[dict[str, Any]] = field(default_factory=list)
    score: ScoreResult | None = None


def validate_corpora(corpora: list[str]) -> None:
    """Validate that all corpus names are known."""
    for c in corpora:
        if c not in VALID_CORPORA:
            raise ValueError(f"Unknown corpus: {c!r}. Valid: {VALID_CORPORA}")


def cache_key(content_hash: str, corpus: str, snapshot: str) -> str:
    """Generate a deterministic cache key for scan results."""
    raw = f"{content_hash}:{corpus}:{snapshot}"
    return hashlib.sha256(raw.encode()).hexdigest()


CorpusScanFn = Callable[..., Coroutine[Any, Any, dict[str, Any]]]


async def _run_corpus(
    name: str,
    factory: CorpusScanFn,
    args: tuple[Any, ...] = (),
    max_retries: int = 2,
) -> dict[str, Any]:
    """Run a single corpus scan with timeout, retry, and error handling."""
    for attempt in range(max_retries):
        try:
            coro = factory(*args)
            result = await asyncio.wait_for(coro, timeout=CORPUS_TIMEOUT)
            return result
        except TimeoutError:
            logger.warning("Corpus %s timed out (attempt %d)", name, attempt + 1)
            if attempt == max_retries - 1:
                return {"corpus": name, "hits": [], "hit_count": 0, "status": "timeout"}
        except PermissionError as e:
            logger.warning("Corpus %s unavailable: %s", name, e)
            return {"corpus": name, "hits": [], "hit_count": 0, "status": "skipped"}
        except Exception as e:
            logger.warning("Corpus %s failed (attempt %d): %s", name, attempt + 1, e)
            if attempt == max_retries - 1:
                return {"corpus": name, "hits": [], "hit_count": 0, "status": "error"}

    return {"corpus": name, "hits": [], "hit_count": 0, "status": "error"}


def _build_tasks(
    corpora: list[str], text: str, simhash: int
) -> list[tuple[str, CorpusScanFn, tuple[Any, ...]]]:
    """Build (name, factory, args) tuples for requested corpora."""
    tasks: list[tuple[str, CorpusScanFn, tuple[Any, ...]]] = []
    if "common_crawl" in corpora:
        tasks.append(("common_crawl", scan_common_crawl, (text, simhash)))
    if "huggingface" in corpora:
        tasks.append(("huggingface", scan_huggingface, (text,)))
    if "the_stack_v2" in corpora:
        tasks.append(("the_stack_v2", scan_the_stack, (text,)))
    return tasks


async def scan(
    text: str,
    simhash: int,
    corpora: list[str] | None = None,
) -> ScanResult:
    """Run a leak scan of ``text`` across the requested corpora.

    Returns an aggregated :class:`ScanResult`. Persistence is the caller's
    responsibility (see :mod:`inkprint.services.leak_service`).
    """
    if corpora is None:
        corpora = list(VALID_CORPORA)
    validate_corpora(corpora)

    tasks = _build_tasks(corpora, text, simhash)

    results = await asyncio.gather(
        *(_run_corpus(name, factory, args) for name, factory, args in tasks)
    )

    all_hits: list[dict[str, Any]] = []
    for r in results:
        all_hits.extend(r.get("hits", []))

    return ScanResult(corpus_results=list(results), score=score(all_hits))


async def scan_stream(
    text: str,
    simhash: int,
    corpora: list[str] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Yield one event per corpus as it completes (for SSE)."""
    if corpora is None:
        corpora = list(VALID_CORPORA)
    validate_corpora(corpora)
    return _stream_scan(_build_tasks(corpora, text, simhash))


async def _stream_scan(
    tasks: list[tuple[str, CorpusScanFn, tuple[Any, ...]]],
) -> AsyncIterator[dict[str, Any]]:
    """Yield events as each corpus completes."""
    for name, factory, args in tasks:
        result = await _run_corpus(name, factory, args)
        yield {"type": "corpus_complete", **result}

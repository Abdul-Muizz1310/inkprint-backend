"""Leak scan service — DB-backed job lifecycle + background execution.

``create_scan`` records a ``pending`` job and returns immediately; the API
schedules :func:`run_scan` as a background task. ``run_scan`` loads the
certificate's text + simhash, fans the corpora out one at a time (so each can be
cache-checked and streamed), persists per-corpus results, and moves the job
``pending → running → complete``.

Two invariants layered on top of the corpus orchestrator:

* **7-day cache** (spec §Cache) — a fresh ``(content_hash, corpus, snapshot)``
  result short-circuits the corpus query.
* **Live SSE progress** (spec invariant #6) — ``run_scan`` publishes one event
  per corpus as it completes to an in-process pub/sub channel keyed by
  ``scan_id``; the ``/stream`` endpoint subscribes to it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from uuid import UUID

from inkprint.core.db import session_scope
from inkprint.leak import scanner
from inkprint.leak.score import score as score_hits
from inkprint.repositories import certificate_repo, leak_repo

logger = logging.getLogger(__name__)

DEFAULT_CORPORA = ["common_crawl", "huggingface", "the_stack_v2"]

# Snapshot identifiers used for cache keying. Common Crawl pins a dated crawl;
# the search-API corpora have no stable snapshot, so they key on "latest".
_CORPUS_SNAPSHOTS = {
    "common_crawl": "CC-MAIN-2024-50",
    "huggingface": "latest",
    "the_stack_v2": "latest",
}

# A scan stuck in pending/running longer than this is considered orphaned and
# reaped to a terminal ``error`` state (REL-2).
STALE_SCAN_MAX_AGE = timedelta(minutes=30)

# In-process SSE pub/sub: scan_id -> list of subscriber queues.
_progress_channels: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}


def publish_progress(scan_id: str, event: dict[str, Any]) -> None:
    """Fan a progress event out to every live subscriber of ``scan_id``."""
    for queue in list(_progress_channels.get(scan_id, ())):
        queue.put_nowait(event)


@contextlib.asynccontextmanager
async def progress_subscription(scan_id: str) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
    """Subscribe to a scan's progress channel for the duration of the context."""
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    _progress_channels.setdefault(scan_id, []).append(queue)
    try:
        yield queue
    finally:
        subs = _progress_channels.get(scan_id)
        if subs is not None:
            with contextlib.suppress(ValueError):
                subs.remove(queue)
            if not subs:
                _progress_channels.pop(scan_id, None)


async def create_scan(certificate_id: UUID, corpora: list[str] | None = None) -> dict[str, Any]:
    """Create a new pending leak-scan job and return its record."""
    async with session_scope() as session:
        return await leak_repo.create_job(
            session,
            certificate_id=certificate_id,
            corpora=corpora or DEFAULT_CORPORA,
        )


async def get_scan(scan_id: str) -> dict[str, Any] | None:
    """Look up a scan job by UUID string."""
    async with session_scope() as session:
        return await leak_repo.get_job(session, scan_id)


async def _scan_corpus_cached(
    corpus: str, text: str, simhash: int, content_hash: str
) -> dict[str, Any]:
    """Run (or reuse a cached) single-corpus scan.

    Checks the 7-day cache first; on a miss, runs the corpus and stores the
    fresh result. Returns the per-corpus result dict, tagged ``cached``.
    """
    snapshot = _CORPUS_SNAPSHOTS.get(corpus, "latest")
    key = scanner.cache_key(content_hash, corpus, snapshot)

    async with session_scope() as session:
        cached = await leak_repo.get_cached_result(session, cache_key=key)
    if cached is not None:
        cached["cached"] = True
        return cached

    result = await scanner.scan_one(corpus, text, simhash)
    result.setdefault("cached", False)
    # Only cache terminal, successful corpus results — never a timeout/error,
    # so a transient failure doesn't poison the cache for 7 days.
    if result.get("status") not in ("timeout", "error"):
        result_snapshot = str(result.get("snapshot", snapshot))
        async with session_scope() as session:
            await leak_repo.put_cached_result(
                session,
                cache_key=key,
                content_hash=content_hash,
                corpus=corpus,
                snapshot=result_snapshot,
                result=result,
            )
    return result


async def run_scan(scan_id: UUID, certificate_id: UUID, corpora: list[str]) -> None:
    """Execute a scan and persist results. Intended as a background task.

    Resolves the certificate text + simhash, marks the job running, scans each
    corpus (cache-first, streaming a progress event per corpus), then persists
    per-corpus rows and completes the job. A missing certificate or unexpected
    failure leaves the job in an ``error`` state (and publishes an error event)
    rather than stuck ``pending``/``running``.
    """
    sid = str(scan_id)
    async with session_scope() as session:
        cert = await certificate_repo.get(session, str(certificate_id))

    if cert is None:
        async with session_scope() as session:
            await leak_repo.set_status(session, scan_id, "error")
        publish_progress(sid, {"type": "error", "scan_id": sid, "status": "error"})
        return

    async with session_scope() as session:
        await leak_repo.set_status(session, scan_id, "running")
    publish_progress(sid, {"type": "status", "scan_id": sid, "status": "running"})

    try:
        scanner.validate_corpora(corpora)
        corpus_results: list[dict[str, Any]] = []
        all_hits: list[dict[str, Any]] = []
        for corpus in corpora:
            result = await _scan_corpus_cached(
                corpus, cert["text"], cert["simhash"], cert["content_hash"]
            )
            corpus_results.append(result)
            all_hits.extend(result.get("hits", []))
            publish_progress(sid, {"type": "corpus_complete", **result})
    except Exception:
        logger.exception("Leak scan %s failed", scan_id)
        async with session_scope() as session:
            await leak_repo.set_status(session, scan_id, "error")
        publish_progress(sid, {"type": "error", "scan_id": sid, "status": "error"})
        return

    result_score = score_hits(all_hits)
    async with session_scope() as session:
        await leak_repo.save_results(
            session,
            scan_id=scan_id,
            certificate_id=certificate_id,
            corpus_results=corpus_results,
            score=result_score,
        )
    publish_progress(
        sid,
        {
            "type": "complete",
            "scan_id": sid,
            "status": "complete",
            "hit_count": result_score.hit_count,
            "confidence": result_score.confidence,
        },
    )


async def reap_stale_scans(max_age: timedelta = STALE_SCAN_MAX_AGE) -> int:
    """Move orphaned pending/running scans older than ``max_age`` to ``error``.

    Called on startup so a worker suspension/redeploy can never leave a client
    polling a job that will never reach a terminal state (REL-2).
    """
    async with session_scope() as session:
        return await leak_repo.reap_stale_jobs(session, max_age=max_age)

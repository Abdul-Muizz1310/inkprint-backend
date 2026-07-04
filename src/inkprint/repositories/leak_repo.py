"""Repository for leak-scan jobs and their per-corpus results."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from inkprint.leak.score import ScoreResult
from inkprint.models.leak import LeakScanCache, LeakScanJob, LeakScanResult

# Spec invariant #3: results are cached for 7 days.
CACHE_TTL = timedelta(days=7)


def _job_to_record(job: LeakScanJob) -> dict[str, Any]:
    """Map a job row to the API record dict."""
    return {
        "scan_id": str(job.id),
        "certificate_id": str(job.certificate_id),
        "corpora": job.corpora,
        "status": job.status,
        "hit_count": job.hit_count,
        "confidence": float(job.confidence) if job.confidence is not None else None,
        "results": job.results,
    }


async def create_job(
    session: AsyncSession,
    *,
    certificate_id: UUID,
    corpora: list[str],
) -> dict[str, Any]:
    """Create a pending leak-scan job and return its record."""
    job = LeakScanJob(
        id=uuid4(),
        certificate_id=certificate_id,
        corpora=corpora,
        status="pending",
        hit_count=0,
        confidence=None,
        results=[],
    )
    session.add(job)
    await session.flush()
    return _job_to_record(job)


async def get_job(session: AsyncSession, scan_id: str) -> dict[str, Any] | None:
    """Fetch a scan job by UUID string, or None."""
    job = await session.get(LeakScanJob, UUID(scan_id))
    return _job_to_record(job) if job is not None else None


async def set_status(session: AsyncSession, scan_id: UUID, status: str) -> None:
    """Update a job's status (e.g. pending → running)."""
    job = await session.get(LeakScanJob, scan_id)
    if job is not None:
        job.status = status
        await session.flush()


async def save_results(
    session: AsyncSession,
    *,
    scan_id: UUID,
    certificate_id: UUID,
    corpus_results: list[dict[str, Any]],
    score: ScoreResult,
) -> None:
    """Persist per-corpus rows and mark the job complete.

    Writes one ``leak_scans`` row per corpus and updates the job with the
    aggregate hit count, confidence, and a result summary for polling.
    """
    now = datetime.now(UTC)
    summaries: list[dict[str, Any]] = []
    for r in corpus_results:
        session.add(
            LeakScanResult(
                id=uuid4(),
                scan_id=scan_id,
                certificate_id=certificate_id,
                corpus=r["corpus"],
                snapshot=r.get("snapshot"),
                hit_count=r.get("hit_count", 0),
                confidence=score.confidence,
                hits=r.get("hits", []),
                scanned_at=now,
            )
        )
        summaries.append(
            {
                "corpus": r["corpus"],
                "hit_count": r.get("hit_count", 0),
                "status": r.get("status", "ok"),
                "snapshot": r.get("snapshot"),
            }
        )

    job = await session.get(LeakScanJob, scan_id)
    if job is not None:
        job.status = "complete"
        job.hit_count = score.hit_count
        job.confidence = score.confidence
        job.results = summaries
        job.completed_at = now
    await session.flush()


async def get_cached_result(
    session: AsyncSession,
    *,
    cache_key: str,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Return a fresh (< 7-day) cached corpus result, or None."""
    row = await session.get(LeakScanCache, cache_key)
    if row is None:
        return None
    created = row.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    if (now or datetime.now(UTC)) - created > CACHE_TTL:
        return None
    return dict(row.result)


async def put_cached_result(
    session: AsyncSession,
    *,
    cache_key: str,
    content_hash: str,
    corpus: str,
    snapshot: str,
    result: dict[str, Any],
) -> None:
    """Insert or refresh a cached corpus result (upsert by cache_key)."""
    now = datetime.now(UTC)
    existing = await session.get(LeakScanCache, cache_key)
    if existing is not None:
        existing.result = result
        existing.snapshot = snapshot
        existing.content_hash = content_hash
        existing.corpus = corpus
        existing.created_at = now
    else:
        session.add(
            LeakScanCache(
                cache_key=cache_key,
                content_hash=content_hash,
                corpus=corpus,
                snapshot=snapshot,
                result=result,
                created_at=now,
            )
        )
    await session.flush()


async def reap_stale_jobs(
    session: AsyncSession,
    *,
    max_age: timedelta,
    now: datetime | None = None,
) -> int:
    """Transition orphaned ``pending``/``running`` jobs older than ``max_age`` to ``error``.

    Returns the number of jobs reaped. Guarantees clients always reach a
    terminal state even if the worker was suspended/redeployed mid-scan
    (spec/reliability finding REL-2).
    """
    cutoff = (now or datetime.now(UTC)) - max_age
    stale = (
        await session.scalars(
            select(LeakScanJob).where(
                LeakScanJob.status.in_(("pending", "running")),
                LeakScanJob.created_at < cutoff,
            )
        )
    ).all()
    for job in stale:
        job.status = "error"
        job.completed_at = now or datetime.now(UTC)
    await session.flush()
    return len(stale)

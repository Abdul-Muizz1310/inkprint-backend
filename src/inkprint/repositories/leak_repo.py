"""Repository for leak-scan jobs and their per-corpus results."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from inkprint.leak.score import ScoreResult
from inkprint.models.leak import LeakScanJob, LeakScanResult


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

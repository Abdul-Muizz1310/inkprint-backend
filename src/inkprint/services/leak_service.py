"""Leak scan service — DB-backed job lifecycle + background execution.

``create_scan`` records a ``pending`` job and returns immediately; the API
schedules :func:`run_scan` as a background task. ``run_scan`` loads the
certificate's text + simhash from the repository, runs the corpus orchestrator,
and persists per-corpus results, moving the job ``pending → running →
complete``.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from inkprint.core.db import session_scope
from inkprint.leak import scanner
from inkprint.repositories import certificate_repo, leak_repo

logger = logging.getLogger(__name__)

DEFAULT_CORPORA = ["common_crawl", "huggingface", "the_stack_v2"]


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


async def run_scan(scan_id: UUID, certificate_id: UUID, corpora: list[str]) -> None:
    """Execute a scan and persist results. Intended as a background task.

    Resolves the certificate text + simhash, marks the job running, runs the
    corpus orchestrator (which degrades gracefully when corpora are
    unreachable), then persists per-corpus rows and completes the job. A
    missing certificate or unexpected failure leaves the job in an ``error``
    state rather than stuck ``pending``.
    """
    async with session_scope() as session:
        cert = await certificate_repo.get(session, str(certificate_id))

    if cert is None:
        async with session_scope() as session:
            await leak_repo.set_status(session, scan_id, "error")
        return

    async with session_scope() as session:
        await leak_repo.set_status(session, scan_id, "running")

    try:
        result = await scanner.scan(cert["text"], cert["simhash"], corpora)
    except Exception:
        logger.exception("Leak scan %s failed", scan_id)
        async with session_scope() as session:
            await leak_repo.set_status(session, scan_id, "error")
        return

    # scanner.scan always sets an aggregate score (score([]) for zero hits).
    assert result.score is not None
    async with session_scope() as session:
        await leak_repo.save_results(
            session,
            scan_id=scan_id,
            certificate_id=certificate_id,
            corpus_results=result.corpus_results,
            score=result.score,
        )

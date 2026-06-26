"""Tests for the DB-backed leak service + background scan (spec 04-leak-scanner.md).

These prove the formerly-permanent "pending" stub now runs: create_scan records
a pending job, and run_scan (the background task) resolves the certificate,
executes the corpus orchestrator, and persists results — moving the job to
'complete'. Corpus clients are mocked, so no network is touched.

Test cases:
- TC-LS-01  create_scan persists a pending job with the requested corpora
- TC-LS-02  run_scan completes the job and persists per-corpus result rows
- TC-LS-03  run_scan on a missing certificate marks the job 'error'
- TC-LS-04  run_scan marks the job 'error' if the orchestrator raises
- TC-LS-05  get_scan returns None for an unknown id
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from sqlalchemy import select

from inkprint.core.db import session_scope
from inkprint.models.leak import LeakScanResult
from inkprint.repositories import certificate_repo
from inkprint.services import leak_service


async def _seed_cert(text: str = "secret manuscript text") -> UUID:
    cert_id = uuid4()
    record = {
        "id": str(cert_id),
        "author": "a@b.com",
        "text": text,
        "content_hash": f"hash-{cert_id}",
        "simhash": 99,
        "embedding": [0.0] * 768,
        "content_len": len(text),
        "language": "en",
        "issued_at": datetime.now(UTC),
        "signature": "c2ln",
        "manifest": {"version": "2.2"},
        "storage_key": None,
        "metadata": None,
    }
    async with session_scope() as s:
        await certificate_repo.add(s, record)
    return cert_id


class TestLeakService:
    async def test_tc_ls_01_create_scan_pending(self):
        cert_id = await _seed_cert()
        job = await leak_service.create_scan(cert_id, corpora=["common_crawl"])
        assert job["status"] == "pending"
        assert job["corpora"] == ["common_crawl"]
        assert job["hit_count"] == 0

    async def test_tc_ls_02_run_scan_completes_and_persists(self):
        cert_id = await _seed_cert()
        job = await leak_service.create_scan(cert_id, corpora=["common_crawl", "huggingface"])
        scan_id = UUID(job["scan_id"])

        async def fake_cc(text, simhash):
            return {
                "corpus": "common_crawl",
                "hits": [{"url": "u1", "hamming": 2}, {"url": "u2", "hamming": 3}],
                "hit_count": 2,
                "snapshot": "CC-MAIN-2024-50",
            }

        async def fake_hf(text):
            return {"corpus": "huggingface", "hits": [], "hit_count": 0}

        with (
            patch("inkprint.leak.scanner.scan_common_crawl", fake_cc),
            patch("inkprint.leak.scanner.scan_huggingface", fake_hf),
        ):
            await leak_service.run_scan(scan_id, cert_id, ["common_crawl", "huggingface"])

        done = await leak_service.get_scan(str(scan_id))
        assert done is not None
        assert done["status"] == "complete"
        assert done["hit_count"] == 2
        assert done["confidence"] is not None and done["confidence"] > 0.0
        assert len(done["results"]) == 2

        # Durable per-corpus rows landed in leak_scans, linked to the job.
        async with session_scope() as s:
            rows = (
                await s.scalars(select(LeakScanResult).where(LeakScanResult.scan_id == scan_id))
            ).all()
        assert {r.corpus for r in rows} == {"common_crawl", "huggingface"}

    async def test_tc_ls_03_missing_certificate_marks_error(self):
        missing_cert = uuid4()
        job = await leak_service.create_scan(missing_cert, corpora=["common_crawl"])
        scan_id = UUID(job["scan_id"])

        await leak_service.run_scan(scan_id, missing_cert, ["common_crawl"])

        done = await leak_service.get_scan(str(scan_id))
        assert done is not None
        assert done["status"] == "error"

    async def test_tc_ls_04_orchestrator_failure_marks_error(self):
        cert_id = await _seed_cert()
        job = await leak_service.create_scan(cert_id, corpora=["common_crawl"])
        scan_id = UUID(job["scan_id"])

        with patch(
            "inkprint.services.leak_service.scanner.scan",
            new=AsyncMock(side_effect=RuntimeError("orchestrator boom")),
        ):
            await leak_service.run_scan(scan_id, cert_id, ["common_crawl"])

        done = await leak_service.get_scan(str(scan_id))
        assert done is not None
        assert done["status"] == "error"

    async def test_tc_ls_05_get_unknown_scan_returns_none(self):
        assert await leak_service.get_scan(str(uuid4())) is None

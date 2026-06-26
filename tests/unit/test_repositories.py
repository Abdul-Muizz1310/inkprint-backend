"""Repository-layer persistence tests on SQLite (spec 05-api.md persistence).

These prove the ORM + repositories genuinely persist and query — round-trip
durability across sessions, exact-hash lookup, semantic cosine ranking, and
leak-scan job/result persistence. They run with no Docker and no network.

Test cases:
- TC-R-01  certificate round-trips across sessions with text/embedding/metadata
- TC-R-02  get() returns None for an unknown id
- TC-R-03  add_many is atomic within a session and all rows are retrievable
- TC-R-04  search_exact matches on content hash, ignores non-matches
- TC-R-05  search_semantic ranks by cosine similarity, most-similar first
- TC-R-06  search_semantic drops zero-similarity rows (zero-vector fallback)
- TC-R-07  search_semantic honors the limit
- TC-R-08  derivative links persist and list by parent
- TC-R-09  leak job is created 'pending' with no results
- TC-R-10  save_results marks the job 'complete' with confidence + per-corpus rows
- TC-R-11  get_job returns None for an unknown id
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from inkprint.core.db import session_scope
from inkprint.leak.score import score
from inkprint.models.leak import LeakScanResult
from inkprint.repositories import certificate_repo, leak_repo


def _make_record(
    text: str, *, author: str = "a@b.com", embedding: list[float] | None = None
) -> dict:
    cert_id = uuid4()
    return {
        "id": str(cert_id),
        "author": author,
        "text": text,
        "content_hash": f"hash-{cert_id}",
        "simhash": 12345,
        "embedding": embedding if embedding is not None else [0.0] * 768,
        "content_len": len(text),
        "language": "en",
        "issued_at": datetime.now(UTC),
        "signature": "c2lnbmF0dXJl",
        "manifest": {"version": "2.2", "author": author},
        "storage_key": f"certificates/{cert_id}.json",
        "metadata": {"source": "unit"},
    }


# ── Certificate persistence ──────────────────────────────────────────────────


class TestCertificatePersistence:
    async def test_tc_r_01_round_trip_across_sessions(self, db_tables: None) -> None:
        record = _make_record("hello world", embedding=[0.5] + [0.0] * 767)
        async with session_scope() as s:
            await certificate_repo.add(s, record)

        # Re-read in a fresh session to prove durability, not in-session cache.
        async with session_scope() as s:
            got = await certificate_repo.get(s, record["id"])

        assert got is not None
        assert got["text"] == "hello world"
        assert got["author"] == "a@b.com"
        assert got["metadata"] == {"source": "unit"}
        assert got["manifest"]["version"] == "2.2"
        # Embedding survives the JSON round-trip as a list of floats.
        assert got["embedding"][0] == 0.5
        assert len(got["embedding"]) == 768

    async def test_tc_r_02_get_unknown_returns_none(self, db_tables: None) -> None:
        async with session_scope() as s:
            assert await certificate_repo.get(s, str(uuid4())) is None

    async def test_tc_r_03_add_many_atomic(self, db_tables: None) -> None:
        records = [_make_record(f"doc {i}") for i in range(5)]
        async with session_scope() as s:
            await certificate_repo.add_many(s, records)
        async with session_scope() as s:
            assert await certificate_repo.count(s) == 5
            for r in records:
                assert await certificate_repo.exists(s, r["id"]) is True


# ── Search ───────────────────────────────────────────────────────────────────


class TestSearch:
    async def test_tc_r_04_exact_hash_match(self, db_tables: None) -> None:
        record = _make_record("find me")
        async with session_scope() as s:
            await certificate_repo.add(s, record)
        async with session_scope() as s:
            hits = await certificate_repo.search_exact(s, record["content_hash"])
            misses = await certificate_repo.search_exact(s, "no-such-hash")
        assert len(hits) == 1
        assert hits[0]["id"] == record["id"]
        assert hits[0]["score"] == 1.0
        assert misses == []

    async def test_tc_r_05_semantic_ranks_by_cosine(self, db_tables: None) -> None:
        near = _make_record("near", embedding=[1.0, 0.1, 0.0] + [0.0] * 765)
        mid = _make_record("mid", embedding=[0.6, 0.8, 0.0] + [0.0] * 765)
        far = _make_record("far", embedding=[0.0, 0.0, 1.0] + [0.0] * 765)
        async with session_scope() as s:
            await certificate_repo.add_many(s, [far, mid, near])

        query = [1.0, 0.0, 0.0] + [0.0] * 765
        async with session_scope() as s:
            ranked = await certificate_repo.search_semantic(s, query)

        ids = [r["id"] for r in ranked]
        # 'far' is orthogonal to the query → dropped; near ranks above mid.
        assert far["id"] not in ids
        assert ids[0] == near["id"]
        assert ids[1] == mid["id"]
        assert ranked[0]["score"] >= ranked[1]["score"]

    async def test_tc_r_06_semantic_drops_zero_vectors(self, db_tables: None) -> None:
        # Default embedding is the zero vector (no embedding backend).
        async with session_scope() as s:
            await certificate_repo.add_many(s, [_make_record("a"), _make_record("b")])
        async with session_scope() as s:
            ranked = await certificate_repo.search_semantic(s, [0.0] * 768)
        assert ranked == []

    async def test_tc_r_07_semantic_honors_limit(self, db_tables: None) -> None:
        records = [
            _make_record(f"d{i}", embedding=[1.0, float(i) / 10.0, 0.0] + [0.0] * 765)
            for i in range(5)
        ]
        async with session_scope() as s:
            await certificate_repo.add_many(s, records)
        async with session_scope() as s:
            ranked = await certificate_repo.search_semantic(
                s, [1.0, 0.0, 0.0] + [0.0] * 765, limit=2
            )
        assert len(ranked) == 2


# ── Derivative links ─────────────────────────────────────────────────────────


class TestDerivativeLinks:
    async def test_tc_r_08_links_persist_and_list(self, db_tables: None) -> None:
        parent = _make_record("parent")
        child = _make_record("child")
        async with session_scope() as s:
            await certificate_repo.add_many(s, [parent, child])
            from uuid import UUID

            await certificate_repo.add_derivative_link(
                s,
                parent_id=UUID(parent["id"]),
                child_id=UUID(child["id"]),
                hamming=4,
                cosine=0.91,
                verdict="derivative",
            )
        from uuid import UUID

        async with session_scope() as s:
            links = await certificate_repo.list_derivative_links(s, UUID(parent["id"]))
        assert len(links) == 1
        assert links[0]["child_id"] == child["id"]
        assert links[0]["verdict"] == "derivative"
        assert links[0]["hamming"] == 4
        assert abs(links[0]["cosine"] - 0.91) < 1e-6


# ── Leak-scan jobs + results ─────────────────────────────────────────────────


class TestLeakPersistence:
    async def test_tc_r_09_create_job_pending(self, db_tables: None) -> None:
        cert = _make_record("scan me")
        async with session_scope() as s:
            await certificate_repo.add(s, cert)
            from uuid import UUID

            job = await leak_repo.create_job(
                s, certificate_id=UUID(cert["id"]), corpora=["common_crawl"]
            )
        assert job["status"] == "pending"
        assert job["results"] == []
        assert job["hit_count"] == 0
        assert job["confidence"] is None

    async def test_tc_r_10_save_results_completes_job(self, db_tables: None) -> None:
        from uuid import UUID

        cert = _make_record("scan me")
        async with session_scope() as s:
            await certificate_repo.add(s, cert)
            job = await leak_repo.create_job(
                s, certificate_id=UUID(cert["id"]), corpora=["common_crawl", "huggingface"]
            )
        scan_id = UUID(job["scan_id"])
        cert_id = UUID(cert["id"])
        corpus_results = [
            {"corpus": "common_crawl", "hit_count": 2, "hits": [{"url": "x"}, {"url": "y"}]},
            {"corpus": "huggingface", "hit_count": 0, "hits": [], "status": "ok"},
        ]
        aggregate = score([{"url": "x", "hamming": 2}, {"url": "y", "hamming": 4}])

        async with session_scope() as s:
            await leak_repo.set_status(s, scan_id, "running")
            await leak_repo.save_results(
                s,
                scan_id=scan_id,
                certificate_id=cert_id,
                corpus_results=corpus_results,
                score=aggregate,
            )

        async with session_scope() as s:
            done = await leak_repo.get_job(s, str(scan_id))
            rows = (
                await s.scalars(select(LeakScanResult).where(LeakScanResult.scan_id == scan_id))
            ).all()

        assert done is not None
        assert done["status"] == "complete"
        assert done["hit_count"] == aggregate.hit_count
        assert done["confidence"] == float(aggregate.confidence)
        assert len(done["results"]) == 2
        # Two durable per-corpus rows persisted to leak_scans.
        assert len(rows) == 2
        assert {r.corpus for r in rows} == {"common_crawl", "huggingface"}

    async def test_tc_r_11_get_job_unknown_returns_none(self, db_tables: None) -> None:
        async with session_scope() as s:
            assert await leak_repo.get_job(s, str(uuid4())) is None


# Cross-check: stored embedding column is valid JSON (storage contract).
class TestStorageContract:
    async def test_embedding_stored_as_json_text(self, db_tables: None) -> None:
        from inkprint.models.certificate import Certificate

        record = _make_record("json check", embedding=[0.1, 0.2, 0.3] + [0.0] * 765)
        async with session_scope() as s:
            await certificate_repo.add(s, record)
        async with session_scope() as s:
            model = await s.get(Certificate, __import__("uuid").UUID(record["id"]))
            assert model is not None
            decoded = json.loads(model.embedding)
        assert decoded[:3] == [0.1, 0.2, 0.3]

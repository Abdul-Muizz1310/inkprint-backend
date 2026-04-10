"""Leak scan service — wraps the leak scanner for the API layer."""

from __future__ import annotations

from uuid import UUID, uuid4

# In-memory store for scan results.
_scans: dict[str, dict] = {}


def reset_store() -> None:
    """Clear the in-memory store (useful for tests)."""
    _scans.clear()


def create_scan(certificate_id: UUID, corpora: list[str] | None = None) -> dict:
    """Create a new leak scan record and return it."""
    scan_id = uuid4()
    record = {
        "scan_id": str(scan_id),
        "certificate_id": str(certificate_id),
        "corpora": corpora or ["common_crawl", "huggingface", "the_stack_v2"],
        "status": "pending",
        "results": [],
    }
    _scans[str(scan_id)] = record
    return record


def get_scan(scan_id: str) -> dict | None:
    """Look up a scan by UUID string."""
    return _scans.get(scan_id)

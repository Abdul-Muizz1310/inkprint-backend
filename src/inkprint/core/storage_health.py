"""The outcome of the last R2 operation, and the storage status it implies (spec 08).

In-process state only: ``/health`` reads it without building a client or making a
network call. ``core.r2`` records every operation's outcome here.
"""

from __future__ import annotations

from typing import Literal

StorageStatus = Literal["ok", "degraded"]

# ``None`` until the first R2 operation of this process completes. A single
# attribute assignment is atomic under the GIL, so worker-thread uploads
# (``asyncio.to_thread``) can record without a lock.
_last_ok: bool | None = None


def storage_status(*, configured: bool, last_ok: bool | None) -> StorageStatus:
    """``degraded`` when R2 is unconfigured or its last operation failed, else ``ok``."""
    if not configured or last_ok is False:
        return "degraded"
    return "ok"


def record_success() -> None:
    global _last_ok
    _last_ok = True


def record_failure() -> None:
    global _last_ok
    _last_ok = False


def last_ok() -> bool | None:
    """The last recorded outcome: ``True`` ok, ``False`` failed, ``None`` none yet."""
    return _last_ok


def reset() -> None:
    """Forget the recorded outcome (test seam)."""
    global _last_ok
    _last_ok = None

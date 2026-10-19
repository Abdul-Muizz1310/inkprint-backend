"""Cloudflare R2 (S3-compatible) client for certificate blob storage.

Every request this module makes records its outcome in ``core.storage_health``
and logs a failure at WARNING (spec 08), so a dead token shows on ``/health`` as
``storage: "degraded"`` instead of disappearing into a DEBUG line.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from inkprint.core import storage_health
from inkprint.core.config import get_settings
from inkprint.core.storage_health import StorageStatus

logger = logging.getLogger(__name__)

# Short timeouts and a single attempt: archival is best-effort, and the startup
# probe runs in a worker thread that a hung endpoint must not pin.
_CLIENT_CONFIG = Config(connect_timeout=3, read_timeout=5, retries={"total_max_attempts": 1})
_KEY_PREFIX = "inkprint/"


def is_configured() -> bool:
    """True when the endpoint and both halves of the credential are set."""
    settings = get_settings()
    return bool(
        settings.r2_endpoint and settings.r2_access_key_id and settings.r2_secret_access_key
    )


def storage_status() -> StorageStatus:
    """``/health``'s storage field — in-process state only, never a network call."""
    return storage_health.storage_status(
        configured=is_configured(), last_ok=storage_health.last_ok()
    )


def _get_client() -> Any:
    """Get a boto3 S3 client configured for R2, or ``None`` when R2 is unconfigured."""
    if not is_configured():
        return None
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
        config=_CLIENT_CONFIG,
    )


def _error_label(exc: Exception) -> str:
    """The exception class, plus the S3 error code for a ``ClientError``. Never the message."""
    name = type(exc).__name__
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code")
        if code:
            return f"{name} ({code})"
    return name


def _recorded[T](operation: str, target: str, call: Callable[[], T]) -> T:
    """Run one R2 request, record its outcome, and WARN (then re-raise) on failure."""
    try:
        result = call()
    except Exception as exc:
        storage_health.record_failure()
        logger.warning("R2 %s failed for %s: %s", operation, target, _error_label(exc))
        raise
    storage_health.record_success()
    return result


def upload_text(key: str, text: str) -> str | None:
    """Upload text to R2. Returns the storage key, or None if R2 is not configured."""
    client = _get_client()
    if client is None:
        return None
    settings = get_settings()
    full_key = f"{_KEY_PREFIX}{key}"
    _recorded(
        "put_object",
        full_key,
        lambda: client.put_object(
            Bucket=settings.r2_bucket,
            Key=full_key,
            Body=text.encode("utf-8"),
            ContentType="text/plain; charset=utf-8",
        ),
    )
    return full_key


async def archive_text(key: str, text: str) -> str | None:
    """Best-effort archival of ``text`` under ``key``.

    Returns the R2 storage key on success, or ``None`` when R2 is unconfigured
    (the common demo case) or the upload fails — archival is never fatal to
    certificate creation. The synchronous boto3 call is offloaded to a thread so
    it never blocks the event loop. A failure has already been logged at WARNING
    and recorded for ``/health`` by ``upload_text``.

    Single home for this behaviour on purpose: the single-certificate and batch
    paths must agree on what ``storage_key`` means, and they previously did not.
    """
    try:
        return await asyncio.to_thread(upload_text, key, text)
    except Exception:
        return None


def download_text(key: str) -> str:
    """Download text from R2."""
    client = _get_client()
    if client is None:
        raise OSError("R2 not configured")
    settings = get_settings()
    resp = _recorded(
        "get_object", key, lambda: client.get_object(Bucket=settings.r2_bucket, Key=key)
    )
    body: str = resp["Body"].read().decode("utf-8")
    return body


def probe_storage() -> None:
    """One cheap read at startup so ``/health`` is truthful before the first upload.

    Render's free instance sleeps when idle, so without this the recorded outcome
    would reset on every wake and report ``ok`` until a certificate was issued.
    Lists one key under the prefix (object-read permission, which an
    object-scoped token has). Never raises: the outcome is the result.
    """
    client = _get_client()
    if client is None:
        logger.warning("R2 is not configured; certificate archival is disabled")
        return
    bucket = get_settings().r2_bucket
    try:
        _recorded(
            "list_objects_v2",
            bucket,
            lambda: client.list_objects_v2(Bucket=bucket, Prefix=_KEY_PREFIX, MaxKeys=1),
        )
    except Exception:
        return


def generate_presigned_url(key: str, expires_in: int = 3600) -> str:
    """Generate a presigned URL for downloading from R2 (signed locally; no request)."""
    client = _get_client()
    if client is None:
        raise OSError("R2 not configured")
    settings = get_settings()
    url: str = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.r2_bucket, "Key": key},
        ExpiresIn=expires_in,
    )
    return url

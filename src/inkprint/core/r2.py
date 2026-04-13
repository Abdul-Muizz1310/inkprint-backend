"""Cloudflare R2 (S3-compatible) client for certificate blob storage."""

from __future__ import annotations

from typing import Any

import boto3

from inkprint.core.config import get_settings


def _get_client() -> Any:
    """Get a boto3 S3 client configured for R2."""
    settings = get_settings()
    if (
        not settings.r2_endpoint
        or not settings.r2_access_key_id
        or not settings.r2_secret_access_key
    ):
        return None
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
    )


def upload_text(key: str, text: str) -> str | None:
    """Upload text to R2. Returns the storage key, or None if R2 is not configured."""
    client = _get_client()
    if client is None:
        return None
    settings = get_settings()
    full_key = f"inkprint/{key}"
    client.put_object(
        Bucket=settings.r2_bucket,
        Key=full_key,
        Body=text.encode("utf-8"),
        ContentType="text/plain; charset=utf-8",
    )
    return full_key


def download_text(key: str) -> str:
    """Download text from R2."""
    client = _get_client()
    if client is None:
        raise OSError("R2 not configured")
    settings = get_settings()
    resp = client.get_object(Bucket=settings.r2_bucket, Key=key)
    body: str = resp["Body"].read().decode("utf-8")
    return body


def generate_presigned_url(key: str, expires_in: int = 3600) -> str:
    """Generate a presigned URL for downloading from R2."""
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

"""The public-route policy — spec 09 §4 (PT-13 at the policy level, PT-26)."""

from __future__ import annotations

import pytest

from inkprint.platform.public_routes import is_public

_ID = "6f1c2b8e-1d2a-4c5b-9e8f-0a1b2c3d4e5f"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/health"),
        ("HEAD", "/health"),
        ("GET", "/version"),
        ("GET", "/docs"),
        ("GET", "/docs/oauth2-redirect"),
        ("GET", "/redoc"),
        ("GET", "/openapi.json"),
        ("GET", "/metrics"),
        ("GET", f"/certificates/{_ID}"),
        ("GET", f"/certificates/{_ID}/manifest"),
        ("GET", f"/certificates/{_ID}/qr"),
        ("GET", f"/certificates/{_ID}/download"),
        ("POST", "/verify"),
        ("POST", "/verify/batch"),
        ("GET", "/public-key.pem"),
    ],
)
def test_public(method: str, path: str) -> None:
    assert is_public(method, path) is True


@pytest.mark.parametrize(
    ("method", "path"),
    [
        # The writes and quota spenders (review focus 5).
        ("POST", "/certificates"),
        ("POST", "/certificates/batch"),
        ("POST", "/diff"),
        ("GET", "/search"),
        ("POST", "/leak-scan"),
        ("GET", f"/leak-scan/{_ID}"),
        ("GET", f"/leak-scan/{_ID}/stream"),
        ("POST", "/dossiers/envelope"),
        # Near misses (PT-26).
        ("POST", f"/certificates/{_ID}"),
        ("DELETE", f"/certificates/{_ID}"),
        ("POST", f"/certificates/{_ID}/qr"),
        ("GET", f"/certificates/{_ID}/qr/x"),
        ("GET", f"/certificates/{_ID}/unknown"),
        ("GET", "/certificates/"),
        ("GET", "/certificates"),
        ("GET", f"/certificates/{_ID}/"),
        ("GET", "/verify"),
        ("PUT", "/verify"),
        ("POST", "/verify/batch/x"),
        ("POST", "/public-key.pem"),
        ("GET", "/healthz"),
        ("GET", "/health/x"),
        ("GET", "/docsx"),
        ("GET", "/openapi.json/x"),
        ("GET", "/"),
        ("GET", ""),
    ],
)
def test_protected(method: str, path: str) -> None:
    assert is_public(method, path) is False


def test_method_is_case_insensitive() -> None:
    assert is_public("post", "/verify") is True
    assert is_public("get", f"/certificates/{_ID}") is True

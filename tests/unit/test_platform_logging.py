"""Tests for platform/logging.py."""

from __future__ import annotations

import logging

from inkprint.platform.logging import configure_logging


def test_configure_logging_dev() -> None:
    configure_logging()
    root = logging.getLogger()
    assert root.level == logging.INFO


def test_configure_logging_prod(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ENVIRONMENT", "production")
    configure_logging()
    root = logging.getLogger()
    assert root.level == logging.INFO

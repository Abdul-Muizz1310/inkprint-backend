"""Declarative base for all inkprint ORM models."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base. All mapped models inherit from this."""

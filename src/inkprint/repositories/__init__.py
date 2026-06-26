"""Persistence layer. Repositories own all DB access; services call them.

Each function takes an :class:`~sqlalchemy.ext.asyncio.AsyncSession` and works
against the ORM models in :mod:`inkprint.models`. Records cross the
service/repository boundary as plain dicts to keep services ORM-agnostic.
"""

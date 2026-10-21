"""Which routes never require a platform token — spec 09 §4.

Default deny: a route is public only when it is listed here, matched exactly by
method and path. Everything that issues, spends quota or reads private data is
absent on purpose (``POST /certificates`` above all: review focus 5).
"""

from __future__ import annotations

import re
from typing import Final

# Infrastructure paths: public for any method (FastAPI answers 405 to a wrong one).
_INFRA_EXACT: Final = frozenset({"/health", "/version", "/openapi.json", "/metrics", "/redoc"})
_DOCS: Final = re.compile(r"^/docs(?:/[^/]+)*$")

# One non-empty path segment: a certificate id as the router receives it.
_SEGMENT: Final = r"[^/]+"

# The verification surfaces: anyone can check a certificate without asking us.
_VERIFICATION: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("GET", re.compile(rf"^/certificates/{_SEGMENT}$")),
    ("GET", re.compile(rf"^/certificates/{_SEGMENT}/(?:manifest|qr|download)$")),
    ("POST", re.compile(r"^/verify$")),
    ("POST", re.compile(r"^/verify/batch$")),
    ("GET", re.compile(r"^/public-key\.pem$")),
)


def is_public(method: str, path: str) -> bool:
    """True when ``method path`` never needs a token."""
    if path in _INFRA_EXACT or _DOCS.match(path):
        return True
    verb = method.upper()
    return any(verb == allowed and pattern.match(path) for allowed, pattern in _VERIFICATION)

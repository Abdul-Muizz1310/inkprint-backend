"""Platform token verification — the pure core of contract v2 (spec 09 §2).

No I/O and no clock: the caller passes the trusted keys and ``now``. The result
is a discriminated union, so the shell must handle a rejection's reason.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Literal

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jwt.types import Options

SERVICE_ID: Final = "inkprint"
BASTION_ISSUER: Final = "bastion"
FRONTEND_ISSUER: Final = "inkprint-frontend"
FRONTEND_ROLE: Final = "frontend"
LEEWAY_S: Final = 10
MAX_LIFETIME_S: Final = 300

Issuer = Literal["bastion", "inkprint-frontend"]

# Signature only: every claim rule is ours (spec 09 §2), not PyJWT's defaults —
# PyJWT accepts a list ``aud`` that contains the audience, which the contract
# forbids, and would otherwise check ``sub``/``jti`` types on its own terms.
_SIGNATURE_ONLY: Final[Options] = {
    "verify_signature": True,
    "verify_exp": False,
    "verify_nbf": False,
    "verify_iat": False,
    "verify_aud": False,
    "verify_iss": False,
    "verify_sub": False,
    "verify_jti": False,
    "require": [],
}


@dataclass(frozen=True)
class TrustedKey:
    """A verification key and the one issuer it may vouch for."""

    issuer: Issuer
    key: Ed25519PublicKey


@dataclass(frozen=True)
class Principal:
    """Who an authenticated request comes from."""

    iss: str
    sub: str
    role: str | None


class RejectReason(StrEnum):
    MALFORMED = "malformed"
    ALGORITHM = "algorithm"
    SIGNATURE = "signature"
    ISSUER = "issuer"
    ROLE = "role"
    AUDIENCE = "audience"
    CLAIMS = "claims"
    EXPIRED = "expired"
    NOT_YET_VALID = "not_yet_valid"
    LIFETIME = "lifetime"


@dataclass(frozen=True)
class Accepted:
    principal: Principal


@dataclass(frozen=True)
class Rejected:
    reason: RejectReason


Verification = Accepted | Rejected


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _issuer_policy(trusted: TrustedKey, claims: dict[str, Any]) -> RejectReason | None:
    """The key decides which ``iss`` (and, for the frontend, which role) it vouches for."""
    if claims.get("iss") != trusted.issuer:
        return RejectReason.ISSUER
    if trusted.issuer == FRONTEND_ISSUER and claims.get("role") != FRONTEND_ROLE:
        return RejectReason.ROLE
    return None


def _claim_rules(claims: dict[str, Any], now: int) -> RejectReason | None:
    """Audience, times and subject — the checks after signature and issuer."""
    aud = claims.get("aud")
    if not isinstance(aud, str) or aud != SERVICE_ID:
        return RejectReason.AUDIENCE
    exp, iat = claims.get("exp"), claims.get("iat")
    if not _is_int(exp) or not _is_int(iat):
        return RejectReason.CLAIMS
    assert isinstance(exp, int) and isinstance(iat, int)  # narrowed by _is_int
    if exp + LEEWAY_S <= now:
        return RejectReason.EXPIRED
    if iat - LEEWAY_S > now:
        return RejectReason.NOT_YET_VALID
    if not 0 < exp - iat <= MAX_LIFETIME_S:
        return RejectReason.LIFETIME
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        return RejectReason.CLAIMS
    return None


def _signed_claims(token: str, trusted: TrustedKey) -> dict[str, Any] | None:
    """The payload when ``trusted`` verifies the signature, else ``None``.

    Raises ``jwt.DecodeError`` when the token verifies but is not a JWT object.
    """
    try:
        claims: dict[str, Any] = jwt.decode(
            token, trusted.key, algorithms=["EdDSA"], options=_SIGNATURE_ONLY
        )
    except jwt.InvalidSignatureError:
        return None
    return claims


def verify_platform_token(token: str, keys: Sequence[TrustedKey], *, now: int) -> Verification:
    """Authenticate ``token`` against ``keys`` at ``now`` (Unix seconds)."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        return Rejected(RejectReason.MALFORMED)
    if header.get("alg") != "EdDSA":
        return Rejected(RejectReason.ALGORITHM)

    first_policy_failure: RejectReason | None = None
    for trusted in keys:
        try:
            claims = _signed_claims(token, trusted)
        except jwt.PyJWTError:
            return Rejected(RejectReason.MALFORMED)
        if claims is None:
            continue
        policy_failure = _issuer_policy(trusted, claims)
        if policy_failure is not None:
            first_policy_failure = first_policy_failure or policy_failure
            continue
        rule_failure = _claim_rules(claims, now)
        if rule_failure is not None:
            return Rejected(rule_failure)
        role = claims.get("role")
        return Accepted(
            Principal(
                iss=trusted.issuer,
                sub=claims["sub"],
                role=role if isinstance(role, str) else None,
            )
        )
    return Rejected(first_policy_failure or RejectReason.SIGNATURE)

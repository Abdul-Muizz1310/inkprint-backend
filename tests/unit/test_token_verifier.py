"""Pure token verification — spec 09 §2 (PT-1..9, PT-15, PT-21..23)."""

from __future__ import annotations

import base64
import time
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization

from inkprint.platform.token_verifier import (
    SERVICE_ID,
    Accepted,
    Principal,
    Rejected,
    RejectReason,
    TrustedKey,
    verify_platform_token,
)
from tests.platform_keys import (
    DROP,
    KeyPair,
    bastion_claims,
    frontend_claims,
    hs256_with_public_key,
    keypair,
    sign,
    unsigned,
    with_payload,
)

BASTION = keypair()
FRONTEND = keypair()
OTHER = keypair()
NOW = int(time.time())


def _public(pair: KeyPair) -> Any:
    return serialization.load_der_public_key(base64.b64decode(pair.public_b64))


KEYS = (
    TrustedKey(issuer="bastion", key=_public(BASTION)),
    TrustedKey(issuer="inkprint-frontend", key=_public(FRONTEND)),
)


def _verify(token: str, *, now: int = NOW, keys: tuple[TrustedKey, ...] = KEYS) -> Any:
    return verify_platform_token(token, keys, now=now)


def _rejected(token: str, reason: RejectReason, **kwargs: Any) -> None:
    assert _verify(token, **kwargs) == Rejected(reason)


def test_service_id_is_a_constant() -> None:
    assert SERVICE_ID == "inkprint"


# ── Pass ─────────────────────────────────────────────────────────────────────


def test_pt1_bastion_token_for_inkprint_is_accepted() -> None:
    claims = bastion_claims(iat=NOW, exp=NOW + 60)
    result = _verify(sign(BASTION, claims))
    assert result == Accepted(Principal(iss="bastion", sub="v_abcdef1234", role="editor"))


def test_pt15_frontend_token_is_accepted() -> None:
    result = _verify(sign(FRONTEND, frontend_claims(iat=NOW, exp=NOW + 60)))
    assert result == Accepted(
        Principal(iss="inkprint-frontend", sub="inkprint-frontend", role="frontend")
    )


def test_bastion_token_without_role_is_accepted() -> None:
    """inkprint authenticates only; a bastion role is informational."""
    result = _verify(sign(BASTION, bastion_claims(iat=NOW, exp=NOW + 60, role=DROP)))
    assert result == Accepted(Principal(iss="bastion", sub="v_abcdef1234", role=None))


@pytest.mark.parametrize("skew", [-5, 0, 5, 9])
def test_pt6_expiry_within_leeway_is_accepted(skew: int) -> None:
    # exp is `skew` seconds in the past (negative skew = still in the future).
    exp = NOW - skew
    token = sign(BASTION, bastion_claims(iat=exp - 60, exp=exp))
    assert isinstance(_verify(token), Accepted)


@pytest.mark.parametrize("ahead", [1, 5, 10])
def test_pt7_iat_within_leeway_is_accepted(ahead: int) -> None:
    token = sign(BASTION, bastion_claims(iat=NOW + ahead, exp=NOW + ahead + 60))
    assert isinstance(_verify(token), Accepted)


def test_lifetime_of_exactly_300_is_accepted() -> None:
    assert isinstance(_verify(sign(BASTION, bastion_claims(iat=NOW, exp=NOW + 300))), Accepted)


def test_same_key_configured_twice_accepts_either_issuer() -> None:
    shared = (
        TrustedKey(issuer="bastion", key=_public(BASTION)),
        TrustedKey(issuer="inkprint-frontend", key=_public(BASTION)),
    )
    token = sign(BASTION, frontend_claims(iat=NOW, exp=NOW + 60))
    assert isinstance(_verify(token, keys=shared), Accepted)


# ── Failure (negative space) ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "aud", ["paper-trail", "magpie", "inkthread", "slowquery", "feathers-demo"]
)
def test_pt2_another_services_audience_is_rejected(aud: str) -> None:
    _rejected(sign(BASTION, bastion_claims(aud=aud)), RejectReason.AUDIENCE)


@pytest.mark.parametrize("aud", [DROP, ["inkprint"], ["inkprint", "magpie"], "", None, 1])
def test_pt3_missing_or_list_audience_is_rejected(aud: Any) -> None:
    _rejected(sign(BASTION, bastion_claims(aud=aud)), RejectReason.AUDIENCE)


def test_pt4_bastion_issuer_signed_with_frontend_key_is_rejected() -> None:
    _rejected(sign(FRONTEND, bastion_claims()), RejectReason.ISSUER)


def test_pt4_frontend_issuer_signed_with_bastion_key_is_rejected() -> None:
    _rejected(sign(BASTION, frontend_claims()), RejectReason.ISSUER)


@pytest.mark.parametrize("iss", [DROP, "", "magpie-frontend", "paper-trail-frontend"])
def test_wrong_issuer_for_either_key_is_rejected(iss: Any) -> None:
    _rejected(sign(BASTION, bastion_claims(iss=iss)), RejectReason.ISSUER)
    _rejected(sign(FRONTEND, frontend_claims(iss=iss)), RejectReason.ISSUER)


@pytest.mark.parametrize("role", ["viewer", "admin", "editor", "", DROP, None])
def test_pt5_frontend_key_without_frontend_role_is_rejected(role: Any) -> None:
    _rejected(sign(FRONTEND, frontend_claims(role=role)), RejectReason.ROLE)


@pytest.mark.parametrize("ago", [10, 15, 3600])
def test_pt6_expiry_beyond_leeway_is_rejected(ago: int) -> None:
    exp = NOW - ago
    _rejected(sign(BASTION, bastion_claims(iat=exp - 60, exp=exp)), RejectReason.EXPIRED)


@pytest.mark.parametrize("ahead", [11, 15, 3600])
def test_pt7_iat_beyond_leeway_is_rejected(ahead: int) -> None:
    token = sign(BASTION, bastion_claims(iat=NOW + ahead, exp=NOW + ahead + 60))
    _rejected(token, RejectReason.NOT_YET_VALID)


def test_pt8_alg_none_is_rejected() -> None:
    _rejected(unsigned(bastion_claims()), RejectReason.ALGORITHM)


def test_pt8_hs256_keyed_with_the_public_key_is_rejected() -> None:
    _rejected(hs256_with_public_key(BASTION, bastion_claims()), RejectReason.ALGORITHM)


def test_pt9_tampered_payload_is_rejected() -> None:
    token = sign(BASTION, bastion_claims(sub="v_honest0000"))
    forged = with_payload(token, bastion_claims(sub="v_attacker00"))
    _rejected(forged, RejectReason.SIGNATURE)


def test_pt9_tampered_signature_is_rejected() -> None:
    token = sign(BASTION, bastion_claims())
    head, payload, signature = token.split(".")
    flipped = ("A" if signature[0] != "A" else "B") + signature[1:]
    _rejected(f"{head}.{payload}.{flipped}", RejectReason.SIGNATURE)


def test_unknown_key_is_rejected() -> None:
    _rejected(sign(OTHER, bastion_claims()), RejectReason.SIGNATURE)


def test_no_keys_rejects_by_signature() -> None:
    _rejected(sign(BASTION, bastion_claims()), RejectReason.SIGNATURE, keys=())


@pytest.mark.parametrize(("iat_delta", "exp_delta"), [(0, 301), (0, 3600), (0, 0), (10, 0)])
def test_pt21_bad_lifetime_is_rejected(iat_delta: int, exp_delta: int) -> None:
    token = sign(BASTION, bastion_claims(iat=NOW + iat_delta - 5, exp=NOW + exp_delta - 5))
    _rejected(token, RejectReason.LIFETIME)


@pytest.mark.parametrize(
    "claim_overrides",
    [
        {"exp": DROP},
        {"iat": DROP},
        {"exp": "9999999999"},
        {"iat": str(NOW)},
        {"exp": float(NOW + 60)},
        {"iat": True},
        {"exp": None},
    ],
)
def test_pt21_missing_or_ill_typed_times_are_rejected(claim_overrides: dict[str, Any]) -> None:
    _rejected(sign(BASTION, bastion_claims(**claim_overrides)), RejectReason.CLAIMS)


@pytest.mark.parametrize("sub", [DROP, "", None, 7, ["v_x"]])
def test_pt22_missing_or_empty_subject_is_rejected(sub: Any) -> None:
    token = sign(BASTION, bastion_claims(sub=sub, iat=NOW, exp=NOW + 60))
    _rejected(token, RejectReason.CLAIMS)


@pytest.mark.parametrize(
    "token",
    [
        "",
        "not-a-jwt",
        "a.b",
        "a.b.c.d",
        "!!!.???.***",
    ],
)
def test_pt23_malformed_tokens_are_rejected(token: str) -> None:
    _rejected(token, RejectReason.MALFORMED)


def test_pt23_payload_that_is_not_an_object_is_rejected() -> None:
    import jwt as pyjwt

    token = pyjwt.api_jws.encode(b"[1,2,3]", BASTION.private, algorithm="EdDSA")
    _rejected(token, RejectReason.MALFORMED)

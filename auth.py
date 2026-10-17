"""Shizuha ID tokens. Atlas does not ask Wiki who the caller is."""

from __future__ import annotations

import os
from dataclasses import dataclass

import jwt
from jwt import PyJWKClient

from token_revocation import is_token_revoked


@dataclass(frozen=True)
class Caller:
    user_id: int
    username: str
    memberships: dict[str, str]
    is_staff: bool = False

    def organizations(self) -> list[int]:
        found = []
        for key in self.memberships:
            try:
                found.append(int(key))
            except (TypeError, ValueError):
                continue
        return found

    def allows(self, organization_id: int) -> bool:
        return str(organization_id) in self.memberships


_jwks: PyJWKClient | None = None


def _memberships(claims: dict) -> dict[str, str]:
    raw = claims.get("organization_memberships") or {}
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def _user_id(claims: dict) -> int:
    value = claims.get("user_id")
    if isinstance(value, bool):
        raise jwt.InvalidTokenError("missing user")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise jwt.InvalidTokenError("missing user")


def caller_from_claims(claims: dict) -> Caller:
    return Caller(
        user_id=_user_id(claims),
        username=str(claims.get("username") or ""),
        memberships=_memberships(claims),
        is_staff=bool(claims.get("is_staff") or claims.get("is_superuser")),
    )


def platform_revocation_required() -> bool:
    """Shizuha ID is the revocation authority only for a platform install.

    A standalone process sets ATLAS_JWT_SECRET and does not set a JWKS or
    revocation URL. Its tokens are not in the ID store, and the default
    http://shizuha-id:8001 lookup would fail closed and lock the operator out.
    """
    if os.environ.get("SHIZUHA_REVOCATION_STATUS_URL", "").strip():
        return True
    if os.environ.get("ATLAS_JWKS_URL", "").strip():
        return True
    return False


def _reject_if_revoked(claims: dict, token: str) -> None:
    if platform_revocation_required() and is_token_revoked(claims, token):
        raise jwt.InvalidTokenError("Token has been revoked")


def verify_token(token: str) -> Caller:
    secret = os.environ.get("ATLAS_JWT_SECRET")
    if secret:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        _reject_if_revoked(claims, token)
        return caller_from_claims(claims)
    jwks_url = os.environ.get("ATLAS_JWKS_URL")
    if not jwks_url:
        raise jwt.InvalidTokenError("atlas auth is not configured")
    header = jwt.get_unverified_header(token)
    if header.get("alg") != "RS256":
        raise jwt.InvalidTokenError("unsupported token")
    global _jwks
    if _jwks is None or getattr(_jwks, "uri", None) != jwks_url:
        _jwks = PyJWKClient(jwks_url)
    key = _jwks.get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token,
        key.key,
        algorithms=["RS256"],
        options={"verify_aud": False},
    )
    _reject_if_revoked(claims, token)
    return caller_from_claims(claims)

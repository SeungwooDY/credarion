"""Authentication primitives — password hashing and session tokens.

Deliberately dependency-free: uses only the Python standard library so the
backend gains real auth without pulling in bcrypt/passlib/PyJWT.

  - Passwords are hashed with scrypt (a memory-hard KDF in hashlib) using a
    random per-password salt. Stored as: ``scrypt$n$r$p$<salt_b64>$<hash_b64>``.
  - Session tokens are compact JWT-style strings signed with HMAC-SHA256
    (the "HS256" algorithm): ``base64url(header).base64url(payload).base64url(sig)``.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from app.config import settings

# scrypt cost parameters. n must be a power of 2; these are a sensible balance
# of security and latency (~tens of ms per hash).
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32


# ── base64url helpers ────────────────────────────────────────────


def _b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64u_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


# ── password hashing ─────────────────────────────────────────────


def hash_password(password: str) -> str:
    """Hash a plaintext password with scrypt and a fresh random salt."""
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N,
        _SCRYPT_R,
        _SCRYPT_P,
        _b64u_encode(salt),
        _b64u_encode(derived),
    )


# A valid scrypt hash of an unguessable value, computed once at import. The
# login path verifies against this when no user matches, so an unknown email
# costs the same scrypt work as a real one — closing the timing oracle that
# would otherwise reveal which emails exist.
DUMMY_PASSWORD_HASH = hash_password("credarion-login-timing-equalizer")


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verify a plaintext password against a stored scrypt hash."""
    try:
        scheme, n_s, r_s, p_s, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        n, r, p = int(n_s), int(r_s), int(p_s)
        salt = _b64u_decode(salt_b64)
        expected = _b64u_decode(hash_b64)
    except (ValueError, TypeError):
        return False

    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=len(expected),
    )
    return hmac.compare_digest(derived, expected)


# ── session tokens (HS256 JWT) ───────────────────────────────────


def _sign(signing_input: bytes) -> str:
    sig = hmac.new(
        settings.auth_secret_key.encode("utf-8"), signing_input, hashlib.sha256
    ).digest()
    return _b64u_encode(sig)


def create_access_token(subject: str, *, ttl_hours: int | None = None, now: int | None = None) -> str:
    """Create a signed session token for ``subject`` (the user id).

    ``now`` is injectable for testing; defaults to the current unix time.
    """
    issued = int(time.time()) if now is None else now
    ttl = settings.auth_token_ttl_hours if ttl_hours is None else ttl_hours
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": subject, "iat": issued, "exp": issued + ttl * 3600}
    segments = [
        _b64u_encode(json.dumps(header, separators=(",", ":")).encode("utf-8")),
        _b64u_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
    ]
    signing_input = ".".join(segments).encode("ascii")
    segments.append(_sign(signing_input))
    return ".".join(segments)


def decode_access_token(token: str, *, now: int | None = None) -> dict[str, Any] | None:
    """Validate signature + expiry and return the payload, or None if invalid."""
    try:
        header_b64, payload_b64, sig = token.split(".")
    except (ValueError, AttributeError):
        return None

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    if not hmac.compare_digest(_sign(signing_input), sig):
        return None

    try:
        payload = json.loads(_b64u_decode(payload_b64))
    except (ValueError, TypeError):
        return None

    current = int(time.time()) if now is None else now
    exp = payload.get("exp")
    if not isinstance(exp, int) or current >= exp:
        return None
    return payload

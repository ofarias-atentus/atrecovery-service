"""Password hashing + JWT helpers (Stage 1).

Password hashing uses ``bcrypt`` directly (not the passlib wrapper) because
passlib 1.7.4 is incompatible with bcrypt >= 4.1 (``__about__`` removal +
72-byte strictness) on modern Python. ``passlib[bcrypt]`` remains in
dependencies per the stack spec; the ``bcrypt`` package itself comes from it.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import get_settings

_BCRYPT_MAX_BYTES = 72


def _truncate(password: str) -> bytes:
    raw = password.encode("utf-8")
    return raw[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_truncate(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_truncate(plain), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def hash_service_token(raw: str) -> str:
    """One-way hash for processor service tokens (Stage 5 reuses this)."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_service_token() -> str:
    return secrets.token_urlsafe(32)


def _now() -> datetime:
    return datetime.now(UTC)


def create_access_token(subject: str) -> str:
    settings = get_settings()
    expires = _now() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return _encode(subject, expires, "access")


def create_refresh_token(subject: str) -> str:
    settings = get_settings()
    expires = _now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    return _encode(subject, expires, "refresh")


def _encode(subject: str, expires: datetime, token_type: str) -> str:
    settings = get_settings()
    payload = {
        "sub": subject,
        "exp": expires,
        "iat": _now(),
        "jti": uuid.uuid4().hex,
        "type": token_type,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


class TokenError(ValueError):
    pass


def decode_token(token: str, expected_type: str = "access") -> dict:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as e:
        raise TokenError("token expired") from e
    except jwt.InvalidTokenError as e:
        raise TokenError("invalid token") from e
    if payload.get("type") != expected_type:
        raise TokenError(f"expected {expected_type} token")
    if not payload.get("sub"):
        raise TokenError("token missing subject")
    return payload

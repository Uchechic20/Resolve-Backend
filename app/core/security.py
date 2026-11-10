"""Resolve: password hashing and JWT helpers.


"""
import asyncio
import base64
import hashlib
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from jwt.exceptions import PyJWTError
from app.core.config import settings
from app.exceptions import AuthenticationError
from app.models import Claims

ACCESS = "access"
REFRESH = "refresh"
VERIFY = "verify"

def decode_claims(token:str,token_type:str) ->dict:
    try:
        payload=jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm]
        )
        return payload
    except jwt.PyJWTError:
        raise AuthenticationError("invalid or expired token")


# --------------------------------------------------------------------------
# Passwords. bcrypt is CPU-heavy and would block the event loop, so it runs
# in a worker thread. Pre-hashing with SHA-256 removes bcrypt's 72-byte limit.
# --------------------------------------------------------------------------
def _prehash(password: str) -> bytes:
    return base64.b64encode(hashlib.sha256(password.encode()).digest())


def _hash(password: str) -> str:
    salt = bcrypt.gensalt(rounds=settings.bcrypt_rounds)
    return bcrypt.hashpw(_prehash(password), salt).decode()


def _verify(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(_prehash(password), hashed.encode())


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_hash, password)


async def verify_password(password: str, hashed: str) -> bool:
    return await asyncio.to_thread(_verify, password, hashed)


_dummy_hash: str | None = None


async def burn_password_check(password: str) -> None:
    """Spend the same time as a real check when the email doesn't exist,
    so response timing doesn't reveal which emails are registered."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = await hash_password("not-a-real-password")
    await verify_password(password, _dummy_hash)


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------

def create_token(
        subject: int,
        token_type: str,
        expires: timedelta,
        token_version: int = 0,
        jti: str | None = None
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(subject),
        "type": token_type,
        "iat": now,
        "exp": now + expires,
        "token_version": token_version,
    }

    if jti:
        payload["jti"] = jti

    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: int, token_version: int, jti: str = None) -> str:
    return create_token(
        subject=user_id,
        token_type=ACCESS,
        expires=timedelta(minutes=settings.access_token_minutes),
        token_version=token_version,
        jti=jti
    )


def create_refresh_token(user_id: int, token_version: int, jti: str = None) -> str:
    return create_token(
        subject=user_id,
        token_type=REFRESH,
        expires=timedelta(days=settings.refresh_token_days),
        token_version=token_version,
        jti=jti
    )


def create_verify_token(user_id: int) -> str:
    return create_token(
        subject=user_id,
        token_type=VERIFY,
        expires=timedelta(hours=settings.verify_token_hours)
    )


def decode_token(token: str, expected_type: str) -> dict:
    """Return the payload dictionary, or raise AuthenticationError."""
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm]
        )
    except PyJWTError:
        raise AuthenticationError("Invalid or expired token")

    if payload.get("type") != expected_type:
        raise AuthenticationError("Wrong token type")

    # Return the raw dictionary. Do NOT use Claims(**payload)
    # unless you have explicitly defined 'token_version' in the Claims class!
    return payload
"""Password hashing and token helpers. No database needed."""
from datetime import timedelta

import pytest

from app.core import security
from app.exceptions import AuthenticationError


async def test_password_hash_roundtrip():
    hashed = await security.hash_password("Passw0rd!")
    assert hashed != "Passw0rd!"
    assert await security.verify_password("Passw0rd!", hashed)
    assert not await security.verify_password("passw0rd!", hashed)


async def test_long_passwords_are_fully_used():
    """bcrypt alone ignores everything past 72 bytes; the SHA-256 pre-hash fixes that."""
    base = "A1!" * 30  # 90 chars
    hashed = await security.hash_password(base)
    assert await security.verify_password(base, hashed)
    assert not await security.verify_password(base[:-1] + "Z", hashed)


async def test_same_password_gets_different_hashes():
    assert await security.hash_password("Passw0rd!") != await security.hash_password("Passw0rd!")


def test_access_token_roundtrip():
    token = security.create_access_token(42,token_version=0)
    claims= security.decode_token(token, security.ACCESS)
    assert claims["sub"]  =="42"


def test_token_type_is_enforced():
    refresh = security.create_refresh_token(7,token_version=0)
    with pytest.raises(AuthenticationError):
        security.decode_token(refresh, security.ACCESS)
    with pytest.raises(AuthenticationError):
        security.decode_token(security.create_access_token(7,token_version=0), security.REFRESH)
    with pytest.raises(AuthenticationError):
        security.decode_token(security.create_access_token(7,token_version=0), security.VERIFY)


def test_expired_token_rejected():
    token = security.create_token(1, security.ACCESS, timedelta(seconds=-5))
    with pytest.raises(AuthenticationError):
        security.decode_token(token, security.ACCESS)


def test_garbage_and_tampered_tokens_rejected():
    with pytest.raises(AuthenticationError):
        security.decode_token("not-a-token", security.ACCESS)
    token = security.create_access_token(1,token_version=0)
    with pytest.raises(AuthenticationError):
        security.decode_token(token[:-3] + "abc", security.ACCESS)
@pytest.mark.asyncio
async def test_burn_password_check_does_not_raise():
    await security.burn_password_check("whatever")

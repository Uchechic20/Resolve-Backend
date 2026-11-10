"""Resolve: encryption for secrets stored in the database (MFA seeds).


"""
import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


@lru_cache
def _fernet() -> Fernet:
    key = settings.field_encryption_key
    if not key:
        digest = hashlib.sha256(("resolve-field-key:" + settings.secret_key).encode()).digest()
        key = base64.urlsafe_b64encode(digest).decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_field(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_field(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Stored secret could not be decrypted (was the key changed?)") from exc
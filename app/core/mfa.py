"""Resolve: TOTP multi-factor authentication (RFC 6238), compatible with Google
Authenticator, Microsoft Authenticator, Authy, 1Password and similar apps.


"""
import hashlib
import hmac
import secrets
import time

import pyotp

from app.core.config import settings

STEP_SECONDS = 30
RECOVERY_CODE_COUNT = 8
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no look-alike characters


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, email: str) -> str:
    """The otpauth:// link that authenticator apps read from a QR code."""
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=settings.mfa_issuer)


def verify_code(
    secret: str, code: str, last_step: int | None = None, now: float | None = None
) -> int | None:
    """Return the accepted time step, or None.

    Accepts the previous, current and next 30-second window (clock drift) and
    refuses any step at or before `last_step`, so a code cannot be used twice.
    """
    code = (code or "").strip().replace(" ", "")
    if not (code.isdigit() and len(code) == 6):
        return None
    totp = pyotp.TOTP(secret)
    current = int((now if now is not None else time.time()) // STEP_SECONDS)
    for step in (current - 1, current, current + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(totp.generate_otp(step), code):
            return step
    return None


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    """One-time codes for when the phone is lost, formatted xxxxx-xxxxx."""
    out = []
    for _ in range(count):
        raw = "".join(secrets.choice(_ALPHABET) for _ in range(10))
        out.append(f"{raw[:5]}-{raw[5:]}")
    return out


def hash_recovery_code(code: str) -> str:
    normalized = code.strip().lower().replace("-", "").replace(" ", "")
    return hashlib.sha256(normalized.encode()).hexdigest()
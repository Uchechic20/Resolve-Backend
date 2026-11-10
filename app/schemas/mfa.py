"""Resolve: request and response shapes for multi-factor authentication (TOTP)."""
from pydantic import BaseModel, Field, model_validator


class MfaChallenge(BaseModel):
    """Login answer for accounts with MFA: the password was right, now send a code."""

    mfa_required: bool = True
    mfa_token: str  # short-lived; only good for POST /auth/login/mfa


class MfaLogin(BaseModel):
    """Second step of login: the challenge token plus ONE proof of the second factor."""

    mfa_token: str
    code: str | None = Field(None, description="6-digit code from the authenticator app")
    recovery_code: str | None = Field(None, description="One-time recovery code")

    @model_validator(mode="after")
    def exactly_one(self):
        if bool(self.code) == bool(self.recovery_code):
            raise ValueError("Send either 'code' or 'recovery_code'")
        return self


class MfaSetupRead(BaseModel):
    secret: str  # for typing into an app by hand
    otpauth_uri: str  # for a QR code


class MfaEnable(BaseModel):
    code: str


class MfaRecoveryCodes(BaseModel):
    recovery_codes: list[str]  # shown ONCE; only hashes are stored


class MfaDisable(BaseModel):
    """Turning MFA off needs the password AND one proof of the second factor."""

    password: str
    code: str | None = None
    recovery_code: str | None = None

    @model_validator(mode="after")
    def exactly_one(self):
        if bool(self.code) == bool(self.recovery_code):
            raise ValueError("Send either 'code' or 'recovery_code'")
        return self


__all__ = [
    "MfaChallenge", "MfaDisable", "MfaEnable", "MfaLogin", "MfaRecoveryCodes", "MfaSetupRead",
]
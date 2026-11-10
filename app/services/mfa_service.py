"""Resolve: multi-factor authentication (TOTP authenticator apps + recovery codes).

The flow
  login        POST /auth/login          password OK + MFA on  ->  MfaChallenge   (challenge)
               POST /auth/login/mfa      challenge + code      ->  tokens         (login)
  enrol        POST /auth/mfa/setup      secret + QR link
               POST /auth/mfa/enable     first code            ->  8 recovery codes (shown once)
  turn off     POST /auth/mfa/disable    password + code       ->  tokens         (disable)
  lost phone   POST /admin/users/{id}/reset-mfa                 (admin)

Safeguards: the secret is stored ENCRYPTED; a code works once (time-step replay
protection); a recovery code works once; disabling needs the password too; every
change to MFA signs the user out everywhere (token_version).
"""
import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto, mfa, security
from app.exceptions import AuthenticationError, BusinessRuleError, ConflictError
from app.models import User
from app.repositories import UserRepository
from app.schemas.mfa import MfaChallenge, MfaDisable, MfaLogin
from app.schemas.mfa_login import Token
from app.services.auth_service import AuthService


class MfaService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.users = UserRepository(session)

    # ------------------------------------------------------- challenge + login
    @staticmethod
    def challenge(user: User) -> MfaChallenge:
        """Step 1 of login for an MFA account (called by AuthService.login once the
        password has been verified). The token proves the password, nothing more:
        it cannot be used as a session."""
        return MfaChallenge(mfa_token=security.create_mfa_token(user.id))

    async def login(self, data: MfaLogin) -> Token:
        """Step 2: exchange the challenge plus a code (or recovery code) for tokens."""
        claims = security.decode_claims(data.mfa_token, security.MFA)
        user = await self.users.get(claims.user_id)
        if user is None or not user.is_active or not user.mfa_enabled:
            raise AuthenticationError("Invalid or expired token")
        if not self.verify_second_factor(user, data.code, data.recovery_code):
            raise AuthenticationError("Incorrect verification code")
        await self.session.commit()  # saves the replay marker / used recovery code
        return AuthService.tokens_for(user)

    @staticmethod
    def verify_second_factor(user: User, code: str | None, recovery_code: str | None) -> bool:
        """True if the proof is valid. Mutates the user (marks the code as used);
        the caller must commit."""
        if recovery_code:
            hashes = json.loads(user.mfa_recovery_hashes or "[]")
            wanted = mfa.hash_recovery_code(recovery_code)
            if wanted not in hashes:
                return False
            hashes.remove(wanted)  # each recovery code works once
            user.mfa_recovery_hashes = json.dumps(hashes)
            return True
        if not code or not user.mfa_secret_enc:
            return False
        step = mfa.verify_code(crypto.decrypt_field(user.mfa_secret_enc), code, user.mfa_last_step)
        if step is None:
            return False
        user.mfa_last_step = step  # this code (and any older one) can never be used again
        return True

    # --------------------------------------------------------------- enrolment
    async def setup(self, user: User) -> tuple[str, str]:
        """Start enrolment. Nothing is enforced until the first code is confirmed."""
        if user.mfa_enabled:
            raise ConflictError("MFA is already enabled")
        secret = mfa.new_secret()
        user.mfa_secret_enc = crypto.encrypt_field(secret)
        user.mfa_last_step = None
        await self.session.commit()
        return secret, mfa.provisioning_uri(secret, user.email)

    async def enable(self, user: User, code: str) -> list[str]:
        if user.mfa_enabled:
            raise ConflictError("MFA is already enabled")
        if not user.mfa_secret_enc:
            raise BusinessRuleError("Start MFA setup first")
        step = mfa.verify_code(crypto.decrypt_field(user.mfa_secret_enc), code)
        if step is None:
            raise AuthenticationError("Incorrect verification code")
        codes = mfa.generate_recovery_codes()
        user.mfa_enabled = True
        user.mfa_last_step = step
        user.mfa_recovery_hashes = json.dumps([mfa.hash_recovery_code(c) for c in codes])
        await self.session.commit()
        return codes  # shown once; only hashes are stored

    # ----------------------------------------------------------------- disable
    async def disable(self, user: User, data: MfaDisable) -> Token:
        if not user.mfa_enabled:
            raise BusinessRuleError("MFA is not enabled")
        if not await security.verify_password(data.password, user.password_hash):
            raise AuthenticationError("Current password is incorrect")
        if not self.verify_second_factor(user, data.code, data.recovery_code):
            raise AuthenticationError("Incorrect verification code")
        self.clear(user)
        await self.session.commit()
        return AuthService.tokens_for(user)  # fresh tokens: this device stays signed in

    @staticmethod
    def clear(user: User) -> None:
        """Remove MFA and sign the user out everywhere. Also used by the admin reset."""
        user.mfa_enabled = False
        user.mfa_secret_enc = None
        user.mfa_recovery_hashes = None
        user.mfa_last_step = None
        user.token_version += 1
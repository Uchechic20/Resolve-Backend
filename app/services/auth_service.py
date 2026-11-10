"""Resolve: accounts and sessions.

Registration, login (with optional MFA), refresh-token rotation, logout,
password reset / change, and MFA enrolment.

How sessions can be ended early (the old "tokens cannot be revoked" limitation):
- one token  -> its `jti` goes in the revoked_tokens table (logout, refresh rotation)
- all tokens -> `users.token_version` is bumped (logout-all, password change,
                role change, MFA changes, refresh-token reuse)
"""
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto, mfa, security
from app.exceptions import (
    AuthenticationError,
    BusinessRuleError,
    ConflictError,
)
from app.models import User
from app.repositories.security import (
    NotificationRepository,
    RevokedTokenRepository,
)
from app.repositories.UserRepository import UserRepository
from app.schemas.mfa import (
    MfaChallenge,
    MfaDisable,
    MfaLogin,
)
from app.schemas.user import UserLogin, UserRegister
from app.schemas.mfa_login import Token


class AuthService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.users = UserRepository(session)
        self.revoked = RevokedTokenRepository(session)
        self.outbox = NotificationRepository(session)

    # ------------------------------------------------------------ registration
    async def register(self, data: UserRegister) -> tuple[User, str]:
        """Returns (user, verification_token). The router emails the token."""
        if await self.users.get_by_email(data.email):
            raise ConflictError("An account with this email already exists")
        user = await self.users.create(
            email=data.email,
            password_hash=await security.hash_password(data.password),
            full_name=data.full_name,
        )
        await self.session.commit()
        return user, security.create_verify_token(user.id)

    async def verify_email(self, token: str) -> User:
        # FIX: decode_token returns a dictionary, not an object
        claims = security.decode_token(token, security.VERIFY)
        user_id = int(claims.get("sub"))

        user = await self.users.get(user_id)
        if user is None:
            raise AuthenticationError("Invalid or expired token")
        user.is_verified = True
        await self.session.commit()
        return user

    async def resend_verification(self, email: str) -> str | None:
        """A fresh token to email, or None. The router answers identically either
        way, so this cannot be used to discover which emails have accounts."""
        user = await self.users.get_by_email(email)
        if user is None or user.is_verified or not user.is_active:
            return None
        return security.create_verify_token(user.id)

    # ------------------------------------------------------------------ login
    async def login(self, data: UserLogin) -> Token | MfaChallenge:
        user = await self.users.get_by_email(data.email)
        if user is None:
            await security.burn_password_check(data.password)
            raise AuthenticationError("Incorrect email or password")
        if not await security.verify_password(data.password, user.password_hash):
            raise AuthenticationError("Incorrect email or password")
        if not user.is_active:
            raise AuthenticationError("This account has been deactivated")
        if user.mfa_enabled:
            return MfaChallenge(mfa_token=security.create_mfa_token(user.id))
        return self._tokens(user)

    async def login_mfa(self, data: MfaLogin) -> Token:
        claims = security.decode_claims(data.mfa_token, security.MFA)

        # FIX: Use dictionary access for the user ID
        user_id = int(claims.get("sub"))
        user = await self.users.get(user_id)

        if user is None or not user.is_active or not user.mfa_enabled:
            raise AuthenticationError("Invalid or expired token")
        if not await self._check_second_factor(user, data.code, data.recovery_code):
            raise AuthenticationError("Incorrect verification code")
        await self.session.commit()
        return self._tokens(user)

    async def _check_second_factor(
            self, user: User, code: str | None, recovery_code: str | None
    ) -> bool:
        """Mutates the user (replay protection / consumed recovery code); caller commits."""
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
        user.mfa_last_step = step
        return True

    # ----------------------------------------------------- tokens and sessions
    async def authenticate(self, token: str) -> tuple[User, dict]:
        """Used on every request. Checks signature, expiry, revocation and version."""
        claims = security.decode_claims(token, security.ACCESS)

        if await self.revoked.is_revoked(claims.get("jti")):
            raise AuthenticationError("Invalid or expired token")


        user_id = int(claims.get("sub"))
        user = await self.users.get(user_id)


        if user is None or not user.is_active or claims.get("token_version") != user.token_version:
            raise AuthenticationError("Invalid or expired token")

        return user, claims

    async def user_from_access_token(self, token: str) -> User:
        return (await self.authenticate(token))[0]

    async def refresh(self, refresh_token: str) -> Token:
        """Rotation: every refresh retires the old refresh token."""
        claims = security.decode_claims(refresh_token, security.REFRESH)

        # 1. Use .get("sub") and convert to int
        user_id = int(claims.get("sub"))
        user = await self.users.get(user_id)

        # 2. Check "token_version"
        if user is None or not user.is_active or claims.get("token_version") != user.token_version:
            raise AuthenticationError("Invalid or expired token")

        # 3. Use .get("jti")
        jti = claims.get("jti")
        reason = await self.revoked.revocation_reason(jti)

        if reason == "rotated":
            user.token_version += 1
            await self.session.commit()
            raise AuthenticationError("This refresh token was already used. Please log in again.")

        if reason is not None:
            raise AuthenticationError("Invalid or expired token")

        # 4. Use .get("exp") for expiration
        await self.revoked.revoke(jti, user.id, claims.get("exp"), reason="rotated")
        await self.session.commit()
        return self._tokens(user)

    async def logout(
            self, user: User, access_claims: dict, refresh_token: str | None = None
    ) -> None:
        await self.revoked.revoke(access_claims.get("jti"), user.id, access_claims.get("exp"))

        if refresh_token:
            try:
                rc = security.decode_claims(refresh_token, security.REFRESH)
            except AuthenticationError:
                rc = None

            # 6. Compare user IDs properly
            if rc and int(rc.get("sub")) == user.id:
                await self.revoked.revoke(rc.get("jti"), user.id, rc.get("exp"))

        await self.session.commit()

    async def logout_all(self, user: User) -> None:
        user.token_version += 1
        await self.session.commit()

    # --------------------------------------------------------------- passwords
    async def forgot_password(self, email: str) -> tuple[User, str] | None:
        """(user, reset_token), or None when there is no such active account."""
        user = await self.users.get_by_email(email)
        if user is None or not user.is_active:
            return None
        return user, security.create_reset_token(user.id, user.password_hash)

    async def reset_password(self, token: str, new_password: str) -> None:
        claims = security.decode_claims(token, security.RESET)

        # FIX: Use dictionary access for sub and pwf
        user_id = int(claims.get("sub"))
        user = await self.users.get(user_id)

        if (
                user is None
                or not user.is_active
                or claims.get("pwf") != security.password_fingerprint(user.password_hash)
        ):
            raise AuthenticationError("This reset link is invalid, expired or already used")
        await self._set_password(user, new_password)
        user.is_verified = True
        await self._security_alert(user, "Your password was reset")
        await self.session.commit()

    async def change_password(self, user: User, current: str, new: str) -> Token:
        if not await security.verify_password(current, user.password_hash):
            raise AuthenticationError("Current password is incorrect")
        if current == new:
            raise BusinessRuleError("The new password must be different from the current one")
        await self._set_password(user, new)
        await self._security_alert(user, "Your password was changed")
        await self.session.commit()
        return self._tokens(user)

    async def _set_password(self, user: User, new_password: str) -> None:
        user.password_hash = await security.hash_password(new_password)
        user.password_changed_at = datetime.now(timezone.utc)
        user.token_version += 1

    async def _security_alert(self, user: User, subject: str) -> None:
        await self.outbox.add(
            user_id=user.id,
            ticket_id=None,
            kind="security_alert",
            subject=subject,
            body=(
                f"{subject} on {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC.\n\n"
                "If this was you, no action is needed. If it was not, reset your "
                "password immediately and contact your administrator."
            ),
        )

    # --------------------------------------------------------------------- MFA
    async def mfa_setup(self, user: User) -> tuple[str, str]:
        if user.mfa_enabled:
            raise ConflictError("MFA is already enabled")
        secret = mfa.new_secret()
        user.mfa_secret_enc = crypto.encrypt_field(secret)
        user.mfa_last_step = None
        await self.session.commit()
        return secret, mfa.provisioning_uri(secret, user.email)

    async def mfa_enable(self, user: User, code: str) -> list[str]:
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
        return codes

    async def mfa_disable(self, user: User, data: MfaDisable) -> Token:
        if not user.mfa_enabled:
            raise BusinessRuleError("MFA is not enabled")
        if not await security.verify_password(data.password, user.password_hash):
            raise AuthenticationError("Current password is incorrect")
        if not await self._check_second_factor(user, data.code, data.recovery_code):
            raise AuthenticationError("Incorrect verification code")
        self.clear_mfa(user)
        await self.session.commit()
        return self._tokens(user)

    @staticmethod
    def clear_mfa(user: User) -> None:
        user.mfa_enabled = False
        user.mfa_secret_enc = None
        user.mfa_recovery_hashes = None
        user.mfa_last_step = None
        user.token_version += 1

    async def update_preferences(self, user: User, email_notifications: bool) -> User:
        user.email_notifications = email_notifications
        await self.session.commit()
        await self.session.refresh(user)
        return user

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _tokens(user: User) -> Token:
        # Generate unique JTIs for the access and refresh tokens
        access_jti = str(uuid.uuid4())
        refresh_jti = str(uuid.uuid4())

        return Token(
            access_token=security.create_access_token(user.id, user.token_version, jti=access_jti),
            refresh_token=security.create_refresh_token(user.id, user.token_version, jti=refresh_jti),
        )
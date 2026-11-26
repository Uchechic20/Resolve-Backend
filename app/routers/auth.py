"""Resolve: auth routes."""
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import ValidationError

from app.core.config import settings
from app.core.rate_limit import limiter
from app.dependencies import AuthSvc, CurrentUser
from app.exceptions import AuthenticationError
# Import the email function from your mailer file
from app.core.mailer import send_verification_email
from app.schemas import (
    ResendVerification,
    Token,
    TokenRefresh,
    UserLogin,
    UserRead,
    UserRegister,
)

auth_router = APIRouter(prefix="/auth", tags=["auth"])


@auth_router.post("/register", response_model=UserRead, status_code=201)
@limiter.limit(settings.rate_limit_register)
async def register(
        request: Request,
        data: UserRegister,
        background: BackgroundTasks,
        auth: AuthSvc
):
    """Registers a new user and sends a verification email."""
    # 1. Auth service creates the user (is_verified=False) and returns the token
    user, token = await auth.register(data)

    # 2. Extract first name for the email template
    first_name = user.full_name.split()[0] if user.full_name else "User"

    # 3. Send the email in the background
    background.add_task(
        send_verification_email,
        email=user.email,
        token=token,
        name=first_name
    )

    return user


@auth_router.get("/verify-email", response_model=UserRead)
async def verify_email(token: str, auth: AuthSvc):
    """Target of the link in the verification email."""
    return await auth.verify_email(token)


@auth_router.post("/resend-verification", status_code=202)
@limiter.limit(settings.rate_limit_resend)
async def resend_verification(
        request: Request,
        data: ResendVerification,
        background: BackgroundTasks,
        auth: AuthSvc,
):
    """Generates a new token and resends the verification email."""
    token = await auth.resend_verification(data.email)

    if token:
        # Look up the user to get their name for the template
        user = await auth.users.get_by_email(data.email)
        first_name = user.full_name.split()[0] if user.full_name else "User"

        background.add_task(
            send_verification_email,
            email=user.email,
            token=token,
            name=first_name
        )

    return {"detail": "If that account exists and is unverified, an email has been sent."}


@auth_router.post("/login", response_model=Token)
@limiter.limit(settings.rate_limit_login)
async def login(request: Request, data: UserLogin, auth: AuthSvc):
    return await auth.login(data)


@auth_router.post("/token", response_model=Token)
@limiter.limit(settings.rate_limit_login)
async def login_form(
        request: Request,
        form: Annotated[OAuth2PasswordRequestForm, Depends()],
        auth: AuthSvc,
):
    """Form-based login so Swagger's Authorize button works.
    The 'username' field is the email."""
    try:
        creds = UserLogin(email=form.username, password=form.password)
    except ValidationError:
        raise AuthenticationError("Incorrect email or password")
    return await auth.login(creds)


@auth_router.post("/refresh", response_model=Token)
@limiter.limit(settings.rate_limit_login)
async def refresh(request: Request, data: TokenRefresh, auth: AuthSvc):
    return await auth.refresh(data.refresh_token)


@auth_router.get("/me", response_model=UserRead)
async def me(user: CurrentUser):
    return user
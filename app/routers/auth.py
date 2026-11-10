"""Resolve: auth routes."""
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import ValidationError

from app.core.config import settings
from app.core.mailer import send_verification_email
from app.core.rate_limit import limiter
from app.dependencies import AuthSvc, CurrentUser
from app.exceptions import AuthenticationError
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
    request: Request, data: UserRegister, background: BackgroundTasks, auth: AuthSvc
):
    user, token = await auth.register(data)
    background.add_task(send_verification_email, user.email, token)
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
    """Always answers the same way, so it can't be used to discover
    which email addresses have accounts."""
    token = await auth.resend_verification(data.email)
    if token:
        background.add_task(send_verification_email, data.email, token)
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
    print(f"DEBUG->username:'{form.username}',password lenght:{len(form.password)}")
    try:
        creds=UserLogin(email=form.username,password=form.password)
    except ValidationError:
        raise AuthenticationError("incorrect email or password")
    return await auth.login(creds)
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

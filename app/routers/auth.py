"""Resolve: auth routes."""
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import ValidationError

from app.core.config import settings
from app.core.rate_limit import limiter
from app.dependencies import AuthSvc, CurrentUser
from app.exceptions import AuthenticationError
from app.schemas import (
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
    request: Request, data: UserRegister, auth: AuthSvc
):
    """Registers a new user. Auto-verified, no email required."""
    user = await auth.register(data)
    return user


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
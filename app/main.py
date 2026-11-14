"""Resolve: application entrypoint."""
import asyncio
import contextlib
from contextlib import asynccontextmanager
import sys
import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.models.base import Base
from app.core.database import engine
from app.core.log import setup_logging
from app.core.rate_limit import limiter, rate_limit_handler
from app.core.request_context import set_client_ip
from app.core.security_headers import SecurityHeadersMiddleware
from app.exceptions import STATUS_MAP, AuthenticationError, DomainError
from app.routers import all_routers
from app.core.config import settings

# --- CRITICAL: Import all models here so Base.metadata knows they exist ---
from app.models.user import User
from app.models.ticket import Ticket, TicketComment, TicketEvent, Attachment
from app.models.revoked_token import RevokedToken
from app.models.department import Department, Category
# --------------------------------------------------------------------------

current_dir = os.path.dirname(os.path.abspath(__file__))
resolve_dir = os.path.dirname(current_dir)
if resolve_dir not in sys.path:
    sys.path.insert(0, resolve_dir)

setup_logging()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Force rebuild: Drop all tables first, then create them perfectly
    async with engine.begin() as conn:
        # WARNING: This deletes all existing data in the database on every restart!
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    worker = None
    if settings.run_worker_in_api:
        from app.core import run_forever
        worker = asyncio.create_task(run_forever())

    yield

    # 2. Cleanup on shutdown
    if worker:
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker
    await engine.dispose()  # close the connection pool on shutdown


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
    # Don't publish interactive docs in production.
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json"
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Allows all origins
        allow_credentials=True,
        allow_methods=["*"],  # Allows all methods (GET, POST, etc.)
        allow_headers=["*"],  # Allows all headers
    )

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)


@app.middleware("http")
async def remember_client_ip(request: Request, call_next):
    """Lets services record WHO looked at a ticket from WHERE (see access_logs).
    Behind a proxy run uvicorn with --proxy-headers so this is the real client."""
    set_client_ip(request.client.host if request.client else None)
    return await call_next(request)


# Added last, so it is the OUTERMOST layer and covers every response (errors and
# CORS answers included).
if settings.security_headers_enabled:
    app.add_middleware(
        SecurityHeadersMiddleware,
        hsts=settings.hsts_active,
        hsts_max_age=settings.hsts_max_age_seconds,
    )


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError):
    # STATUS_MAP is ordered most-specific first (InvalidTransition before Conflict).
    code = next((c for t, c in STATUS_MAP.items() if isinstance(exc, t)), 400)
    headers = {"WWW-Authenticate": "Bearer"} if isinstance(exc, AuthenticationError) else None
    return JSONResponse(
        status_code=code, content={"detail": exc.message}, headers=headers
    )


for router in all_routers:
    app.include_router(router)


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok"}
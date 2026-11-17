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
from sqlalchemy import select

from app.models.base import Base
from app.core.database import engine, SessionLocal
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
from app.models.knowledge_base import KBArticle  # This will work now!

# --------------------------------------------------------------------------

current_dir = os.path.dirname(os.path.abspath(__file__))
resolve_dir = os.path.dirname(current_dir)
if resolve_dir not in sys.path:
    sys.path.insert(0, resolve_dir)

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Create missing tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 2. PERMANENT FIX: Auto-Seed Default Categories and Departments
    async with SessionLocal() as db:
        # Check if categories exist
        result = await db.execute(select(Category).limit(1))
        if not result.scalar_one_or_none():
            db.add_all([
                Category(name="Banking Issue"),
                Category(name="Technical Support"),
                Category(name="Account Access")
            ])
            await db.commit()

        # Check if departments exist
        result = await db.execute(select(Department).limit(1))
        if not result.scalar_one_or_none():
            db.add_all([
                Department(name="IT Support", is_active=True),
                Department(name="Customer Care", is_active=True)
            ])
            await db.commit()

    # 3. Start background workers
    worker = None
    if settings.run_worker_in_api:
        from app.core import run_forever
        worker = asyncio.create_task(run_forever())

    try:
        from app.services.sla_background_worker import run_sla_worker
        sla_task = asyncio.create_task(run_sla_worker())
    except ImportError:
        sla_task = None

    yield

    # 4. Cleanup
    if worker:
        worker.cancel()
    if sla_task:
        sla_task.cancel()
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json"
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)


@app.middleware("http")
async def remember_client_ip(request: Request, call_next):
    set_client_ip(request.client.host if request.client else None)
    return await call_next(request)


if settings.security_headers_enabled:
    app.add_middleware(
        SecurityHeadersMiddleware,
        hsts=settings.hsts_active,
        hsts_max_age=settings.hsts_max_age_seconds,
    )


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError):
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
"""Resolve: async engine and session factory."""
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,  # drop dead connections instead of failing a request
)


SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

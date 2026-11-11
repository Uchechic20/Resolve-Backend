"""Resolve: async engine and session factory."""
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.engine.url import make_url
from app.core.config import settings


db_url = make_url(settings.database_url)
# Neon uses 'sslmode' but asyncpg requires 'ssl'
if "sslmode" in db_url.query:
    db_url = db_url.difference_update_query(["sslmode", "channel_binding"])

# 2. Create the engine
engine = create_async_engine(
    db_url,
    echo=settings.db_echo,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,  # drop dead connections instead of failing a request
    # 3. Tell asyncpg to use SSL for Neon
    connect_args={"ssl": True} if "neon.tech" in str(db_url) else {}
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
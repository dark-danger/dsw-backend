import os
import re
import ssl as _ssl
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

db_url = settings.DATABASE_URL

if not db_url:
    # Use a persistent SQLite file shared by all async sessions
    db_path = "/tmp/dsw_portal.db" if os.path.exists("/tmp") else os.path.abspath("dsw_portal.db")
    db_url = f"sqlite+aiosqlite:///{db_path}"

# Convert postgres:// or postgresql:// to postgresql+asyncpg://
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif db_url.startswith("postgresql://") and not db_url.startswith("postgresql+"):
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

if db_url.startswith("postgresql+asyncpg"):
    connect_args = {
        "timeout": 10.0,
        "command_timeout": 10.0,
        "statement_cache_size": 0
    }
    # asyncpg does NOT accept sslmode/channel_binding as query params
    # Strip them out and pass ssl via connect_args instead
    db_url = re.sub(r'[\&?]sslmode=[^\&]*', '', db_url)
    db_url = re.sub(r'[\&?]channel_binding=[^\&]*', '', db_url)
    # Clean any trailing ? or & left over
    db_url = re.sub(r'\?$', '', db_url)
    db_url = re.sub(r'\&$', '', db_url)
    # Always use SSL for Supabase/external PostgreSQL
    ssl_ctx = _ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = _ssl.CERT_NONE
    connect_args["ssl"] = ssl_ctx

elif db_url.startswith("sqlite"):
    connect_args = {
        "check_same_thread": False
    }
else:
    connect_args = {}

print(f"[DB] Using: {db_url[:40]}...")

engine_kwargs = {
    "echo": False,
    "connect_args": connect_args,
    "pool_pre_ping": True,
}

if db_url.startswith("postgresql"):
    engine_kwargs.update({
        "pool_size": 5,
        "max_overflow": 10,
        "pool_recycle": 300,
        "pool_timeout": 10.0,
    })

engine = create_async_engine(
    db_url,
    **engine_kwargs
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

class Base(DeclarativeBase):
    pass

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

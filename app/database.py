import re
import ssl as _ssl
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

db_url = settings.DATABASE_URL

if not db_url:
    # Provide a dummy URL just to allow the module to load without throwing an ArgumentError.
    # The middleware will catch the missing URL and throw a proper HTTP 500 error.
    db_url = "sqlite+aiosqlite:///:memory:"

# Convert postgres:// or postgresql:// to postgresql+asyncpg://
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif db_url.startswith("postgresql://") and not db_url.startswith("postgresql+"):
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

connect_args = {
    "timeout": 5.0,
    "command_timeout": 5.0
}

if db_url.startswith("postgresql+asyncpg"):
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
    # Supabase Supavisor (Transaction Pooler port 6543) does NOT support
    # prepared statements. Disabling cache prevents "database does not exist" errors.
    connect_args["statement_cache_size"] = 0

elif db_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False

print(f"[DB] Using: {db_url[:40]}...")

engine = create_async_engine(
    db_url,
    echo=False,
    connect_args=connect_args,
    pool_pre_ping=True
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

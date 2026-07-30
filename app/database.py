import re
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

db_url = settings.DATABASE_URL

# Convert postgres:// or postgresql:// to postgresql+asyncpg://
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif db_url.startswith("postgresql://") and not db_url.startswith("postgresql+"):
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

connect_args = {}

if db_url.startswith("postgresql+asyncpg"):
    # asyncpg does NOT accept sslmode/channel_binding as query params
    # Strip them out and pass ssl=True via connect_args instead
    has_ssl = "sslmode=require" in db_url or "sslmode=prefer" in db_url
    db_url = re.sub(r'[&?]sslmode=[^&]*', '', db_url)
    db_url = re.sub(r'[&?]channel_binding=[^&]*', '', db_url)
    # Clean any trailing ? or & left over
    db_url = re.sub(r'\?$', '', db_url)
    db_url = re.sub(r'&$', '', db_url)
    if has_ssl:
        connect_args["ssl"] = True

elif db_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False

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

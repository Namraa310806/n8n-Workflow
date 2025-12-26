import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from .base import Base

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/n8n_popularity",
)

# Try to create an async engine; if async DB driver is missing (e.g. asyncpg),
# fall back to None so scripts that only need JSON fallback can run.
try:
    engine = create_async_engine(DATABASE_URL, echo=False)
    AsyncSession = async_sessionmaker(engine, expire_on_commit=False)

    async def init_db():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
except Exception as e:
    # Missing async DB driver or connection issue — disable DB path
    print(f"Warning: async DB engine not available ({e}); DB upserts will be skipped")
    engine = None
    AsyncSession = None

    async def init_db():
        raise RuntimeError("DB engine not configured")

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from .models import Base

DATABASE_URL = "sqlite+aiosqlite:///./flax_assistant.db"

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Safe migrations — add columns that may not exist in older DBs
    async with engine.begin() as conn:
        for sql in [
            "ALTER TABLE tasks ADD COLUMN priority INTEGER DEFAULT 3",
            "ALTER TABLE tasks ADD COLUMN is_blocked BOOLEAN DEFAULT 0",
            "ALTER TABLE tasks ADD COLUMN blocked_reason TEXT",
            "ALTER TABLE tasks ADD COLUMN is_recurring BOOLEAN DEFAULT 0",
            "ALTER TABLE tasks ADD COLUMN recurrence_days INTEGER",
            "ALTER TABLE users ADD COLUMN focus_until DATETIME",
            "ALTER TABLE users ADD COLUMN google_calendar_token TEXT",
            "ALTER TABLE users ADD COLUMN last_reflection_at DATETIME",
        ]:
            try:
                await conn.execute(text(sql))
            except Exception:
                pass  # column already exists


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

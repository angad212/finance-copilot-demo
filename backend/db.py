from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config import settings

engine = create_async_engine(settings.database_url, echo=settings.sql_echo)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


def sqlglot_dialect() -> str:
    return "postgres" if engine.dialect.name == "postgresql" else engine.dialect.name


async def check_db() -> bool:
    async with SessionLocal() as session:
        result = await session.execute(text("SELECT 1"))
        return result.scalar() == 1


async def get_session():
    async with SessionLocal() as session:
        yield session


async def init_models() -> None:
    """Create any missing tables. Existing tables are left untouched."""
    from models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

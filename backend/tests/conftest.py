import os

# Must be set before the app modules are imported.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_finance.db"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["JWT_SECRET"] = "test-secret"
os.environ["LLM_BACKOFF_SECONDS"] = "0"

import httpx
import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def fresh_db():
    import ratelimit
    from db import engine
    from models import Base

    ratelimit.reset()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture
async def client():
    from main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()

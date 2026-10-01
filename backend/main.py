from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from config import settings
from db import check_db, init_models
from routers import auth, ledger, pipeline, query


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_models()
    yield


app = FastAPI(title="Finance Copilot", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(ledger.router)
app.include_router(pipeline.router)
app.include_router(query.router)


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok", "db": await check_db(), "llm_configured": bool(settings.anthropic_api_key)}


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse("/app/")


app.mount("/app", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="app")

"""FastAPI app entrypoint: lifespan (background task registry), router mount, /health."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.video_requests import router as video_requests_router
from app.utils.logging import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.background_tasks: set[asyncio.Task] = set()
    logger.info("App startup: background task registry ready")
    yield
    pending = app.state.background_tasks
    if pending:
        logger.info(f"App shutdown: draining {len(pending)} in-flight task(s)")
        await asyncio.gather(*pending, return_exceptions=True)


app = FastAPI(title="AI Chemistry Video Request Service", lifespan=lifespan)
app.include_router(video_requests_router)


@app.get("/health")
async def health():
    return {"status": "ok"}

"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.routes import router
from app.core.request_context import reset_current_user_id, set_current_user_id
from app.core.settings import settings
from app.dependencies import get_auth_service, get_knowledge_base_service


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CurrentUserContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        base_token = set_current_user_id(None)
        current_token = None
        try:
            try:
                auth_service = get_auth_service()
                user_id = await run_in_threadpool(auth_service.resolve_effective_user_id_from_request, request)
                current_token = set_current_user_id(user_id)
            except Exception:
                current_token = None

            response = await call_next(request)
            return response
        finally:
            if current_token is not None:
                reset_current_user_id(current_token)
            reset_current_user_id(base_token)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build the index once when the app starts."""
    if settings.rebuild_index_on_startup:
        service = get_knowledge_base_service()
        try:
            await run_in_threadpool(service.rebuild_index)
        except Exception as exc:  # pragma: no cover
            logger.warning("Initial index build skipped: %s", exc)
    else:
        logger.info("Initial index build skipped because REBUILD_INDEX_ON_STARTUP=false.")
    yield


app = FastAPI(
    title="RAG Knowledge Base",
    version="1.0.0",
    description="A local RAG knowledge base built with FastAPI.",
    lifespan=lifespan,
)

app.add_middleware(CurrentUserContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "message": "RAG knowledge base backend is running.",
        "docs": "/docs",
        "health": "/api/health",
    }

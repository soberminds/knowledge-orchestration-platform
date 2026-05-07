"""FastAPI 应用入口。

这个文件负责把路由、CORS、启动逻辑串起来。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from app.api.routes import router
from app.core.settings import settings
from app.dependencies import get_knowledge_base_service


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动时做一次索引重建。

    这样你把文档放进 data/docs 后，后端启动就能自动可用。
    """
    service = get_knowledge_base_service()
    try:
        # 重建索引是同步任务，放到线程池里执行，避免阻塞事件循环。
        await run_in_threadpool(service.rebuild_index)
    except Exception as exc:  # pragma: no cover - 启动失败不让整站挂掉
        logger.warning("Initial index build skipped: %s", exc)
    yield


app = FastAPI(
    title="RAG Knowledge Base",
    version="1.0.0",
    description="A DeepSeek-powered local RAG knowledge base built with FastAPI.",
    lifespan=lifespan,
)

# 允许前端开发服务器访问后端接口。
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
    """根路径，方便快速确认后端是否启动成功。"""
    return {
        "message": "RAG knowledge base backend is running.",
        "docs": "/docs",
        "health": "/api/health",
    }


"""依赖注入入口。

FastAPI 会通过这里拿到知识库服务实例。
"""

from __future__ import annotations

from functools import lru_cache

from app.services.knowledge_base import KnowledgeBaseService


@lru_cache(maxsize=1)
def get_knowledge_base_service() -> KnowledgeBaseService:
    """进程内只创建一个服务实例，避免重复加载模型和向量库。"""
    return KnowledgeBaseService()


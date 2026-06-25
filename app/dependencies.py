"""FastAPI dependency entry points."""

from __future__ import annotations

from functools import lru_cache

from app.services.chat_memory import ChatMemoryService
from app.services.knowledge_base import KnowledgeBaseService


@lru_cache(maxsize=1)
def get_knowledge_base_service() -> KnowledgeBaseService:
    """Create one knowledge-base service for the backend process."""
    return KnowledgeBaseService()


@lru_cache(maxsize=1)
def get_chat_memory_service() -> ChatMemoryService:
    """Create one chat-memory service for the backend process."""
    return ChatMemoryService()

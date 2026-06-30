"""FastAPI dependency entry points."""

from __future__ import annotations

from functools import lru_cache

from app.services.auth import UserAuthService
from app.services.agent_tools import AgentToolConfirmationService
from app.services.chat_memory import ChatMemoryService
from app.services.document_library import DocumentLibraryService
from app.services.knowledge_base import KnowledgeBaseService


@lru_cache(maxsize=1)
def get_knowledge_base_service() -> KnowledgeBaseService:
    """Create one knowledge-base service for the backend process."""
    service = KnowledgeBaseService()
    service.attach_tool_confirmation_service(get_agent_tool_confirmation_service())
    return service


@lru_cache(maxsize=1)
def get_chat_memory_service() -> ChatMemoryService:
    """Create one chat-memory service for the backend process."""
    return ChatMemoryService()


@lru_cache(maxsize=1)
def get_document_library_service() -> DocumentLibraryService:
    """Create one document-library service for the backend process."""
    return DocumentLibraryService()


@lru_cache(maxsize=1)
def get_auth_service() -> UserAuthService:
    """Create one auth service for the backend process."""
    return UserAuthService()


@lru_cache(maxsize=1)
def get_agent_tool_confirmation_service() -> AgentToolConfirmationService:
    """Create one in-process Agent tool confirmation service."""
    return AgentToolConfirmationService()

"""Agent 工具。

这个文件给 LangChain Agent 预留一个“查知识库”的工具函数。
"""

from __future__ import annotations

import json

from langchain_core.tools import tool

from app.services.knowledge_base import KnowledgeBaseService


def build_search_tool(service: KnowledgeBaseService):
    """把知识库检索能力包装成 LangChain Tool。

    Agent 后面如果想“自己先查资料再回答”，就可以直接调用这个工具。
    """

    @tool("search_knowledge_base")
    def search_knowledge_base(query: str, top_k: int | None = None) -> str:
        """搜索本地知识库，并返回 JSON 格式结果。"""
        hits = service.search(query=query, top_k=top_k)
        payload = [
            {
                "source": hit.source,
                "page": hit.page,
                "chunk_index": hit.chunk_index,
                "score": hit.score,
                "preview": hit.preview,
                "content": hit.content,
            }
            for hit in hits
        ]
        return json.dumps(payload, ensure_ascii=False, indent=2)

    return search_knowledge_base


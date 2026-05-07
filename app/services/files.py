"""文档读取工具。

这个文件负责把 Markdown、TXT、PDF、DOCX 转成 LangChain 的 Document。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from langchain_core.documents import Document

from app.core.settings import settings


def iter_source_files() -> list[Path]:
    """扫描 data/docs 和 data/uploads，找出所有支持的文档。"""
    files: list[Path] = []
    for base_dir in (settings.docs_dir, settings.uploads_dir):
        if not base_dir.exists():
            continue
        for path in sorted(base_dir.rglob("*")):
            if path.is_file() and path.suffix.lower() in settings.supported_extensions:
                files.append(path)
    return files


def file_info(path: Path) -> dict[str, str | int]:
    """给前端展示文件信息。"""
    stat = path.stat()
    return {
        "path": str(path.relative_to(settings.root_dir)).replace("\\", "/"),
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "extension": path.suffix.lower(),
    }


def _relative_source(path: Path) -> str:
    """把绝对路径转成更适合展示的相对路径。"""
    return str(path.relative_to(settings.root_dir)).replace("\\", "/")


def load_documents_from_file(path: Path) -> list[Document]:
    """把单个文件转成 LangChain Document 列表。

    不同格式的处理方式不一样：
    - txt/md：直接读全文
    - pdf：按页读取
    - docx：把段落拼起来
    """
    suffix = path.suffix.lower()
    base_metadata = {
        "source": _relative_source(path),
        "file_name": path.name,
        "extension": suffix,
    }

    # Markdown / TXT 直接读取文本内容。
    if suffix in {".txt", ".md", ".markdown"}:
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        if not text:
            return []
        return [Document(page_content=text, metadata=base_metadata)]

    # PDF 需要按页抽取，方便后面给出 page 来源。
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover - 依赖缺失时给出明确错误
            raise RuntimeError("Missing dependency: pypdf") from exc

        reader = PdfReader(str(path))
        documents: list[Document] = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if not text:
                continue
            metadata = {**base_metadata, "page": page_number}
            documents.append(Document(page_content=text, metadata=metadata))
        return documents

    # DOCX 读取段落并合并，先做成一个大 Document。
    if suffix == ".docx":
        try:
            from docx import Document as DocxDocument
        except ImportError as exc:  # pragma: no cover - 依赖缺失时给出明确错误
            raise RuntimeError("Missing dependency: python-docx") from exc

        doc = DocxDocument(str(path))
        paragraphs = [paragraph.text.strip() for paragraph in doc.paragraphs if paragraph.text.strip()]
        if not paragraphs:
            return []
        return [Document(page_content="\n".join(paragraphs), metadata=base_metadata)]

    return []


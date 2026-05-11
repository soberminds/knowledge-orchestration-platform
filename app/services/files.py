"""Document loading utilities."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from langchain_core.documents import Document

from app.core.settings import settings

# Common plain-text formats that can be loaded with UTF-8 fallback.
TEXT_FILE_EXTENSIONS: tuple[str, ...] = (
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".tsv",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".xml",
    ".ini",
    ".cfg",
    ".conf",
    ".toml",
    ".log",
    ".rst",
    ".rtf",
    ".sql",
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".go",
    ".rs",
    ".sh",
    ".bat",
    ".ps1",
)

RICH_DOC_EXTENSIONS: tuple[str, ...] = (".pdf", ".docx")


def iter_source_files() -> list[Path]:
    """Scan data/docs and data/uploads for supported files."""
    files: list[Path] = []
    for base_dir in (settings.docs_dir, settings.uploads_dir):
        if not base_dir.exists():
            continue
        for path in sorted(base_dir.rglob("*")):
            if path.is_file() and path.suffix.lower() in settings.supported_extensions:
                files.append(path)
    return files


def file_info(path: Path) -> dict[str, str | int]:
    """Build metadata for frontend file list."""
    stat = path.stat()
    return {
        "path": str(path.relative_to(settings.root_dir)).replace("\\", "/"),
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "extension": path.suffix.lower(),
    }


def _relative_source(path: Path) -> str:
    return str(path.relative_to(settings.root_dir)).replace("\\", "/")


def load_documents_from_file(path: Path) -> list[Document]:
    """Convert a single source file into LangChain Documents."""
    suffix = path.suffix.lower()
    base_metadata = {
        "source": _relative_source(path),
        "file_name": path.name,
        "extension": suffix,
    }

    if suffix in TEXT_FILE_EXTENSIONS:
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        if not text:
            return []
        return [Document(page_content=text, metadata=base_metadata)]

    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover
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

    if suffix == ".docx":
        try:
            from docx import Document as DocxDocument
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Missing dependency: python-docx") from exc

        doc = DocxDocument(str(path))
        paragraphs = [paragraph.text.strip() for paragraph in doc.paragraphs if paragraph.text.strip()]
        if not paragraphs:
            return []
        return [Document(page_content="\n".join(paragraphs), metadata=base_metadata)]

    return []

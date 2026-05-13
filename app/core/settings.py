"""Project runtime settings loaded from .env and environment variables."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _load_env_file(path: Path) -> None:
    """Tiny .env loader, so the app works without python-dotenv."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        # Some editors save UTF-8 with BOM; strip BOM to keep key parsing stable.
        line = raw_line.lstrip("\ufeff").strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("export "):
            line = line[7:].strip()

        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        value = value.strip().strip('"').strip("'")
        if key:
            # Keep .env as the source of truth for local development so edits
            # take effect after a normal app restart/reload.
            os.environ[key] = value


ROOT_DIR = Path(__file__).resolve().parents[2]
_load_env_file(ROOT_DIR / ".env")

# Silence Chroma telemetry by default to avoid noisy runtime logs.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "FALSE")


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


@dataclass(frozen=True)
class Settings:
    """Centralized immutable settings object."""

    root_dir: Path = ROOT_DIR
    data_dir: Path = ROOT_DIR / "data"
    docs_dir: Path = ROOT_DIR / "data" / "docs"
    uploads_dir: Path = ROOT_DIR / "data" / "uploads"
    chroma_dir: Path = ROOT_DIR / "data" / "chroma_db"
    preview_pdf_dir: Path = ROOT_DIR / "data" / "preview_pdf"
    collection_name: str = os.getenv("CHROMA_COLLECTION", "rga_knowledge_base")

    # LLM provider settings.
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    qwen_api_key: str = os.getenv("QWEN_API_KEY", "")
    qwen_base_url: str = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    zai_api_key: str = os.getenv("ZAI_API_KEY", "")
    zai_base_url: str = os.getenv("ZAI_BASE_URL", "https://api.z.ai/api/paas/v4")
    kimi_api_key: str = os.getenv("KIMI_API_KEY", "")
    kimi_base_url: str = os.getenv("KIMI_BASE_URL", "https://api.moonshot.cn/v1")
    hunyuan_api_key: str = os.getenv("HUNYUAN_API_KEY", "")
    hunyuan_base_url: str = os.getenv("HUNYUAN_BASE_URL", "https://api.hunyuan.cloud.tencent.com/v1")
    siliconflow_api_key: str = os.getenv("SILICONFLOW_API_KEY", "")
    siliconflow_base_url: str = os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
    qianfan_api_key: str = os.getenv("QIANFAN_API_KEY", "")
    qianfan_base_url: str = os.getenv("QIANFAN_BASE_URL", "https://qianfan.baidubce.com/v2")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model_provider_overrides_json: str = os.getenv("MODEL_PROVIDER_OVERRIDES_JSON", "").strip()
    extra_provider_configs_json: str = os.getenv("EXTRA_PROVIDER_CONFIGS_JSON", "").strip()
    available_models: tuple[str, ...] = tuple(
        model.strip()
        for model in os.getenv("AVAILABLE_MODELS", "").split(",")
        if model.strip()
    )

    # Optional external web search provider.
    web_search_provider: str = os.getenv("WEB_SEARCH_PROVIDER", "none").strip().lower()
    web_search_api_key: str = os.getenv("WEB_SEARCH_API_KEY", "").strip()
    web_search_top_k: int = _env_int("WEB_SEARCH_TOP_K", 5)
    cost_currency: str = os.getenv("COST_CURRENCY", "CNY").strip().upper()
    model_pricing_json: str = os.getenv("MODEL_PRICING_JSON", "").strip()

    # Local embedding model for retrieval.
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
    embedding_device: str = os.getenv("EMBEDDING_DEVICE", "cpu")

    # RAG tuning.
    top_k: int = _env_int("TOP_K", 4)
    chunk_size: int = _env_int("CHUNK_SIZE", 800)
    chunk_overlap: int = _env_int("CHUNK_OVERLAP", 120)
    temperature: float = _env_float("TEMPERATURE", 0.2)
    max_tokens: int = _env_int("MAX_TOKENS", 1024)
    max_upload_mb: int = _env_int("MAX_UPLOAD_MB", 20)
    preview_convert_timeout_sec: int = _env_int("PREVIEW_CONVERT_TIMEOUT_SEC", 120)
    soffice_bin: str = os.getenv("SOFFICE_BIN", "").strip()

    cors_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if origin.strip()
    )

    supported_extensions: tuple[str, ...] = (
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
        ".pdf",
        ".doc",
        ".docx",
        ".xlsx",
        ".xlsm",
        ".xls",
    )


settings = Settings()

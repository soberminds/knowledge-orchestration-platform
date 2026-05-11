"""项目全局配置。

这个文件只做三件事：
1. 从 `.env` 读取配置
2. 统一管理目录、模型和切片参数
3. 避免把敏感信息写死在代码里
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _load_env_file(path: Path) -> None:
    """手写一个很轻量的 `.env` 读取器。

    这样项目即使没有安装 python-dotenv 也能运行。
    """
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("export "):
            line = line[7:].strip()

        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


# 项目根目录，后面所有路径都以它为基准。
ROOT_DIR = Path(__file__).resolve().parents[2]
_load_env_file(ROOT_DIR / ".env")

# Silence Chroma telemetry by default to avoid noisy runtime errors.
# Users can still override these in `.env` when needed.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "FALSE")


def _env_int(name: str, default: int) -> int:
    """把环境变量转成整数。"""
    return int(os.getenv(name, str(default)))


def _env_float(name: str, default: float) -> float:
    """把环境变量转成浮点数。"""
    return float(os.getenv(name, str(default)))


@dataclass(frozen=True)
class Settings:
    """把所有配置集中成一个对象，调用起来更清晰。"""

    root_dir: Path = ROOT_DIR
    data_dir: Path = ROOT_DIR / "data"
    docs_dir: Path = ROOT_DIR / "data" / "docs"
    uploads_dir: Path = ROOT_DIR / "data" / "uploads"
    chroma_dir: Path = ROOT_DIR / "data" / "chroma_db"
    collection_name: str = os.getenv("CHROMA_COLLECTION", "rga_knowledge_base")

    # 这里不要写死真实 key，统一从环境变量读取。
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

    # 本地向量模型，用于检索，不走大模型接口。
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
    embedding_device: str = os.getenv("EMBEDDING_DEVICE", "cpu")

    # RAG 相关调参。
    top_k: int = _env_int("TOP_K", 4)
    chunk_size: int = _env_int("CHUNK_SIZE", 800)
    chunk_overlap: int = _env_int("CHUNK_OVERLAP", 120)
    temperature: float = _env_float("TEMPERATURE", 0.2)
    max_tokens: int = _env_int("MAX_TOKENS", 1024)
    max_upload_mb: int = _env_int("MAX_UPLOAD_MB", 20)

    cors_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if origin.strip()
    )

    supported_extensions: tuple[str, ...] = (".md", ".markdown", ".txt", ".pdf", ".docx")


settings = Settings()

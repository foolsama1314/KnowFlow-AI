"""全局配置：默认值来自环境变量 / .env，可被 data/settings.json 中的运行时设置覆盖。"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 打包为桌面程序后：代码与静态资源解压在临时目录，用户数据放在 exe 同级目录。
IS_FROZEN = bool(getattr(sys, "frozen", False))

if IS_FROZEN:
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    RESOURCE_DIR = Path(__file__).resolve().parents[2]
    PROJECT_ROOT = RESOURCE_DIR.parent

BACKEND_DIR = RESOURCE_DIR

# 数据目录可由用户自定义：位置记录在程序目录下的 storage.json（不放在 data 内，
# 否则改目录后就找不到这条记录了）。写入后需重启应用才会生效。
STORAGE_FILE = PROJECT_ROOT / "storage.json"
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"


def _read_custom_data_dir() -> Path | None:
    try:
        raw = json.loads(STORAGE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = raw.get("data_dir") if isinstance(raw, dict) else None
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(os.path.expandvars(value.strip())).expanduser()
    return path if path.is_absolute() else None


def custom_data_dir() -> Path | None:
    """返回用户自定义的数据目录；未自定义时为 None。"""
    return _read_custom_data_dir()


def set_custom_data_dir(path: Path) -> None:
    resolved = Path(os.path.expandvars(str(path))).expanduser().resolve()
    STORAGE_FILE.write_text(
        json.dumps({"data_dir": str(resolved)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def clear_custom_data_dir() -> None:
    STORAGE_FILE.unlink(missing_ok=True)


DATA_DIR = _read_custom_data_dir() or DEFAULT_DATA_DIR
FRONTEND_DIST = (
    RESOURCE_DIR / "frontend" / "dist"
    if IS_FROZEN
    else PROJECT_ROOT / "frontend" / "dist"
)

UPLOAD_DIR = DATA_DIR / "uploads"
PROCESSED_DIR = DATA_DIR / "processed"
EXPORT_DIR = DATA_DIR / "exports"
DATABASE_DIR = DATA_DIR / "database"
QDRANT_DIR = DATA_DIR / "qdrant"

SUPPORTED_DOCUMENT_TYPES = ("pdf", "docx", "txt", "md", "markdown")
SUPPORTED_IMAGE_TYPES = ("jpg", "jpeg", "png", "bmp", "webp")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # 应用
    app_name: str = "知枢 AI"
    app_version: str = "0.1.0"
    api_prefix: str = "/api/v1"
    debug: bool = False

    # 存储
    data_dir: Path = DATA_DIR
    database_url: str = ""
    qdrant_url: str = ""
    qdrant_collection: str = "document_chunks"

    # 模型服务
    llm_provider: str = "openai_compatible"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"

    embedding_provider: str = "openai_compatible"
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_model: str = ""
    embedding_dim: int = 1024

    # 处理参数
    chunk_size: int = 800
    chunk_overlap: int = 120
    max_upload_mb: int = 200
    default_top_k: int = 5
    max_concurrent_tasks: int = 2

    # RAG 问答
    rag_top_k: int = 5
    # 第三阶段实测：有答案问题 top1≈0.71，弱相关≈0.55，完全无关≈0.50，
    # 因此默认拒答阈值取 0.50，并保留设置页可调。
    rag_min_score: float = 0.50
    rag_context_chars: int = 6000

    # 允许上传的扩展名
    allowed_extensions: tuple[str, ...] = SUPPORTED_DOCUMENT_TYPES + SUPPORTED_IMAGE_TYPES

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        db_file = (self.data_dir / "database" / "knowflow.db").as_posix()
        return f"sqlite:///{db_file}"

    @property
    def qdrant_local_path(self) -> Path:
        return self.data_dir / "qdrant"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def export_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def embedding_configured(self) -> bool:
        return bool(self.embedding_api_key and self.embedding_model)

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key and self.llm_model)


_settings: Settings | None = None


def get_settings() -> Settings:
    """获取配置单例（含 data/settings.json 覆盖值）。"""
    global _settings
    if _settings is None:
        from app.core.settings_store import read_overrides

        overrides = {k: v for k, v in read_overrides().items() if v is not None}
        _settings = Settings(**overrides)
    return _settings


def reload_settings() -> Settings:
    """运行时设置变更后重新加载。"""
    global _settings
    _settings = None
    return get_settings()


def ensure_directories() -> None:
    for path in (
        get_settings().upload_dir,
        get_settings().processed_dir,
        get_settings().data_dir / "database",
        get_settings().export_dir,
        get_settings().qdrant_local_path,
    ):
        path.mkdir(parents=True, exist_ok=True)

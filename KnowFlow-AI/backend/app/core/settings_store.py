"""本地运行时设置：保存在 data/settings.json，用于页面内修改模型配置，无需改 .env。"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from app.core.config import DATA_DIR

SETTINGS_FILE = DATA_DIR / "settings.json"

# 允许通过页面覆盖的配置项
OVERRIDABLE_KEYS = {
    "llm_provider",
    "llm_api_key",
    "llm_base_url",
    "llm_model",
    "embedding_provider",
    "embedding_api_key",
    "embedding_base_url",
    "embedding_model",
    "embedding_dim",
    "chunk_size",
    "chunk_overlap",
    "default_top_k",
    "max_upload_mb",
    "rag_top_k",
    "rag_min_score",
    "rag_context_chars",
}

_lock = threading.Lock()


def read_overrides() -> dict[str, Any]:
    if not SETTINGS_FILE.exists():
        return {}
    try:
        raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if k in OVERRIDABLE_KEYS}


def write_overrides(values: dict[str, Any]) -> dict[str, Any]:
    """合并非空值并落盘；返回合并后的完整覆盖配置。"""
    with _lock:
        current = read_overrides()
        for key, value in values.items():
            if key not in OVERRIDABLE_KEYS:
                continue
            if isinstance(value, str):
                value = value.strip()
            if value is None or value == "":
                continue
            current[key] = value
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(
            json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return current


def clear_override(key: str) -> None:
    with _lock:
        current = read_overrides()
        if key in current:
            current.pop(key)
            SETTINGS_FILE.write_text(
                json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
            )

"""向量索引状态、模型身份校验与写入互斥。"""

from __future__ import annotations

import threading
from datetime import datetime

from app.ai.vector_store import vector_store
from app.core.config import get_settings
from app.core.errors import AIProviderError, ProcessingError
from app.models import Document, DocumentChunk, VectorIndexState
from app.schemas import VectorIndexStatusOut

INDEX_ID = "default"
INDEX_LOCK = threading.Lock()


def _identity() -> tuple[str, str, int]:
    settings = get_settings()
    return settings.embedding_provider, settings.embedding_model, settings.embedding_dim


def _configured() -> bool:
    settings = get_settings()
    return bool(settings.embedding_configured and settings.embedding_base_url)


def _state(db) -> VectorIndexState:
    state = db.get(VectorIndexState, INDEX_ID)
    if state is None:
        provider, model, dimension = _identity()
        state = VectorIndexState(
            id=INDEX_ID,
            provider=provider,
            model=model,
            dimension=dimension,
            status="not_indexed" if _configured() else "unconfigured",
            chunk_count=0,
            updated_at=datetime.now(),
        )
        db.add(state)
        db.flush()
    return state


def _out(state: VectorIndexState, chunk_count: int) -> VectorIndexStatusOut:
    return VectorIndexStatusOut(
        provider=state.provider,
        model=state.model,
        dimension=state.dimension,
        status=state.status,
        chunk_count=chunk_count,
        error=state.error,
        updated_at=state.updated_at,
    )


def get_index_status(db) -> VectorIndexStatusOut:
    """返回真实索引状态；旧哈希索引和模型不一致的索引必须重建。"""
    state = _state(db)
    count = vector_store.count()
    configured = _configured()

    if not configured:
        state.status = "unconfigured"
        state.error = "尚未配置 Embedding 向量服务"
    elif (state.provider, state.model, state.dimension) != _identity():
        state.status = "requires_reindex"
        state.error = "向量模型或维度已变化，必须使用当前模型重建索引"
    elif state.status == "completed" and count != state.chunk_count:
        state.status = "requires_reindex"
        state.error = (
            f"向量数量与索引记录不一致（记录 {state.chunk_count}，实际 {count}），请重建索引"
        )
    elif state.status in ("not_indexed", "unconfigured") and count:
        state.status = "requires_reindex"
        state.error = "检测到未登记模型身份的旧向量，请重建索引后再检索"
    elif state.status == "not_indexed" and not count:
        missing = (
            db.query(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .filter(Document.status == "completed")
            .count()
        )
        if missing:
            state.status = "requires_reindex"
            state.error = f"检测到 {missing} 个已解析文本块尚未建立向量，请重建索引"
    elif state.status == "unconfigured":
        state.status = "not_indexed"
        state.error = None

    state.updated_at = datetime.now()
    db.commit()
    return _out(state, count)


def require_index_ready(db) -> VectorIndexStatusOut:
    status = get_index_status(db)
    if status.status == "unconfigured":
        raise AIProviderError(
            "尚未配置 Embedding 向量服务，正式语义检索已停用。"
            "请到「系统设置」填写接口地址、API Key、模型名称和向量维度。"
        )
    if status.status != "completed":
        message = status.error or "向量索引尚未建立"
        raise ProcessingError(f"向量索引当前不可用：{message}。请先执行「重建索引」。")
    return status


def start_index_build(db) -> None:
    state = _state(db)
    state.provider, state.model, state.dimension = _identity()
    state.status = "building"
    state.error = None
    state.updated_at = datetime.now()
    db.commit()


def complete_index(db, chunk_count: int) -> None:
    state = _state(db)
    state.provider, state.model, state.dimension = _identity()
    state.status = "completed"
    state.chunk_count = chunk_count
    state.error = None
    state.updated_at = datetime.now()
    db.commit()


def fail_index(db, message: str) -> None:
    state = _state(db)
    state.status = "failed"
    state.error = message[:2000]
    state.updated_at = datetime.now()
    db.commit()


def require_reindex(db, message: str) -> None:
    state = _state(db)
    state.status = "requires_reindex" if _configured() else "unconfigured"
    state.error = message
    state.updated_at = datetime.now()
    db.commit()


def sync_count_after_delete(db) -> None:
    state = db.get(VectorIndexState, INDEX_ID)
    if state is not None and state.status == "completed":
        state.chunk_count = vector_store.count()
        state.updated_at = datetime.now()
        db.commit()

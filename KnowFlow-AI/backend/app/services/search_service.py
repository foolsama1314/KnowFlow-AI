"""真实 Embedding 语义检索与安全索引重建。"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from datetime import datetime

from sqlalchemy import select

from app.ai.registry import get_embedding
from app.ai.vector_store import vector_store
from app.core.errors import AppError, ConflictError, ProcessingError
from app.models import Document, DocumentChunk
from app.repositories import document_repository
from app.schemas import ReindexProgressOut, SearchFilters, SearchHit, SearchRequest, SearchResponse
from app.services.index_service import (
    INDEX_LOCK,
    complete_index,
    fail_index,
    require_index_ready,
    start_index_build,
)

logger = logging.getLogger(__name__)

REINDEX_BATCH = 32
UPSERT_BATCH = 64
_history: deque[dict] = deque(maxlen=20)
_history_lock = threading.Lock()

_reindex_state: dict = {
    "running": False,
    "processed": 0,
    "total": 0,
    "stage": "空闲",
    "error": None,
    "finished_at": None,
}
_reindex_state_lock = threading.Lock()


def _update_reindex(**values) -> None:
    with _reindex_state_lock:
        _reindex_state.update(values)


def reindex_progress() -> ReindexProgressOut:
    with _reindex_state_lock:
        state = dict(_reindex_state)
    return ReindexProgressOut(**state)


async def search(db, request: SearchRequest) -> SearchResponse:
    started = time.perf_counter()
    query = request.query.strip()
    filters: SearchFilters = request.filters
    index_status = require_index_ready(db)

    embedding = get_embedding()
    vector = await embedding.embed_query(query)
    raw_hits = await asyncio.to_thread(
        vector_store.search,
        vector,
        limit=request.top_k,
        document_ids=filters.document_ids,
        file_types=filters.file_types,
    )

    chunk_ids = [payload.get("chunk_id") for payload, _score in raw_hits if payload.get("chunk_id")]
    chunk_map = document_repository.get_chunks(db, [cid for cid in chunk_ids if cid])

    results: list[SearchHit] = []
    for payload, score in raw_hits:
        chunk_id = payload.get("chunk_id")
        chunk = chunk_map.get(chunk_id) if chunk_id else None
        if chunk is None:
            logger.warning("检索命中孤立向量：%s", chunk_id)
            continue
        document = document_repository.get_document(db, chunk.document_id)
        if document is None or document.status != "completed":
            continue
        results.append(
            SearchHit(
                chunk_id=chunk.id,
                document_id=document.id,
                document_name=document.original_name,
                file_type=document.file_type,
                page_from=chunk.page_from,
                page_to=chunk.page_to,
                content=chunk.content,
                score=round(score, 4),
            )
        )

    took_ms = int((time.perf_counter() - started) * 1000)
    with _history_lock:
        _history.appendleft(
            {
                "query": query,
                "top_k": request.top_k,
                "result_count": len(results),
                "at": datetime.now(),
            }
        )
    return SearchResponse(
        query=query,
        results=results,
        took_ms=took_ms,
        retrieval_mode="semantic",
        embedding_model=index_status.model,
        index_status=index_status,
    )


def history() -> list[dict]:
    with _history_lock:
        return list(_history)


async def reindex(db) -> dict:
    """在临时集合中完整重建，全部成功后才原子切换当前别名。"""
    if not INDEX_LOCK.acquire(blocking=False):
        raise ConflictError("另一个索引写入或重建任务正在执行，请稍后重试")

    started = time.perf_counter()
    staging: str | None = None
    activated = False
    _update_reindex(
        running=True,
        processed=0,
        total=0,
        stage="读取文本块",
        error=None,
        finished_at=None,
    )
    try:
        embedding = get_embedding()
        start_index_build(db)
        rows = db.execute(
            select(DocumentChunk, Document.file_type)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(Document.status == "completed")
            .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
        ).all()
        staging = await asyncio.to_thread(
            vector_store.create_staging_collection, embedding.dimension
        )

        total = len(rows)
        _update_reindex(total=total, stage=f"向量化 0/{total}")
        for start in range(0, total, REINDEX_BATCH):
            batch = rows[start : start + REINDEX_BATCH]
            vectors = await embedding.embed_documents([row.content for row, _type in batch])
            records = [
                {
                    "id": row.id,
                    "vector": vector,
                    "payload": {
                        "chunk_id": row.id,
                        "document_id": row.document_id,
                        "file_type": file_type,
                        "page_from": row.page_from,
                        "page_to": row.page_to,
                        "chunk_index": row.chunk_index,
                    },
                }
                for (row, file_type), vector in zip(batch, vectors, strict=True)
            ]
            for offset in range(0, len(records), UPSERT_BATCH):
                await asyncio.to_thread(
                    vector_store.upsert,
                    records[offset : offset + UPSERT_BATCH],
                    staging,
                )
            done = min(total, start + REINDEX_BATCH)
            _update_reindex(processed=done, stage=f"向量化 {done}/{total}")
            logger.info("重建索引进度：%d/%d", done, total)

        actual_count = await asyncio.to_thread(vector_store.count, staging)
        if actual_count != total:
            raise ProcessingError(
                f"重建结果数量不一致：应有 {total} 条，实际 {actual_count} 条，原索引未切换"
            )
        _update_reindex(stage="切换索引")
        await asyncio.to_thread(vector_store.activate_staging_collection, staging)
        activated = True
        complete_index(db, total)
        elapsed = int((time.perf_counter() - started) * 1000)
        _update_reindex(
            running=False,
            processed=total,
            stage="重建完成",
            error=None,
            finished_at=datetime.now(),
        )
        return {
            "chunks": total,
            "dimension": embedding.dimension,
            "elapsed_ms": elapsed,
        }
    except Exception as exc:
        if staging is not None and not activated:
            try:
                await asyncio.to_thread(vector_store.drop_collection, staging)
            except Exception:  # noqa: BLE001
                logger.warning("临时索引集合清理失败：%s", staging, exc_info=True)
        message = exc.message if isinstance(exc, AppError) else f"重建索引失败：{exc}"
        fail_index(db, message)
        _update_reindex(
            running=False, stage="重建失败", error=message, finished_at=datetime.now()
        )
        if isinstance(exc, AppError):
            raise
        raise ProcessingError(message) from exc
    finally:
        with _reindex_state_lock:
            _reindex_state["running"] = False
        INDEX_LOCK.release()

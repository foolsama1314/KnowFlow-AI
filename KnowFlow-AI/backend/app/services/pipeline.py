"""解析 → 结构化 → 切块 → 向量化 → 入库 的完整流水线。

任何一步失败都会把任务置为 failed，并把文档状态回写为 failed，绝不出现假成功。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from uuid import uuid4

from app.ai.registry import get_embedding
from app.ai.vector_store import vector_store
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.errors import AppError, ProcessingError
from app.models import Document, DocumentBlock, DocumentChunk, DocumentPage, ProcessingTask
from app.processors.chunker import build_chunks
from app.processors.document_parser import parse_document
from app.repositories import task_repository
from app.services.index_service import (
    INDEX_LOCK,
    complete_index,
    fail_index,
    get_index_status,
)
from app.tasks.runner import runner

logger = logging.getLogger(__name__)

EMBED_BATCH = 16
UPSERT_BATCH = 64


def _publish(task: ProcessingTask) -> None:
    runner.publish(
        {
            "task_id": task.id,
            "document_id": task.document_id,
            "status": task.status,
            "progress": task.progress,
            "current_step": task.current_step,
            "error_message": task.error_message,
        }
    )


def _progress(db, task: ProcessingTask, progress: int, step: str) -> None:
    task_repository.update_progress(db, task, progress, step)
    _publish(task)


def _commit_vectors(db, document: Document, records: list[dict], dimension: int) -> None:
    """全部向量生成成功后一次性替换该文档向量，失败时清理部分写入。"""
    with INDEX_LOCK:
        status = get_index_status(db)
        if status.status not in ("not_indexed", "completed"):
            raise ProcessingError(
                f"向量索引状态为 {status.status}，请先完成索引重建再导入文档"
            )
        vector_store.ensure_collection(dimension)
        try:
            vector_store.delete_document(document.id)
            for start in range(0, len(records), UPSERT_BATCH):
                vector_store.upsert(records[start : start + UPSERT_BATCH])
        except Exception as exc:
            try:
                vector_store.delete_document(document.id)
            except Exception:  # noqa: BLE001
                logger.error("部分向量清理失败：doc=%s", document.id, exc_info=True)
            fail_index(db, f"文档向量写入失败，已阻止不一致索引继续检索：{exc}")
            raise
        complete_index(db, vector_store.count())


async def run_pipeline(task_id: str, document_id: str) -> None:
    db = SessionLocal()
    task = db.get(ProcessingTask, task_id)
    document = db.get(Document, document_id)
    if task is None or document is None:
        logger.warning("任务或文档不存在：task=%s doc=%s", task_id, document_id)
        db.close()
        return

    try:
        task_repository.mark_running(db, task)
        document.status = "processing"
        db.commit()
        _publish(task)

        settings = get_settings()
        embedding = get_embedding()
        index_status = get_index_status(db)
        if index_status.status not in ("not_indexed", "completed"):
            raise ProcessingError(
                "向量模型已变化或索引不一致，请先在「语义检索」页执行「重建索引」"
            )
        path = settings.data_dir / document.file_path
        _progress(db, task, 5, "读取文件")

        parsed = await asyncio.to_thread(parse_document, path, document.file_type)
        _progress(
            db,
            task,
            35,
            f"解析完成：{len(parsed.pages)} 页，{parsed.text_length} 字符",
        )
        for warning in parsed.warnings:
            logger.warning("文档 %s：%s", document.id, warning)

        # 清理旧结果（重新解析 / 失败重试）
        db.query(DocumentBlock).filter(DocumentBlock.document_id == document.id).delete()
        db.query(DocumentChunk).filter(DocumentChunk.document_id == document.id).delete()
        db.query(DocumentPage).filter(DocumentPage.document_id == document.id).delete()
        db.commit()

        units: list[tuple[str, int]] = []
        for page in parsed.pages:
            page_row = DocumentPage(
                document_id=document.id,
                page_no=page.page_no,
                width=page.width,
                height=page.height,
                content=page.content,
                parse_method=page.parse_method,
                confidence=page.confidence,
            )
            db.add(page_row)
            db.flush()
            for block in page.blocks:
                if not block.content.strip():
                    continue
                db.add(
                    DocumentBlock(
                        document_id=document.id,
                        page_id=page_row.id,
                        block_type=block.block_type,
                        block_order=block.block_order,
                        content=block.content,
                        bbox=block.bbox,
                        confidence=block.confidence,
                    )
                )
                units.append((block.content, page.page_no))
        db.commit()
        _progress(db, task, 50, "写入页面与版面块")

        chunks = build_chunks(
            units, size=settings.chunk_size, overlap=settings.chunk_overlap
        )
        if not chunks:
            raise ProcessingError("未能生成可用于检索的文本块，请检查文件内容")

        chunk_rows: list[DocumentChunk] = []
        for index, chunk in enumerate(chunks):
            chunk_id = str(uuid4())
            row = DocumentChunk(
                id=chunk_id,
                document_id=document.id,
                content=chunk.content,
                chunk_index=index,
                page_from=chunk.page_from,
                page_to=chunk.page_to,
                token_count=chunk.token_count,
                qdrant_point_id=chunk_id,
            )
            db.add(row)
            chunk_rows.append(row)
        document.page_count = len(parsed.pages)
        document.chunk_count = len(chunk_rows)
        db.commit()
        _progress(db, task, 62, f"切块完成：{len(chunk_rows)} 个文本块")

        total = len(chunk_rows)
        records: list[dict] = []
        for start in range(0, total, EMBED_BATCH):
            batch = chunk_rows[start : start + EMBED_BATCH]
            vectors = await embedding.embed_documents([row.content for row in batch])
            records.extend(
                {
                    "id": row.id,
                    "vector": vector,
                    "payload": {
                        "chunk_id": row.id,
                        "document_id": document.id,
                        "file_type": document.file_type,
                        "page_from": row.page_from,
                        "page_to": row.page_to,
                        "chunk_index": row.chunk_index,
                    },
                }
                for row, vector in zip(batch, vectors, strict=True)
            )
            done = min(total, start + EMBED_BATCH)
            _progress(db, task, 62 + int(done / total * 33), f"向量化 {done}/{total}")

        await asyncio.to_thread(
            _commit_vectors, db, document, records, embedding.dimension
        )
        task_repository.mark_completed(db, task)
        document.status = "completed"
        document.updated_at = datetime.now()
        db.commit()
        _publish(task)
        logger.info("文档处理完成：%s（%d 块）", document.original_name, total)

    except AppError as exc:
        db.rollback()
        _fail(db, task_id, document_id, exc.message)
    except Exception as exc:  # noqa: BLE001
        logger.exception("文档处理失败：doc=%s", document_id)
        db.rollback()
        _fail(db, task_id, document_id, f"处理过程发生未预期错误：{exc}")
    finally:
        db.close()


def _fail(db, task_id: str, document_id: str, message: str) -> None:
    task = db.get(ProcessingTask, task_id)
    document = db.get(Document, document_id)
    if task is not None:
        task_repository.mark_failed(db, task, message)
        _publish(task)
    if document is not None:
        document.status = "failed"
        db.commit()
    logger.error("任务失败：task=%s，原因：%s", task_id, message)


__all__ = ["run_pipeline"]

"""文档上传、删除、重新解析等业务流程。"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.ai.vector_store import vector_store
from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError, ProcessingError
from app.models import Document, ProcessingTask
from app.processors.document_parser import detect_file_type
from app.repositories import document_repository, task_repository
from app.services.index_service import INDEX_LOCK, fail_index, sync_count_after_delete
from app.tasks.runner import runner

logger = logging.getLogger(__name__)

READ_CHUNK = 1024 * 1024


async def save_upload(db, file: UploadFile) -> tuple[Document, ProcessingTask]:
    settings = get_settings()
    original_name = Path(file.filename or "").name or "未命名文件"
    file_type = detect_file_type(original_name)
    suffix = Path(original_name).suffix.lower()

    target_dir = settings.upload_dir / datetime.now().strftime("%Y/%m")
    target_dir.mkdir(parents=True, exist_ok=True)
    temp_path = target_dir / f".{uuid4().hex}.part"

    hasher = hashlib.sha256()
    size = 0
    max_bytes = settings.max_upload_mb * 1024 * 1024
    try:
        with temp_path.open("wb") as buffer:
            while True:
                chunk = await file.read(READ_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise ProcessingError(
                        f"文件超过 {settings.max_upload_mb} MB 上限，请拆分后再上传"
                    )
                hasher.update(chunk)
                buffer.write(chunk)
        if size == 0:
            raise ProcessingError("文件内容为空，无法解析")

        digest = hasher.hexdigest()
        duplicated = document_repository.find_by_hash(db, digest)
        if duplicated is not None:
            raise ConflictError(
                f"该文件已存在：{duplicated.name}（{duplicated.id[:8]}），"
                "无需重复上传；如需重新解析请在文档详情中操作"
            )

        final_path = target_dir / f"{uuid4().hex}{suffix}"
        temp_path.replace(final_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    document = document_repository.create_document(
        db,
        name=Path(original_name).stem,
        original_name=original_name,
        file_type=file_type,
        file_size=size,
        file_path=final_path.relative_to(settings.data_dir).as_posix(),
        file_hash=digest,
    )
    task = task_repository.create_task(db, document_id=document.id)
    runner.submit(task.id, document.id)
    return document, task


def list_documents(db, **kwargs):  # type: ignore[no-untyped-def]
    return document_repository.list_documents(db, **kwargs)


def get_document_or_404(db, document_id: str) -> Document:
    document = document_repository.get_document(db, document_id)
    if document is None:
        raise NotFoundError("文档不存在或已被删除")
    return document


def get_document_content(db, document_id: str) -> tuple[Document, list]:
    document = get_document_or_404(db, document_id)
    pages = document_repository.get_pages(db, document_id)
    blocks = document_repository.get_blocks(db, document_id)
    grouped: dict[str, list] = {}
    for block in blocks:
        grouped.setdefault(block.page_id, []).append(block)
    for page in pages:
        page.blocks = grouped.get(page.id, [])  # type: ignore[attr-defined]
    return document, pages


def delete_document(db, document_id: str) -> None:
    document = get_document_or_404(db, document_id)
    file_path = get_settings().data_dir / document.file_path
    with INDEX_LOCK:
        try:
            vector_store.delete_document(document_id)
            document_repository.delete_document(db, document)
            sync_count_after_delete(db)
        except Exception as exc:
            db.rollback()
            fail_index(db, f"删除文档时数据一致性受损，请重建索引：{exc}")
            raise
    file_path.unlink(missing_ok=True)
    logger.info("已删除文档及关联数据：%s", document_id)


def reprocess_document(db, document_id: str) -> ProcessingTask:
    document = get_document_or_404(db, document_id)
    running = task_repository.latest_task(db, document_id)
    if running is not None and running.status in ("pending", "running"):
        raise ConflictError("该文档正在处理中，请等待当前任务结束后再试")
    if not (get_settings().data_dir / document.file_path).exists():
        raise NotFoundError("原始文件已丢失，请重新上传")

    document.status = "processing"
    db.commit()
    task = task_repository.create_task(db, document_id=document_id)
    runner.submit(task.id, document_id)
    return task


def raw_file_path(document: Document) -> Path:
    path = get_settings().data_dir / document.file_path
    if not path.exists():
        raise NotFoundError("原始文件不存在")
    return path


async def delete_document_async(db, document_id: str) -> None:
    await asyncio.to_thread(delete_document, db, document_id)

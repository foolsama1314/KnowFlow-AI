"""文档管理接口。"""

from __future__ import annotations

import asyncio
import mimetypes
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.vector_store import vector_store
from app.core.database import get_db
from app.core.errors import AppError
from app.models import Document, DocumentChunk, ProcessingTask
from app.schemas import (
    BatchUploadOut,
    DocumentContentOut,
    DocumentListOut,
    DocumentOut,
    IndexSummaryOut,
    PageOut,
    TaskOut,
    UploadItem,
)
from app.services import document_service
from app.services.index_service import get_index_status

router = APIRouter(prefix="/documents", tags=["documents"])


def _decorate_documents(db: Session, items: list[Document]) -> list[DocumentOut]:
    """为列表补充单文档索引状态与失败原因（批量查询，避免 N+1）。"""
    index_status = get_index_status(db)
    failed_ids = [item.id for item in items if item.status == "failed"]
    errors: dict[str, str] = {}
    if failed_ids:
        rows = db.execute(
            select(ProcessingTask.document_id, ProcessingTask.error_message)
            .where(
                ProcessingTask.document_id.in_(failed_ids),
                ProcessingTask.status == "failed",
            )
            .order_by(ProcessingTask.created_at.desc())
        ).all()
        for document_id, message in rows:
            if document_id not in errors and message:
                errors[document_id] = message

    result: list[DocumentOut] = []
    for item in items:
        out = DocumentOut.model_validate(item)
        if item.status in ("uploaded", "processing"):
            out.index_status = "processing"
        elif item.status == "failed":
            out.index_status = "failed"
            out.last_error = errors.get(item.id)
        elif item.status == "completed":
            out.index_status = "indexed" if index_status.status == "completed" else "not_indexed"
        else:
            out.index_status = "unknown"
        result.append(out)
    return result



def _to_task_out(task, document_name: str | None = None) -> TaskOut:
    data = TaskOut.model_validate(task)
    data.document_name = document_name
    return data


@router.post("/upload", response_model=UploadItem, status_code=201)
async def upload_document(
    file: UploadFile = File(...), db: Session = Depends(get_db)
) -> UploadItem:
    document, task = await document_service.save_upload(db, file)
    return UploadItem(document_id=document.id, task_id=task.id, name=document.original_name)


@router.post("/batch-upload", response_model=BatchUploadOut, status_code=201)
async def batch_upload(
    files: list[UploadFile] = File(...), db: Session = Depends(get_db)
) -> BatchUploadOut:
    succeeded: list[UploadItem] = []
    failed: list[dict[str, str]] = []
    for file in files:
        name = file.filename or "未命名文件"
        try:
            document, task = await document_service.save_upload(db, file)
            succeeded.append(
                UploadItem(document_id=document.id, task_id=task.id, name=document.original_name)
            )
        except AppError as exc:
            db.rollback()
            failed.append({"name": name, "message": exc.message})
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            failed.append({"name": name, "message": f"上传失败：{exc}"})
    return BatchUploadOut(succeeded=succeeded, failed=failed)


@router.get("", response_model=DocumentListOut)
def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    file_type: str | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
) -> DocumentListOut:
    items, total = document_service.list_documents(
        db,
        page=page,
        page_size=page_size,
        status=status,
        file_type=file_type,
        keyword=keyword,
    )
    return DocumentListOut(
        items=_decorate_documents(db, items),
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/index-summary", response_model=IndexSummaryOut)
def index_summary(db: Session = Depends(get_db)) -> IndexSummaryOut:
    status = get_index_status(db)
    completed = int(
        db.scalar(select(func.count()).select_from(Document).where(Document.status == "completed"))
        or 0
    )
    failed = int(
        db.scalar(select(func.count()).select_from(Document).where(Document.status == "failed")) or 0
    )
    total_documents = int(db.scalar(select(func.count()).select_from(Document)) or 0)
    total_chunks = int(
        db.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(Document.status == "completed")
        )
        or 0
    )
    running_tasks = int(
        db.scalar(
            select(func.count())
            .select_from(ProcessingTask)
            .where(ProcessingTask.status.in_(["pending", "running"]))
        )
        or 0
    )
    indexed_chunks = vector_store.count() if status.status == "completed" else 0
    pending_index = 0 if status.status == "completed" else completed
    return IndexSummaryOut(
        total_documents=total_documents,
        completed_documents=completed,
        failed_documents=failed,
        pending_index=pending_index,
        total_chunks=total_chunks,
        indexed_chunks=indexed_chunks,
        index_status=status,
        running_tasks=running_tasks,
    )


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, db: Session = Depends(get_db)) -> DocumentOut:
    document = document_service.get_document_or_404(db, document_id)
    return DocumentOut.model_validate(document)


@router.get("/{document_id}/content", response_model=DocumentContentOut)
def get_document_content(
    document_id: str, db: Session = Depends(get_db)
) -> DocumentContentOut:
    document, pages = document_service.get_document_content(db, document_id)
    return DocumentContentOut(
        document=DocumentOut.model_validate(document),
        pages=[PageOut.model_validate(page) for page in pages],
    )


@router.get("/{document_id}/preview")
def preview_document(document_id: str, db: Session = Depends(get_db)) -> FileResponse:
    document: Document = document_service.get_document_or_404(db, document_id)
    path = document_service.raw_file_path(document)
    media_type = mimetypes.guess_type(document.original_name)[0] or "application/octet-stream"
    encoded = quote(document.original_name)
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{encoded}"},
    )


@router.post("/{document_id}/reprocess", response_model=TaskOut, status_code=202)
def reprocess_document(document_id: str, db: Session = Depends(get_db)) -> TaskOut:
    task = document_service.reprocess_document(db, document_id)
    document = document_service.get_document_or_404(db, document_id)
    return _to_task_out(task, document.original_name)


@router.delete("/{document_id}", status_code=204)
async def delete_document(document_id: str, db: Session = Depends(get_db)) -> None:
    await asyncio.to_thread(document_service.delete_document, db, document_id)

"""首页统计。"""

from __future__ import annotations

from sqlalchemy import func, select

from app.models import Document, DocumentChunk, ProcessingTask
from app.schemas import StatsOut


def stats(db) -> StatsOut:
    document_count = db.scalar(select(func.count(Document.id))) or 0
    chunk_count = db.scalar(select(func.count(DocumentChunk.id))) or 0
    storage_bytes = db.scalar(select(func.coalesce(func.sum(Document.file_size), 0))) or 0

    by_file_type = {
        str(row[0]): int(row[1])
        for row in db.execute(
            select(Document.file_type, func.count(Document.id)).group_by(Document.file_type)
        ).all()
    }
    by_status = {
        str(row[0]): int(row[1])
        for row in db.execute(
            select(Document.status, func.count(Document.id)).group_by(Document.status)
        ).all()
    }
    task_running = (
        db.scalar(
            select(func.count(ProcessingTask.id)).where(
                ProcessingTask.status.in_(["pending", "running"])
            )
        )
        or 0
    )
    task_failed = (
        db.scalar(
            select(func.count(ProcessingTask.id)).where(ProcessingTask.status == "failed")
        )
        or 0
    )

    return StatsOut(
        document_count=int(document_count),
        chunk_count=int(chunk_count),
        storage_bytes=int(storage_bytes),
        task_running=int(task_running),
        task_failed=int(task_failed),
        by_file_type=by_file_type,
        by_status=by_status,
    )

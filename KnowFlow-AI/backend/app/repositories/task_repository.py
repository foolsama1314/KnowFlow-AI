"""任务数据访问。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from app.models import Document, ProcessingTask


def create_task(db, *, document_id: str, task_type: str = "parse") -> ProcessingTask:
    task = ProcessingTask(
        document_id=document_id,
        task_type=task_type,
        status="pending",
        progress=0,
        current_step="等待执行",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_task(db, task_id: str) -> ProcessingTask | None:
    return db.get(ProcessingTask, task_id)


def latest_task(db, document_id: str) -> ProcessingTask | None:
    return db.scalar(
        select(ProcessingTask)
        .where(ProcessingTask.document_id == document_id)
        .order_by(ProcessingTask.created_at.desc())
        .limit(1)
    )


def list_tasks(
    db,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[tuple[ProcessingTask, str]], int]:
    stmt = select(ProcessingTask, Document.name).join(
        Document, Document.id == ProcessingTask.document_id
    )
    count_stmt = select(func.count()).select_from(ProcessingTask)
    if status:
        stmt = stmt.where(ProcessingTask.status == status)
        count_stmt = count_stmt.where(ProcessingTask.status == status)
    total = db.scalar(count_stmt) or 0
    rows = db.execute(
        stmt.order_by(ProcessingTask.created_at.desc()).offset(offset).limit(limit)
    ).all()
    return [(row[0], row[1]) for row in rows], int(total)


def mark_running(db, task: ProcessingTask) -> None:
    task.status = "running"
    task.started_at = datetime.now()
    task.finished_at = None
    task.error_message = None
    db.commit()


def update_progress(db, task: ProcessingTask, progress: int, step: str) -> None:
    task.progress = max(0, min(100, int(progress)))
    task.current_step = step[:100]
    db.commit()


def mark_completed(db, task: ProcessingTask) -> None:
    task.status = "completed"
    task.progress = 100
    task.current_step = "已完成"
    task.finished_at = datetime.now()
    db.commit()


def mark_failed(db, task: ProcessingTask, message: str) -> None:
    task.status = "failed"
    task.error_message = message[:2000]
    task.current_step = "执行失败"
    task.finished_at = datetime.now()
    db.commit()


def fail_stale_tasks(db) -> int:
    """服务重启后，把仍在 running 的任务标记为失败，避免出现假运行状态。"""
    rows = db.scalars(
        select(ProcessingTask).where(ProcessingTask.status.in_(["running", "pending"]))
    ).all()
    for task in rows:
        task.status = "failed"
        task.error_message = "服务重启导致任务中断，请在任务中心重试"
        task.current_step = "已中断"
        task.finished_at = datetime.now()
    db.commit()
    return len(rows)

"""任务状态查询、SSE 进度订阅、重试与取消。"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import ConflictError, NotFoundError
from app.models import Document, ProcessingTask
from app.repositories import task_repository
from app.schemas import TaskListOut, TaskOut
from app.tasks.runner import runner

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _serialize(task: ProcessingTask, document_name: str | None = None) -> dict:
    return {
        "task_id": task.id,
        "document_id": task.document_id,
        "document_name": document_name,
        "status": task.status,
        "progress": task.progress,
        "current_step": task.current_step,
        "error_message": task.error_message,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


@router.get("", response_model=TaskListOut)
def list_tasks(
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> TaskListOut:
    rows, total = task_repository.list_tasks(db, status=status, limit=limit, offset=offset)
    items = []
    for task, document_name in rows:
        item = TaskOut.model_validate(task)
        item.document_name = document_name
        items.append(item)
    return TaskListOut(items=items, total=total)


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: str, db: Session = Depends(get_db)) -> TaskOut:
    task = task_repository.get_task(db, task_id)
    if task is None:
        raise NotFoundError("任务不存在")
    document = db.get(Document, task.document_id)
    item = TaskOut.model_validate(task)
    item.document_name = document.original_name if document else None
    return item


@router.get("/{task_id}/events")
async def task_events(
    task_id: str, request: Request, db: Session = Depends(get_db)
) -> StreamingResponse:
    task = task_repository.get_task(db, task_id)
    if task is None:
        raise NotFoundError("任务不存在")
    document = db.get(Document, task.document_id)
    snapshot = _serialize(task, document.original_name if document else None)

    async def event_stream():  # type: ignore[no-untyped-def]
        queue = runner.subscribe(task_id)
        try:
            yield f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
            if snapshot["status"] in ("completed", "failed"):
                return
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("status") in ("completed", "failed"):
                    break
        finally:
            runner.unsubscribe(task_id, queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{task_id}/retry", response_model=TaskOut, status_code=202)
def retry_task(task_id: str, db: Session = Depends(get_db)) -> TaskOut:
    task = task_repository.get_task(db, task_id)
    if task is None:
        raise NotFoundError("任务不存在")
    if task.status in ("pending", "running"):
        raise ConflictError("任务正在执行中，无需重试")
    document = db.get(Document, task.document_id)
    if document is None:
        raise NotFoundError("文档不存在，无法重试")

    document.status = "processing"
    db.commit()
    new_task = task_repository.create_task(db, document_id=document.id)
    new_task.retry_count = task.retry_count + 1
    db.commit()
    runner.submit(new_task.id, document.id)

    item = TaskOut.model_validate(new_task)
    item.document_name = document.original_name
    return item


@router.delete("/{task_id}", status_code=204)
def cancel_task(task_id: str, db: Session = Depends(get_db)) -> Response:
    task = task_repository.get_task(db, task_id)
    if task is None:
        raise NotFoundError("任务不存在")
    if task.status == "running":
        raise HTTPException(status_code=409, detail="任务正在执行，暂时无法删除")
    db.delete(task)
    db.commit()
    return Response(status_code=204)

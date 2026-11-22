"""RAG 智能问答接口。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import NotFoundError
from app.repositories import chat_repository
from app.schemas import (
    ChatAskRequest,
    ChatMessageOut,
    ChatSessionCreateRequest,
    ChatSessionDetailOut,
    ChatSessionListOut,
    ChatSessionOut,
)
from app.services import chat_service
from app.services.index_service import require_index_ready

router = APIRouter(prefix="/chat", tags=["chat"])


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/sessions", response_model=ChatSessionOut, status_code=201)
def create_session(
    payload: ChatSessionCreateRequest | None = None, db: Session = Depends(get_db)
) -> ChatSessionOut:
    title = payload.title.strip() if payload and payload.title.strip() else "新会话"
    session = chat_repository.create_session(db, title=title)
    return ChatSessionOut.model_validate(session)


@router.get("/sessions", response_model=ChatSessionListOut)
def list_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> ChatSessionListOut:
    items, total = chat_repository.list_sessions(db, page=page, page_size=page_size)
    return ChatSessionListOut(
        items=[ChatSessionOut.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/sessions/{session_id}", response_model=ChatSessionDetailOut)
def get_session(session_id: str, db: Session = Depends(get_db)) -> ChatSessionDetailOut:
    session = chat_repository.get_session(db, session_id)
    if session is None:
        raise NotFoundError("问答会话不存在")
    messages = chat_repository.list_messages(db, session_id)
    return ChatSessionDetailOut(
        session=ChatSessionOut.model_validate(session),
        messages=[ChatMessageOut.model_validate(item) for item in messages],
    )


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str, db: Session = Depends(get_db)) -> Response:
    session = chat_repository.get_session(db, session_id)
    if session is None:
        raise NotFoundError("问答会话不存在")
    chat_repository.delete_session(db, session)
    return Response(status_code=204)


@router.post("/sessions/{session_id}/messages")
async def create_message(
    session_id: str,
    payload: ChatAskRequest,
    db: Session = Depends(get_db),
):
    session = chat_repository.get_session(db, session_id)
    if session is None:
        raise NotFoundError("问答会话不存在")
    if not payload.stream:
        return await chat_service.answer_once(
            db, session_id, payload.question, top_k=payload.top_k
        )

    # 流式开始前先做门禁，让前端能拿到 409/502 而不是一个只有错误事件的 200 流
    require_index_ready(db)

    async def event_stream():
        async for item in chat_service.stream_answer(
            session_id, payload.question, top_k=payload.top_k
        ):
            yield _sse(item["event"], item["data"])

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = ["router"]

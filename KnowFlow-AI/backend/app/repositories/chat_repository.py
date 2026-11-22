"""问答会话与消息的数据访问。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from app.models import ChatMessage, ChatSession


def create_session(db, title: str = "新会话") -> ChatSession:
    session = ChatSession(title=title)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session(db, session_id: str) -> ChatSession | None:
    return db.get(ChatSession, session_id)


def list_sessions(db, *, page: int = 1, page_size: int = 20) -> tuple[list[ChatSession], int]:
    total = db.scalar(select(func.count()).select_from(ChatSession)) or 0
    rows = db.scalars(
        select(ChatSession)
        .order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(rows), int(total)


def delete_session(db, session: ChatSession) -> None:
    db.query(ChatMessage).filter(ChatMessage.session_id == session.id).delete()
    db.delete(session)
    db.commit()


def add_message(
    db,
    *,
    session: ChatSession,
    role: str,
    content: str,
    citations: list[dict] | None = None,
) -> ChatMessage:
    message = ChatMessage(
        session_id=session.id,
        role=role,
        content=content,
        citations=citations,
    )
    db.add(message)
    session.updated_at = datetime.now()
    if role == "user" and session.title == "新会话":
        session.title = content.strip()[:30] or "新会话"
    db.commit()
    db.refresh(message)
    return message


def list_messages(db, session_id: str) -> list[ChatMessage]:
    return list(
        db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at, ChatMessage.id)
        ).all()
    )

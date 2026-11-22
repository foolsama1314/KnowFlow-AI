"""资料列表索引状态与索引概览测试。"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import documents as documents_api
from app.models import Base, Document, DocumentChunk, ProcessingTask
from app.schemas import VectorIndexStatusOut


def index_status(status: str, chunk_count: int = 1) -> VectorIndexStatusOut:
    return VectorIndexStatusOut(
        provider="openai_compatible",
        model="test-model",
        dimension=8,
        status=status,
        chunk_count=chunk_count,
        updated_at=datetime.now(),
    )


@pytest.fixture
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'docs.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    yield session
    session.close()
    engine.dispose()


def add_document(db, name: str, status: str) -> Document:
    document = Document(
        name=name,
        original_name=name,
        file_type="pdf",
        file_size=10,
        file_path=f"/tmp/{name}",
        file_hash=name,
        status=status,
        page_count=1,
        chunk_count=1,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def test_document_index_status_derivation(db, monkeypatch):
    completed = add_document(db, "完成.pdf", "completed")
    failed = add_document(db, "失败.pdf", "failed")
    running = add_document(db, "处理中.pdf", "processing")
    db.add(
        ProcessingTask(
            document_id=failed.id,
            task_type="parse",
            status="failed",
            progress=30,
            current_step="执行失败",
            error_message="解析失败：文件损坏",
        )
    )
    db.commit()

    monkeypatch.setattr(
        documents_api, "get_index_status", lambda _db: index_status("completed")
    )
    items = documents_api._decorate_documents(db, [completed, failed, running])
    by_name = {item.original_name: item for item in items}

    assert by_name["完成.pdf"].index_status == "indexed"
    assert by_name["失败.pdf"].index_status == "failed"
    assert by_name["失败.pdf"].last_error == "解析失败：文件损坏"
    assert by_name["处理中.pdf"].index_status == "processing"

    monkeypatch.setattr(
        documents_api, "get_index_status", lambda _db: index_status("requires_reindex")
    )
    items = documents_api._decorate_documents(db, [completed])
    assert items[0].index_status == "not_indexed"


def test_index_summary_counts(db, monkeypatch):
    completed = add_document(db, "完成.pdf", "completed")
    add_document(db, "失败.pdf", "failed")
    db.add(
        DocumentChunk(
            document_id=completed.id,
            content="内容",
            chunk_index=0,
            page_from=1,
            page_to=1,
            token_count=5,
            qdrant_point_id="",
        )
    )
    db.add(
        ProcessingTask(
            document_id=completed.id,
            task_type="parse",
            status="running",
            progress=50,
            current_step="向量化",
        )
    )
    db.commit()

    monkeypatch.setattr(
        documents_api, "get_index_status", lambda _db: index_status("completed")
    )
    monkeypatch.setattr(documents_api.vector_store, "count", lambda: 1)

    summary = documents_api.index_summary(db)
    assert summary.total_documents == 2
    assert summary.completed_documents == 1
    assert summary.failed_documents == 1
    assert summary.pending_index == 0
    assert summary.total_chunks == 1
    assert summary.indexed_chunks == 1
    assert summary.running_tasks == 1

    monkeypatch.setattr(
        documents_api, "get_index_status", lambda _db: index_status("requires_reindex")
    )
    summary = documents_api.index_summary(db)
    assert summary.pending_index == 1
    assert summary.indexed_chunks == 0

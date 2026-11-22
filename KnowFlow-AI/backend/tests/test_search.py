"""使用真实 SQLite 与 Qdrant 本地引擎验证索引和检索行为。"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ai.vector_store import vector_store
from app.core.errors import AIProviderError, ProcessingError
from app.models import Base, Document, DocumentChunk, ProcessingTask, VectorIndexState
from app.schemas import SearchRequest
from app.services import document_service, index_service, pipeline, search_service


vector_store_module = importlib.import_module("app.ai.vector_store")


class DeterministicEmbedding:
    """测试适配器：只替代外部模型，检索与相似度计算由真实 Qdrant 执行。"""

    dimension = 3

    def _vector(self, text: str) -> list[float]:
        if "幻觉" in text:
            return [1.0, 0.0, 0.0]
        if "烹饪" in text:
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class FailingEmbedding(DeterministicEmbedding):
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise AIProviderError("测试：向量服务中断")


@pytest.fixture
def search_env(tmp_path, monkeypatch):
    vector_store.close()
    settings = SimpleNamespace(
        qdrant_url="",
        qdrant_collection="document_chunks",
        qdrant_local_path=tmp_path / "qdrant",
        embedding_provider="openai_compatible",
        embedding_base_url="https://embedding.example/v1",
        embedding_model="bge-m3-test",
        embedding_dim=3,
        embedding_configured=True,
        data_dir=tmp_path,
        chunk_size=200,
        chunk_overlap=20,
    )
    monkeypatch.setattr(vector_store_module, "get_settings", lambda: settings)
    monkeypatch.setattr(index_service, "get_settings", lambda: settings)
    monkeypatch.setattr(document_service, "get_settings", lambda: settings)

    engine = create_engine(f"sqlite:///{(tmp_path / 'search.db').as_posix()}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield settings, session, tmp_path
    session.close()
    vector_store.close()
    engine.dispose()


def add_document(db, tmp_path: Path, content: str, page: int = 2):
    document_id = str(uuid4())
    relative_path = f"uploads/{document_id}.txt"
    target = tmp_path / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    document = Document(
        id=document_id,
        name="研究论文",
        original_name="研究论文.pdf",
        file_type="pdf",
        file_size=target.stat().st_size,
        file_path=relative_path,
        file_hash=uuid4().hex,
        status="completed",
        page_count=3,
        chunk_count=1,
    )
    chunk = DocumentChunk(
        id=str(uuid4()),
        document_id=document_id,
        content=content,
        chunk_index=0,
        page_from=page,
        page_to=page,
        token_count=len(content),
        qdrant_point_id="",
    )
    chunk.qdrant_point_id = chunk.id
    db.add_all([document, chunk])
    db.commit()
    return document, chunk


async def test_qdrant_search_source_page_persistence_and_delete(search_env, monkeypatch):
    settings, db, tmp_path = search_env
    monkeypatch.setattr(search_service, "get_embedding", DeterministicEmbedding)
    document, chunk = add_document(db, tmp_path, "大语言模型幻觉的检测与缓解", page=7)
    other, _chunk = add_document(db, tmp_path, "家常烹饪与膳食搭配", page=1)

    rebuilt = await search_service.reindex(db)
    assert rebuilt["chunks"] == 2

    response = await search_service.search(db, SearchRequest(query="幻觉有哪些风险", top_k=5))
    assert response.retrieval_mode == "semantic"
    assert response.embedding_model == settings.embedding_model
    assert response.index_status.status == "completed"
    assert response.results[0].document_id == document.id
    assert response.results[0].chunk_id == chunk.id
    assert response.results[0].document_name == "研究论文.pdf"
    assert response.results[0].page_from == 7
    assert "幻觉" in response.results[0].content
    assert 0 < response.results[0].score <= 1

    # 关闭并重开本地 Qdrant，别名、向量及检索结果仍然可用。
    vector_store.reset()
    persisted = await search_service.search(db, SearchRequest(query="幻觉", top_k=1))
    assert persisted.results[0].chunk_id == chunk.id

    document_service.delete_document(db, document.id)
    document_service.delete_document(db, other.id)
    assert db.query(DocumentChunk).count() == 0
    assert vector_store.count() == 0
    status = index_service.get_index_status(db)
    assert status.status == "completed"
    assert status.chunk_count == 0
    assert not (tmp_path / document.file_path).exists()


async def test_failed_rebuild_preserves_active_index_and_blocks_inconsistent_search(
    search_env, monkeypatch
):
    _settings, db, tmp_path = search_env
    monkeypatch.setattr(search_service, "get_embedding", DeterministicEmbedding)
    document, _chunk = add_document(db, tmp_path, "幻觉评估基准")
    await search_service.reindex(db)
    old_collection = next(
        item
        for item in vector_store.client().get_aliases().aliases
        if item.alias_name == vector_store.collection
    ).collection_name

    monkeypatch.setattr(search_service, "get_embedding", FailingEmbedding)
    with pytest.raises(AIProviderError, match="向量服务中断"):
        await search_service.reindex(db)

    state = db.get(VectorIndexState, "default")
    assert state.status == "failed"
    assert vector_store.count() == 1
    current_collection = next(
        item
        for item in vector_store.client().get_aliases().aliases
        if item.alias_name == vector_store.collection
    ).collection_name
    assert current_collection == old_collection
    assert {item.name for item in vector_store.client().get_collections().collections} == {
        old_collection
    }
    with pytest.raises(ProcessingError, match="向量索引当前不可用"):
        await search_service.search(db, SearchRequest(query="幻觉"))

    monkeypatch.setattr(search_service, "get_embedding", DeterministicEmbedding)
    await search_service.reindex(db)
    assert index_service.get_index_status(db).status == "completed"
    assert document.id == (
        await search_service.search(db, SearchRequest(query="幻觉"))
    ).results[0].document_id


async def test_model_change_and_legacy_vectors_require_reindex(search_env, monkeypatch):
    settings, db, tmp_path = search_env
    monkeypatch.setattr(search_service, "get_embedding", DeterministicEmbedding)
    add_document(db, tmp_path, "检索增强生成")
    await search_service.reindex(db)

    settings.embedding_model = "another-model"
    status = index_service.get_index_status(db)
    assert status.status == "requires_reindex"
    with pytest.raises(ProcessingError, match="重建索引"):
        await search_service.search(db, SearchRequest(query="检索增强"))


async def test_full_document_pipeline_builds_searchable_real_vectors(search_env, monkeypatch):
    settings, db, tmp_path = search_env
    document_id = str(uuid4())
    relative_path = f"uploads/{document_id}.txt"
    source = tmp_path / relative_path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("RAG 系统需要评估大语言模型幻觉，并给出可追溯的原文证据。" * 8, encoding="utf-8")
    document = Document(
        id=document_id,
        name="完整流程",
        original_name="完整流程.txt",
        file_type="txt",
        file_size=source.stat().st_size,
        file_path=relative_path,
        file_hash=uuid4().hex,
        status="uploaded",
    )
    task = ProcessingTask(document_id=document_id)
    db.add_all([document, task])
    db.commit()
    task_id = task.id

    session_factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", session_factory)
    monkeypatch.setattr(pipeline, "get_settings", lambda: settings)
    monkeypatch.setattr(pipeline, "get_embedding", DeterministicEmbedding)
    monkeypatch.setattr(search_service, "get_embedding", DeterministicEmbedding)

    await pipeline.run_pipeline(task_id, document_id)
    db.expire_all()

    assert db.get(Document, document_id).status == "completed"
    assert db.get(ProcessingTask, task_id).status == "completed"
    assert db.query(DocumentChunk).filter_by(document_id=document_id).count() > 0
    assert index_service.get_index_status(db).status == "completed"
    response = await search_service.search(db, SearchRequest(query="幻觉", top_k=3))
    assert response.results
    assert all(hit.document_id == document_id for hit in response.results)


def test_unregistered_legacy_vectors_are_not_reported_as_semantic(search_env):
    _settings, db, _tmp_path = search_env
    vector_store.ensure_collection(3)
    vector_store.upsert(
        [
            {
                "id": str(uuid4()),
                "vector": [1.0, 0.0, 0.0],
                "payload": {"chunk_id": "legacy"},
            }
        ]
    )

    status = index_service.get_index_status(db)

    assert status.status == "requires_reindex"
    assert status.chunk_count == 1
    with pytest.raises(ProcessingError):
        index_service.require_index_ready(db)

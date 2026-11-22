"""RAG 问答行为测试：真实 SQLite + 可编程 LLM 适配器（只替代外部网络）。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.errors import AIProviderError, NotFoundError, ProcessingError
from app.models import Base, Document, DocumentChunk
from app.repositories import chat_repository
from app.schemas import SearchHit
from app.services import chat_service, rag_service


class FakeLLM:
    def __init__(self, reply: str = "答案 [1]", parts: list[str] | None = None) -> None:
        self.reply = reply
        self.parts = parts if parts is not None else [reply]
        self.calls: list[list[dict[str, str]]] = []

    async def chat(self, messages, **kwargs):
        self.calls.append(messages)
        return self.reply

    async def chat_stream(self, messages, **kwargs):
        self.calls.append(messages)
        for part in self.parts:
            yield part


class FailingLLM:
    def __init__(self, message: str = "模型服务返回错误：401 Unauthorized") -> None:
        self.message = message
        self.calls = 0

    async def chat(self, messages, **kwargs):
        self.calls += 1
        raise AIProviderError(self.message)

    async def chat_stream(self, messages, **kwargs):
        self.calls += 1
        raise AIProviderError(self.message)
        yield ""  # pragma: no cover


@pytest.fixture
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'chat.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    yield session
    session.close()
    engine.dispose()


def make_document(db, name: str = "咖啡烘焙基础.pdf", status: str = "completed") -> Document:
    document = Document(
        name=name,
        original_name=name,
        file_type="pdf",
        file_size=1024,
        file_path=f"/tmp/{name}",
        file_hash=name,
        status=status,
        page_count=3,
        chunk_count=1,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def make_chunk(
    db, document: Document, content: str, *, page: int = 2, chunk_id: str | None = None
) -> DocumentChunk:
    chunk = DocumentChunk(
        document_id=document.id,
        content=content,
        chunk_index=0,
        page_from=page,
        page_to=page,
        token_count=10,
        qdrant_point_id="",
    )
    if chunk_id:
        chunk.id = chunk_id
    db.add(chunk)
    db.commit()
    db.refresh(chunk)
    return chunk


def hit_for(chunk: DocumentChunk, document: Document, score: float = 0.8) -> SearchHit:
    return SearchHit(
        chunk_id=chunk.id,
        document_id=document.id,
        document_name=document.name,
        file_type=document.file_type,
        page_from=chunk.page_from,
        page_to=chunk.page_to,
        content=chunk.content,
        score=score,
    )


@pytest.fixture
def fake_settings(monkeypatch):
    settings = SimpleNamespace(
        llm_configured=True,
        llm_model="fake-llm",
        rag_top_k=5,
        rag_min_score=0.35,
        rag_context_chars=6000,
    )
    monkeypatch.setattr(chat_service, "get_settings", lambda: settings)
    monkeypatch.setattr(rag_service, "get_settings", lambda: settings)
    return settings


def stub_search(monkeypatch, hits: list[SearchHit]):
    calls: list[str] = []

    async def _search(_db, request):
        calls.append(request.query)
        return SimpleNamespace(results=hits)

    monkeypatch.setattr(rag_service.search_service, "search", _search)
    return calls


def use_llm(monkeypatch, llm) -> None:
    monkeypatch.setattr(chat_service, "get_llm", lambda: llm)


async def test_answer_with_real_citation(db, fake_settings, monkeypatch):
    document = make_document(db)
    chunk = make_chunk(db, document, "一爆发生在约 196 摄氏度，豆内压力释放产生爆裂声。")
    stub_search(monkeypatch, [hit_for(chunk, document, 0.82)])
    llm = FakeLLM("一爆出现在约 196 摄氏度，是豆内二氧化碳压力释放造成的 [1]。")
    use_llm(monkeypatch, llm)

    session = chat_repository.create_session(db)
    result = await chat_service.answer_once(db, session.id, "为什么咖啡豆会爆裂？")

    assert result.refusal is False
    assert len(result.citations) == 1
    citation = result.citations[0]
    assert citation.cited is True
    assert citation.chunk_id == chunk.id
    assert citation.document_id == document.id
    assert citation.page_from == 2
    assert "[1]" in result.message.content
    assert len(llm.calls) == 1


async def test_multi_document_answer(db, fake_settings, monkeypatch):
    doc_a = make_document(db, "咖啡烘焙基础.pdf")
    doc_b = make_document(db, "城市地铁行车调度.pdf")
    chunk_a = make_chunk(db, doc_a, "一爆约在一百九十六摄氏度发生。", page=2)
    chunk_b = make_chunk(db, doc_b, "夜间检修天窗从零点三十分到三点三十分。", page=3)
    stub_search(monkeypatch, [hit_for(chunk_a, doc_a, 0.8), hit_for(chunk_b, doc_b, 0.7)])
    use_llm(monkeypatch, FakeLLM("爆裂与检修分别见资料 [1] 和 [2]。"))

    session = chat_repository.create_session(db)
    result = await chat_service.answer_once(db, session.id, "把烘焙爆裂和地铁夜间检修一起说说")

    assert len(result.citations) == 2
    assert {c.document_name for c in result.citations} == {"咖啡烘焙基础.pdf", "城市地铁行车调度.pdf"}
    assert all(c.cited for c in result.citations)


async def test_refusal_when_no_hits(db, fake_settings, monkeypatch):
    stub_search(monkeypatch, [])
    llm = FakeLLM()
    use_llm(monkeypatch, llm)

    session = chat_repository.create_session(db)
    result = await chat_service.answer_once(db, session.id, "量子计算机怎么校准？")

    assert result.refusal is True
    assert result.citations == []
    assert result.message.content == chat_service.REFUSAL_TEXT
    assert llm.calls == []


async def test_refusal_when_score_below_threshold(db, fake_settings, monkeypatch):
    document = make_document(db)
    chunk = make_chunk(db, document, "无关内容")
    stub_search(monkeypatch, [hit_for(chunk, document, 0.12)])
    llm = FakeLLM()
    use_llm(monkeypatch, llm)

    session = chat_repository.create_session(db)
    result = await chat_service.answer_once(db, session.id, "完全无关的问题")

    assert result.refusal is True
    assert llm.calls == []


async def test_bad_api_key_surfaces_error(db, fake_settings, monkeypatch):
    document = make_document(db)
    chunk = make_chunk(db, document, "内容")
    stub_search(monkeypatch, [hit_for(chunk, document, 0.9)])
    use_llm(monkeypatch, FailingLLM("模型服务返回错误：401 Unauthorized"))

    session = chat_repository.create_session(db)
    with pytest.raises(AIProviderError):
        await chat_service.answer_once(db, session.id, "问题")


async def test_llm_error_emits_stream_error_event(db, fake_settings, monkeypatch):
    document = make_document(db)
    chunk = make_chunk(db, document, "内容")
    stub_search(monkeypatch, [hit_for(chunk, document, 0.9)])
    use_llm(monkeypatch, FailingLLM("模型流式服务连接失败：timed out"))
    monkeypatch.setattr(
        chat_service, "SessionLocal", sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    )

    session = chat_repository.create_session(db)
    events = [item async for item in chat_service.stream_answer(session.id, "问题")]

    assert events[-1]["event"] == "error"
    assert "timed out" in events[-1]["data"]["message"]


async def test_embedding_unconfigured_rejects(db, fake_settings, monkeypatch):
    async def _search(_db, _request):
        raise AIProviderError("尚未配置 Embedding 向量服务。")

    monkeypatch.setattr(rag_service.search_service, "search", _search)
    use_llm(monkeypatch, FakeLLM())

    session = chat_repository.create_session(db)
    with pytest.raises(AIProviderError):
        await chat_service.answer_once(db, session.id, "问题")


async def test_index_not_ready_rejects(db, fake_settings, monkeypatch):
    async def _search(_db, _request):
        raise ProcessingError("向量索引尚未就绪，请先重建索引")

    monkeypatch.setattr(rag_service.search_service, "search", _search)
    use_llm(monkeypatch, FakeLLM())

    session = chat_repository.create_session(db)
    with pytest.raises(ProcessingError):
        await chat_service.answer_once(db, session.id, "问题")


async def test_out_of_range_citation_is_dropped(db, fake_settings, monkeypatch):
    document = make_document(db)
    chunk = make_chunk(db, document, "内容")
    stub_search(monkeypatch, [hit_for(chunk, document, 0.9)])
    use_llm(monkeypatch, FakeLLM("这是编造的引用 [9]，还有真实引用 [1]。"))

    session = chat_repository.create_session(db)
    result = await chat_service.answer_once(db, session.id, "问题")

    assert "[9]" not in result.message.content
    assert "[1]" in result.message.content
    assert [c.cited for c in result.citations] == [True]


async def test_stale_chunk_is_filtered(db, fake_settings, monkeypatch):
    document = make_document(db)
    chunk = make_chunk(db, document, "真实内容")
    ghost = SearchHit(
        chunk_id="missing-chunk",
        document_id=document.id,
        document_name=document.name,
        file_type="pdf",
        page_from=2,
        page_to=2,
        content="已删除的文本块",
        score=0.95,
    )
    stub_search(monkeypatch, [ghost, hit_for(chunk, document, 0.8)])
    use_llm(monkeypatch, FakeLLM("回答 [1]"))

    session = chat_repository.create_session(db)
    result = await chat_service.answer_once(db, session.id, "问题")

    assert len(result.citations) == 1
    assert result.citations[0].chunk_id == chunk.id


async def test_history_roundtrip_and_persistence(tmp_path, fake_settings, monkeypatch):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'persist.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = factory()

    document = make_document(db)
    chunk = make_chunk(db, document, "内容")
    stub_search(monkeypatch, [hit_for(chunk, document, 0.9)])
    use_llm(monkeypatch, FakeLLM("回答 [1]"))

    session = chat_repository.create_session(db)
    await chat_service.answer_once(db, session.id, "第一个问题")
    db.close()

    reopened = factory()
    detail = chat_repository.get_session(reopened, session.id)
    assert detail is not None
    assert detail.title == "第一个问题"
    messages = chat_repository.list_messages(reopened, session.id)
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[1].citations and messages[1].citations[0]["chunk_id"] == chunk.id

    items, total = chat_repository.list_sessions(reopened)
    assert total == 1 and items[0].id == session.id

    chat_repository.delete_session(reopened, detail)
    assert chat_repository.get_session(reopened, session.id) is None
    assert chat_repository.list_messages(reopened, session.id) == []
    reopened.close()
    engine.dispose()


async def test_stream_interrupted_saves_partial(db, fake_settings, monkeypatch):
    document = make_document(db)
    chunk = make_chunk(db, document, "内容")
    stub_search(monkeypatch, [hit_for(chunk, document, 0.9)])
    use_llm(monkeypatch, FakeLLM(parts=["第一段", "第二段", "第三段"]))
    monkeypatch.setattr(
        chat_service, "SessionLocal", sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    )

    session = chat_repository.create_session(db)
    generator = chat_service.stream_answer(session.id, "问题")
    seen: list[str] = []
    async for item in generator:
        if item["event"] == "delta":
            seen.append(item["data"]["text"])
            if len(seen) == 1:
                await generator.aclose()
                break

    assert seen == ["第一段"]

    messages = chat_repository.list_messages(db, session.id)
    assert [m.role for m in messages] == ["user", "assistant"]
    assert "第一段" in messages[1].content
    assert "生成已中断" in messages[1].content


async def test_missing_session_rejected(db, fake_settings):
    with pytest.raises(NotFoundError):
        await chat_service.answer_once(db, "not-exist", "问题")

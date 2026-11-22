"""多文档分析与智能总结测试：真实 SQLite，只替换外部模型调用与向量检索。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.errors import AIProviderError, AppError
from app.models import Base, Document, DocumentChunk
from app.schemas import AnalysisRequest, SearchHit
from app.services import analysis_service


class FakeLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[list[dict[str, str]]] = []

    async def chat(self, messages, **kwargs):
        self.calls.append(messages)
        return self.reply


@pytest.fixture
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'analysis.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    yield session
    session.close()
    engine.dispose()


def make_document(db, name: str, status: str = "completed") -> Document:
    document = Document(
        name=name,
        original_name=name,
        file_type="pdf",
        file_size=1024,
        file_path=f"/tmp/{name}",
        file_hash=name,
        status=status,
        page_count=2,
        chunk_count=1,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def make_hit(db, document: Document, content: str, page: int = 1, score: float = 0.8) -> SearchHit:
    chunk = DocumentChunk(
        document_id=document.id,
        content=content,
        chunk_index=0,
        page_from=page,
        page_to=page,
        token_count=10,
        qdrant_point_id="",
    )
    db.add(chunk)
    db.commit()
    db.refresh(chunk)
    return SearchHit(
        chunk_id=chunk.id,
        document_id=document.id,
        document_name=document.name,
        file_type="pdf",
        page_from=page,
        page_to=page,
        content=content,
        score=score,
    )


@pytest.fixture
def settings(monkeypatch, tmp_path):
    value = SimpleNamespace(
        llm_configured=True,
        llm_model="fake-llm",
        rag_top_k=5,
        rag_min_score=0.35,
        rag_context_chars=4000,
        export_dir=tmp_path / "exports",
    )
    monkeypatch.setattr(analysis_service, "get_settings", lambda: value)
    monkeypatch.setattr(analysis_service.rag_service, "get_settings", lambda: value)
    return value


def stub_search(monkeypatch, hits: list[SearchHit]):
    calls: list[list[str]] = []

    async def _search(_db, request):
        calls.append(list(request.filters.document_ids))
        filtered = [hit for hit in hits if hit.document_id in request.filters.document_ids]
        return SimpleNamespace(results=filtered[: request.top_k])

    monkeypatch.setattr(analysis_service.rag_service.search_service, "search", _search)
    return calls


async def test_compare_builds_sections_and_citations(db, settings, monkeypatch):
    doc_a = make_document(db, "方法论A.pdf")
    doc_b = make_document(db, "方法论B.pdf")
    hit_a = make_hit(db, doc_a, "A 强调先做用户访谈，再迭代原型。", page=2)
    hit_b = make_hit(db, doc_b, "B 强调数据驱动，小步快跑。", page=5)
    stub_search(monkeypatch, [hit_a, hit_b])
    llm = FakeLLM(
        "## 共同观点\n两者都强调迭代 [1][2]。\n"
        "## 差异分析\nA 重访谈，B 重数据 [2]。\n"
        "## 关键知识点\n迭代与验证 [1]。"
    )
    monkeypatch.setattr(analysis_service, "get_llm", lambda: llm)

    result = await analysis_service.analyze(
        db,
        AnalysisRequest(
            mode="compare", document_ids=[doc_a.id, doc_b.id], topic="产品方法论", top_k=1
        ),
    )

    assert result.refusal is False
    assert [section.title for section in result.sections] == ["共同观点", "差异分析", "关键知识点"]
    assert result.retrieval_count == 2
    assert {c.document_name for c in result.citations} == {"方法论A.pdf", "方法论B.pdf"}
    assert all(c.cited for c in result.citations)
    assert len(llm.calls) == 1


async def test_out_of_range_citation_removed(db, settings, monkeypatch):
    doc = make_document(db, "单篇.pdf")
    hit = make_hit(db, doc, "核心内容是需求验证。", page=3)
    stub_search(monkeypatch, [hit])
    monkeypatch.setattr(
        analysis_service,
        "get_llm",
        lambda: FakeLLM("## 核心观点\n需求验证最重要 [1]，编造引用 [9]。"),
    )

    result = await analysis_service.analyze(
        db,
        AnalysisRequest(mode="summary", document_ids=[doc.id], topic="需求验证", top_k=1),
    )

    text = "".join(section.content for section in result.sections)
    assert "[9]" not in text
    assert "[1]" in text
    assert result.citations[0].cited is True


async def test_refusal_without_hits_does_not_call_llm(db, settings, monkeypatch):
    doc = make_document(db, "空检索.pdf")
    stub_search(monkeypatch, [])
    llm = FakeLLM("不应该被调用")
    monkeypatch.setattr(analysis_service, "get_llm", lambda: llm)

    result = await analysis_service.analyze(
        db,
        AnalysisRequest(mode="compare", document_ids=[doc.id], topic="不存在的内容"),
    )

    assert result.refusal is True
    assert result.citations == []
    assert result.sections == []
    assert llm.calls == []


async def test_low_score_refused(db, settings, monkeypatch):
    doc = make_document(db, "弱相关.pdf")
    hit = make_hit(db, doc, "弱相关内容", score=0.2)
    stub_search(monkeypatch, [hit])
    llm = FakeLLM("不应该被调用")
    monkeypatch.setattr(analysis_service, "get_llm", lambda: llm)

    result = await analysis_service.analyze(
        db, AnalysisRequest(mode="compare", document_ids=[doc.id], topic="无关问题")
    )

    assert result.refusal is True
    assert "相关性不足" in result.message
    assert llm.calls == []


async def test_missing_sections_are_filled(db, settings, monkeypatch):
    doc = make_document(db, "总结.pdf")
    hit = make_hit(db, doc, "资料内容", page=2)
    stub_search(monkeypatch, [hit])
    monkeypatch.setattr(analysis_service, "get_llm", lambda: FakeLLM("## 核心观点\n只有一个观点 [1]。"))

    result = await analysis_service.analyze(
        db,
        AnalysisRequest(mode="summary", document_ids=[doc.id], topic="总结", top_k=1),
    )

    titles = [section.title for section in result.sections]
    assert titles[:4] == ["核心观点", "关键概念", "重要结论", "待研究问题"]
    assert result.sections[1].content == "资料不足，无法判断。"


async def test_llm_unconfigured_rejected(db, settings, monkeypatch):
    doc = make_document(db, "资料.pdf")
    monkeypatch.setattr(
        analysis_service, "get_settings", lambda: SimpleNamespace(llm_configured=False)
    )
    with pytest.raises(AIProviderError):
        await analysis_service.analyze(
            db, AnalysisRequest(mode="compare", document_ids=[doc.id], topic="主题")
        )


async def test_incomplete_document_rejected(db, settings):
    doc = make_document(db, "未完成.pdf", status="processing")
    with pytest.raises(AppError):
        await analysis_service.analyze(
            db, AnalysisRequest(mode="compare", document_ids=[doc.id], topic="主题")
        )

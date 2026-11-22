"""研究报告生成与导出测试：真实 SQLite + 临时导出目录。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from docx import Document as DocxDocument
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.errors import AIProviderError, NotFoundError
from app.models import Base, Document, DocumentChunk
from app.schemas import ReportRequest, SearchHit
from app.services import report_service


class FakeLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls = 0

    async def chat(self, messages, **kwargs):
        self.calls += 1
        return self.reply


@pytest.fixture
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'report.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    yield session
    session.close()
    engine.dispose()


def make_document(db, name: str) -> Document:
    document = Document(
        name=name,
        original_name=name,
        file_type="pdf",
        file_size=2048,
        file_path=f"/tmp/{name}",
        file_hash=name,
        status="completed",
        page_count=5,
        chunk_count=1,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def make_hit(db, document: Document, content: str, page: int, score: float = 0.82) -> SearchHit:
    chunk = DocumentChunk(
        document_id=document.id,
        content=content,
        chunk_index=0,
        page_from=page,
        page_to=page,
        token_count=12,
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
        rag_context_chars=6000,
        export_dir=tmp_path / "exports",
    )
    monkeypatch.setattr(report_service, "get_settings", lambda: value)
    monkeypatch.setattr(report_service.rag_service, "get_settings", lambda: value)
    return value


def stub_search(monkeypatch, hits: list[SearchHit]):
    async def _search(_db, request):
        filtered = [hit for hit in hits if hit.document_id in request.filters.document_ids]
        return SimpleNamespace(results=filtered[: request.top_k])

    monkeypatch.setattr(report_service.rag_service.search_service, "search", _search)


REPORT_TEXT = (
    "## 研究背景\n知识管理正在从文档存储走向智能检索 [1]。\n"
    "## 核心内容\n真实检索与大模型结合是主流路径 [1][2]。\n"
    "## 关键发现\n引用溯源是可信度的关键 [2]，编造引用 [9] 应被剔除。\n"
    "## 综合分析\n两类资料互补 [1]。\n"
    "## 结论\n建议先小范围验证 [2]。"
)


async def test_generate_report_writes_files(db, settings, monkeypatch):
    doc_a = make_document(db, "行业报告.pdf")
    doc_b = make_document(db, "技术白皮书.pdf")
    hits = [
        make_hit(db, doc_a, "知识管理正在走向智能检索。", page=2),
        make_hit(db, doc_b, "检索增强生成需要引用溯源。", page=7),
    ]
    stub_search(monkeypatch, hits)
    llm = FakeLLM(REPORT_TEXT)
    monkeypatch.setattr(report_service, "get_llm", lambda: llm)

    result = await report_service.generate(
        db, ReportRequest(topic="知识管理演进", document_ids=[doc_a.id, doc_b.id], top_k=1)
    )

    assert result.report_id
    assert result.title == "知识管理演进 研究报告"
    assert [section.title for section in result.sections] == [
        "研究背景",
        "核心内容",
        "关键发现",
        "综合分析",
        "结论",
    ]
    assert "[9]" not in result.markdown
    assert "参考资料" in result.markdown
    assert {c.document_name for c in result.citations} == {"行业报告.pdf", "技术白皮书.pdf"}
    assert all(c.cited for c in result.citations)
    assert llm.calls == 1

    directory = settings.export_dir / "reports"
    for suffix in ("json", "md", "docx"):
        assert (directory / f"{result.report_id}.{suffix}").is_file()

    document = DocxDocument(str(directory / f"{result.report_id}.docx"))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "知识管理演进 研究报告" in text
    assert "参考资料" in text
    assert "行业报告.pdf" in text

    summaries = report_service.list_reports()
    assert summaries and summaries[0].report_id == result.report_id
    assert summaries[0].citation_count == 2

    loaded = report_service.get_report(result.report_id)
    assert loaded.title == result.title
    assert report_service.download_path(result.report_id, "md").is_file()


async def test_report_refuses_without_hits(db, settings, monkeypatch):
    doc = make_document(db, "无关.pdf")
    stub_search(monkeypatch, [])
    llm = FakeLLM(REPORT_TEXT)
    monkeypatch.setattr(report_service, "get_llm", lambda: llm)

    result = await report_service.generate(
        db, ReportRequest(topic="完全无关的主题", document_ids=[doc.id])
    )

    assert result.refusal is True
    assert result.report_id == ""
    assert result.sections == []
    assert llm.calls == 0


async def test_report_requires_llm(db, settings, monkeypatch):
    doc = make_document(db, "资料.pdf")
    monkeypatch.setattr(
        report_service, "get_settings", lambda: SimpleNamespace(llm_configured=False)
    )
    with pytest.raises(AIProviderError):
        await report_service.generate(
            db, ReportRequest(topic="主题", document_ids=[doc.id])
        )


async def test_report_id_traversal_rejected(settings):
    with pytest.raises(NotFoundError):
        report_service.get_report("../settings")
    with pytest.raises(NotFoundError):
        report_service.download_path("../../etc/passwd", "md")

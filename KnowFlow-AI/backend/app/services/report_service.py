"""AI 研究报告：基于知识库检索生成结构化报告，并导出 Markdown / DOCX。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from docx import Document as DocxDocument

from app.ai.registry import get_llm
from app.core.config import get_settings
from app.core.errors import AIProviderError, NotFoundError, ProcessingError
from app.schemas import (
    ReportRequest,
    ReportResultOut,
    ReportSectionOut,
    ReportSummaryOut,
    SearchHit,
)
from app.services import rag_service
from app.services.analysis_service import _page_label, _validate_documents

logger = logging.getLogger(__name__)

REPORT_HEADINGS = ["研究背景", "核心内容", "关键发现", "综合分析", "结论"]

SYSTEM_PROMPT = (
    "你是知枢 AI 的研究报告撰写助手。你只能依据提供的知识库资料片段撰写报告。\n"
    "规则：\n"
    "0. 必须严格按用户指定的二级标题分节输出，不要增加或遗漏小节。\n"
    "1. 每个关键结论后用 [编号] 标注来源，编号只能来自资料前的方括号编号。\n"
    "2. 严禁编造文档名称、页码、数据或原文，也不要补充资料中没有的事实。\n"
    "3. 资料不足时明确写「资料不足，无法判断」，不要用常识猜测。\n"
    "4. 使用简体中文，结构清晰，观点与证据对应。"
)

_HEADING_PATTERN = re.compile(r"^#{2,4}\s*(.+?)\s*$", re.MULTILINE)
_REPORT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


def _reports_dir() -> Path:
    path = get_settings().export_dir / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _build_context(hits: list[SearchHit]) -> str:
    return "\n\n".join(
        f"[{index}] 《{hit.document_name}》{_page_label(hit)}\n{hit.content.strip()}"
        for index, hit in enumerate(hits, start=1)
    )


def _build_messages(topic: str, context_text: str) -> list[dict[str, str]]:
    outline = "\n".join(f"## {title}" for title in REPORT_HEADINGS)
    user_prompt = (
        f"研究主题：{topic}\n\n"
        f"请基于以下资料撰写一份研究报告，严格按下列小节输出（参考资料由系统自动生成，不要自行编写）：\n"
        f"{outline}\n\n资料片段：\n\n{context_text}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def _split_sections(text: str) -> list[ReportSectionOut]:
    matches = list(_HEADING_PATTERN.finditer(text))
    if not matches:
        return [ReportSectionOut(title="报告正文", content=text.strip())]
    sections: list[ReportSectionOut] = []
    for index, match in enumerate(matches):
        title = match.group(1).strip().strip("*# ").strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        if title:
            sections.append(
                ReportSectionOut(title=title, content=text[start:end].strip())
            )
    by_title = {section.title: section for section in sections}
    ordered = [
        by_title.pop(title, ReportSectionOut(title=title, content="资料不足，无法判断。"))
        for title in REPORT_HEADINGS
    ]
    ordered.extend(by_title.values())
    return ordered


def _reference_lines(citations) -> list[str]:
    cited = [item for item in citations if item.cited]
    if not cited:
        return ["本次生成未引用具体资料，请谨慎参考。"]
    return [f"{index}. 《{item.document_name}》 {_page_label_hit(item)}" for index, item in enumerate(cited, start=1)]


def _page_label_hit(item) -> str:
    if item.page_from is None:
        return "全文"
    if item.page_from == item.page_to:
        return f"第 {item.page_from} 页"
    return f"第 {item.page_from}–{item.page_to} 页"


def _render_markdown(
    title: str,
    topic: str,
    created_at: datetime,
    sections: list[ReportSectionOut],
    citations,
    truncated: bool,
    document_count: int,
) -> str:
    lines = [
        f"# {title}",
        "",
        f"> 研究主题：{topic}",
        f"> 生成时间：{created_at.strftime('%Y-%m-%d %H:%M:%S')}",
        f"> 资料来源：{document_count} 份知识库文档",
        "",
    ]
    for section in sections:
        lines.extend([f"## {section.title}", "", section.content.strip(), ""])
    lines.extend(["## 参考资料", ""])
    for line in _reference_lines(citations):
        lines.append(line)
    lines.append("")
    if truncated:
        lines.append("> 提示：资料较多，已按上下文预算截取部分检索结果。")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _write_docx(
    path: Path,
    title: str,
    topic: str,
    created_at: datetime,
    sections: list[ReportSectionOut],
    citations,
    truncated: bool,
) -> None:
    document = DocxDocument()
    document.add_heading(title, level=0)
    document.add_paragraph(f"研究主题：{topic}")
    document.add_paragraph(f"生成时间：{created_at.strftime('%Y-%m-%d %H:%M:%S')}")
    for section in sections:
        document.add_heading(section.title, level=1)
        for paragraph in section.content.split("\n"):
            if paragraph.strip():
                document.add_paragraph(paragraph.strip())
    document.add_heading("参考资料", level=1)
    for line in _reference_lines(citations):
        document.add_paragraph(line)
    if truncated:
        document.add_paragraph("提示：资料较多，已按上下文预算截取部分检索结果。")
    document.save(str(path))


async def generate(db, payload: ReportRequest) -> ReportResultOut:
    started = time.perf_counter()
    settings = get_settings()
    if not settings.llm_configured:
        raise AIProviderError(
            "尚未配置大语言模型，无法生成研究报告。"
            "请到「系统设置 → 大模型（LLM）」填写接口地址、API Key 和模型名称。"
        )
    documents = _validate_documents(db, payload.document_ids)
    per_doc_budget = max(800, settings.rag_context_chars // len(documents))

    hits: list[SearchHit] = []
    seen: set[str] = set()
    truncated = False
    for document in documents:
        context = await rag_service.build_context(
            db,
            payload.topic,
            top_k=payload.top_k,
            max_chars=per_doc_budget,
            document_ids=[document.id],
        )
        truncated = truncated or context.truncated
        for hit in context.hits:
            if hit.chunk_id in seen:
                continue
            seen.add(hit.chunk_id)
            hits.append(hit)

    kept: list[SearchHit] = []
    used_chars = 0
    for hit in hits:
        block_len = len(hit.content) + len(hit.document_name) + 32
        if kept and used_chars + block_len > settings.rag_context_chars:
            truncated = True
            break
        kept.append(hit)
        used_chars += block_len
    hits = kept

    max_score = max((hit.score for hit in hits), default=0.0)
    if not hits or max_score < settings.rag_min_score:
        reason = (
            "所选资料中没有检索到与研究主题相关的内容，请更换资料或调整主题关键词。"
            if not hits
            else (
                f"检索到的资料相关性不足（最高相似度 {max_score:.2f}，"
                f"当前拒答阈值 {settings.rag_min_score:.2f}），未生成报告，避免编造。"
            )
        )
        return ReportResultOut(
            report_id="",
            title=f"{payload.topic} 研究报告",
            topic=payload.topic,
            sections=[],
            citations=[],
            markdown="",
            retrieval_count=len(hits),
            truncated=truncated,
            refusal=True,
            message=reason,
            model=settings.llm_model,
            created_at=datetime.now(),
            formats=[],
        )

    llm = get_llm()
    raw = await llm.chat(_build_messages(payload.topic, _build_context(hits)), temperature=0.2)
    cleaned, cited, _refusal = rag_service.validate_citations(raw, len(hits))
    if not cleaned.strip():
        raise ProcessingError("模型未返回有效内容，请重试或更换模型。")
    citations = rag_service.build_citations(hits, cited)
    sections = _split_sections(cleaned)
    title = f"{payload.topic} 研究报告"
    created_at = datetime.now()
    markdown = _render_markdown(
        title, payload.topic, created_at, sections, citations, truncated, len(documents)
    )

    report_id = uuid4().hex
    directory = _reports_dir()
    json_path = directory / f"{report_id}.json"
    md_path = directory / f"{report_id}.md"
    docx_path = directory / f"{report_id}.docx"
    try:
        await asyncio.to_thread(
            _write_docx, docx_path, title, payload.topic, created_at, sections, citations, truncated
        )
        await asyncio.to_thread(md_path.write_text, markdown, "utf-8")
        payload_json = {
            "report_id": report_id,
            "title": title,
            "topic": payload.topic,
            "created_at": created_at.isoformat(),
            "sections": [section.model_dump() for section in sections],
            "citations": [item.model_dump(mode="json") for item in citations],
            "markdown": markdown,
            "model": settings.llm_model,
            "retrieval_count": len(hits),
            "truncated": truncated,
            "document_ids": [document.id for document in documents],
            "formats": ["md", "docx"],
        }
        await asyncio.to_thread(
            json_path.write_text,
            json.dumps(payload_json, ensure_ascii=False, indent=2),
            "utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("报告文件写入失败")
        raise ProcessingError(f"报告内容已生成，但导出文件失败：{exc}") from exc

    logger.info(
        "研究报告已生成：%s（%d 段资料，%d ms）",
        report_id,
        len(hits),
        int((time.perf_counter() - started) * 1000),
    )
    return ReportResultOut(
        report_id=report_id,
        title=title,
        topic=payload.topic,
        sections=sections,
        citations=citations,
        markdown=markdown,
        retrieval_count=len(hits),
        truncated=truncated,
        refusal=False,
        message="报告已生成" if not truncated else "报告已生成（部分资料因上下文预算被截取）",
        model=settings.llm_model,
        created_at=created_at,
        formats=["md", "docx"],
    )


def list_reports(limit: int = 20) -> list[ReportSummaryOut]:
    directory = _reports_dir()
    files = sorted(directory.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    summaries: list[ReportSummaryOut] = []
    for path in files[:limit]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            summaries.append(
                ReportSummaryOut(
                    report_id=data.get("report_id", path.stem),
                    title=data.get("title", "未命名报告"),
                    topic=data.get("topic", ""),
                    created_at=datetime.fromisoformat(data["created_at"]),
                    citation_count=len(
                        [item for item in data.get("citations", []) if item.get("cited")]
                    ),
                    formats=[
                        fmt
                        for fmt in ("md", "docx")
                        if (directory / f"{path.stem}.{fmt}").exists()
                    ],
                )
            )
        except (json.JSONDecodeError, KeyError, ValueError, OSError):
            logger.warning("跳过损坏的报告文件：%s", path)
    return summaries


def get_report(report_id: str) -> ReportResultOut:
    if not _REPORT_ID_PATTERN.match(report_id):
        raise NotFoundError("报告不存在")
    path = _reports_dir() / f"{report_id}.json"
    if not path.is_file():
        raise NotFoundError("报告不存在或已被删除")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ReportResultOut(**data)
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        raise ProcessingError("报告文件损坏，无法读取") from exc


def download_path(report_id: str, fmt: str) -> Path:
    if fmt not in ("md", "docx"):
        raise ProcessingError("仅支持导出 Markdown 或 DOCX 格式")
    if not _REPORT_ID_PATTERN.match(report_id):
        raise NotFoundError("报告不存在")
    path = _reports_dir() / f"{report_id}.{fmt}"
    if not path.is_file():
        raise NotFoundError("该格式的导出文件不存在，请重新生成报告")
    return path

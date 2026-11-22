"""多文档联合分析与智能总结：逐文档检索、上下文预算控制、引用校验。"""

from __future__ import annotations

import logging
import re
import time

from app.ai.registry import get_llm
from app.core.config import get_settings
from app.core.errors import AIProviderError, AppError, NotFoundError
from app.models import Document
from app.repositories import document_repository
from app.schemas import (
    AnalysisRequest,
    AnalysisResultOut,
    AnalysisSectionOut,
    SearchHit,
)
from app.services import rag_service

logger = logging.getLogger(__name__)

MODE_COMPARE = "compare"
MODE_SUMMARY = "summary"

HEADINGS = {
    MODE_COMPARE: ["共同观点", "差异分析", "关键知识点"],
    MODE_SUMMARY: ["核心观点", "关键概念", "重要结论", "待研究问题"],
}

SYSTEM_PROMPT = (
    "你是知枢 AI 的知识库分析助手。你只能依据提供的资料片段进行分析。\n"
    "规则：\n"
    "0. 必须严格按用户指定的二级标题分节输出，不要增删小节。\n"
    "1. 每个结论后用 [编号] 标注来源，编号只能来自资料前的方括号编号。\n"
    "2. 严禁编造文档名称、页码或原文，也不要补充资料中没有的事实。\n"
    "3. 资料不足时，在该小节明确写「资料不足，无法判断」。\n"
    "4. 使用简体中文，条理清晰，避免空话。"
)

_HEADING_PATTERN = re.compile(r"^#{2,4}\s*(.+?)\s*$", re.MULTILINE)


def _page_label(hit: SearchHit) -> str:
    if hit.page_from is None:
        return "全文"
    if hit.page_from == hit.page_to:
        return f"第 {hit.page_from} 页"
    return f"第 {hit.page_from}–{hit.page_to} 页"


def _validate_documents(db, document_ids: list[str]) -> list[Document]:
    unique_ids = list(dict.fromkeys(document_ids))
    if not unique_ids:
        raise AppError("请至少选择一份资料")
    documents: list[Document] = []
    for document_id in unique_ids:
        document = document_repository.get_document(db, document_id)
        if document is None:
            raise NotFoundError("所选资料不存在或已被删除，请刷新后重试")
        if document.status != "completed":
            raise AppError(
                f"《{document.original_name}》尚未完成解析与索引，暂不能参与分析"
            )
        documents.append(document)
    return documents


def _build_prompt(topic: str, mode: str, blocks: list[str]) -> list[dict[str, str]]:
    headings = HEADINGS[mode]
    outline = "\n".join(f"## {title}" for title in headings)
    if mode == MODE_COMPARE:
        task = "请对以下资料进行联合分析，比较它们的共同观点、差异与关键知识点。"
    else:
        task = "请对以下资料进行综合总结，提炼核心观点、关键概念、重要结论与待研究问题。"
    user_prompt = (
        f"{task}\n\n主题：{topic}\n\n"
        f"请严格按以下小节输出，每个小节都要有实质内容，并用 [编号] 标注资料出处：\n{outline}\n\n"
        f"资料片段：\n\n" + "\n\n".join(blocks)
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def _build_context(hits: list[SearchHit]) -> str:
    return "\n\n".join(
        f"[{index}] 《{hit.document_name}》{_page_label(hit)}\n{hit.content.strip()}"
        for index, hit in enumerate(hits, start=1)
    )


def _split_sections(text: str, mode: str) -> list[AnalysisSectionOut]:
    matches = list(_HEADING_PATTERN.finditer(text))
    if not matches:
        return [AnalysisSectionOut(title="分析结果", content=text.strip())]

    sections: list[AnalysisSectionOut] = []
    for index, match in enumerate(matches):
        title = match.group(1).strip().strip("*# ").strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        if title:
            sections.append(AnalysisSectionOut(title=title, content=content))

    if not sections:
        return [AnalysisSectionOut(title="分析结果", content=text.strip())]
    # 保证固定小节顺序存在，缺失的小节补占位，避免前端展示不完整
    by_title = {section.title: section for section in sections}
    ordered: list[AnalysisSectionOut] = []
    for title in HEADINGS[mode]:
        ordered.append(
            by_title.pop(
                title,
                AnalysisSectionOut(title=title, content="资料不足，无法判断。"),
            )
        )
    ordered.extend(by_title.values())
    return ordered


async def analyze(db, payload: AnalysisRequest) -> AnalysisResultOut:
    started = time.perf_counter()
    settings = get_settings()
    if not settings.llm_configured:
        raise AIProviderError(
            "尚未配置大语言模型，无法进行多文档分析。"
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

    # 总上下文预算兜底：超长时保留高分命中，明确标记截断
    blocks: list[str] = []
    kept: list[SearchHit] = []
    used_chars = 0
    for hit in hits:
        block = f"[{len(kept) + 1}] 《{hit.document_name}》{_page_label(hit)}\n{hit.content.strip()}"
        if blocks and used_chars + len(block) > settings.rag_context_chars:
            truncated = True
            break
        kept.append(hit)
        blocks.append(block)
        used_chars += len(block)
    hits = kept

    max_score = max((hit.score for hit in hits), default=0.0)
    insufficient = not hits or max_score < settings.rag_min_score
    if insufficient:
        reason = (
            "所选资料中没有检索到与主题相关的内容，请更换资料或调整关键词。"
            if not hits
            else (
                f"检索到的内容相关性不足（最高相似度 {max_score:.2f}，"
                f"当前拒答阈值 {settings.rag_min_score:.2f}），为避免编造，未生成分析。"
            )
        )
        return AnalysisResultOut(
            mode=payload.mode,
            topic=payload.topic,
            sections=[],
            citations=[],
            retrieval_count=len(hits),
            truncated=truncated,
            refusal=True,
            message=reason,
            model=settings.llm_model,
            took_ms=int((time.perf_counter() - started) * 1000),
        )

    llm = get_llm()
    raw = await llm.chat(
        _build_prompt(payload.topic, payload.mode, blocks), temperature=0.2
    )
    cleaned, cited, _refusal = rag_service.validate_citations(raw, len(hits))
    citations = rag_service.build_citations(hits, cited)

    refusal_text = "所选资料中没有找到足够相关的内容"
    message = ""
    if not cleaned.strip():
        cleaned = refusal_text + "，无法生成分析。"
        message = cleaned

    return AnalysisResultOut(
        mode=payload.mode,
        topic=payload.topic,
        sections=_split_sections(cleaned, payload.mode),
        citations=citations,
        retrieval_count=len(hits),
        truncated=truncated,
        refusal=bool(message),
        message=message,
        model=settings.llm_model,
        took_ms=int((time.perf_counter() - started) * 1000),
    )


async def summarize(db, payload: AnalysisRequest) -> AnalysisResultOut:
    return await analyze(db, payload)

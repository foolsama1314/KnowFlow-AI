"""RAG 检索上下文：真实向量检索 + SQLite 校验 + 上下文长度控制。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from app.core.config import get_settings
from app.models import Document
from app.repositories import document_repository
from app.schemas import CitationOut, SearchFilters, SearchHit, SearchRequest
from app.services import search_service

logger = logging.getLogger(__name__)


@dataclass
class RagContext:
    """一次问答实际使用的检索结果。"""

    hits: list[SearchHit] = field(default_factory=list)
    prompt_text: str = ""
    max_score: float = 0.0
    truncated: bool = False
    insufficient: bool = False


def page_label(hit: SearchHit) -> str:
    if hit.page_from is None:
        return "全文"
    if hit.page_from == hit.page_to:
        return f"第 {hit.page_from} 页"
    return f"第 {hit.page_from}–{hit.page_to} 页"


def _hit_block(index: int, hit: SearchHit) -> str:
    return f"[{index}] 《{hit.document_name}》{page_label(hit)}\n{hit.content.strip()}"


async def build_context(
    db,
    query: str,
    *,
    top_k: int | None = None,
    min_score: float | None = None,
    max_chars: int | None = None,
    document_ids: list[str] | None = None,
) -> RagContext:
    """调用第一阶段检索服务，并逐个校验命中是否仍指向真实存在的文本块。"""
    settings = get_settings()
    limit = top_k or settings.rag_top_k
    threshold = settings.rag_min_score if min_score is None else min_score
    budget = max_chars or settings.rag_context_chars

    response = await search_service.search(
        db,
        SearchRequest(
            query=query,
            top_k=limit,
            filters=SearchFilters(document_ids=document_ids or []),
        ),
    )

    hits: list[SearchHit] = []
    seen: set[str] = set()
    for hit in response.results:
        if hit.chunk_id in seen:
            continue
        chunk = document_repository.get_chunks(db, [hit.chunk_id]).get(hit.chunk_id)
        if chunk is None:
            logger.warning("检索命中对应的文本块已不存在，已跳过：%s", hit.chunk_id)
            continue
        document = db.get(Document, chunk.document_id)
        if document is None or document.status != "completed":
            logger.warning("检索命中对应的文档不可用，已跳过：%s", hit.chunk_id)
            continue
        seen.add(hit.chunk_id)
        hits.append(hit)

    blocks: list[str] = []
    used_chars = 0
    truncated = False
    for index, hit in enumerate(hits, start=1):
        block = _hit_block(index, hit)
        if blocks and used_chars + len(block) > budget:
            truncated = True
            hits = hits[: len(blocks)]
            break
        blocks.append(block)
        used_chars += len(block)

    max_score = max((hit.score for hit in hits), default=0.0)
    insufficient = not hits or max_score < threshold
    return RagContext(
        hits=hits,
        prompt_text="\n\n".join(blocks),
        max_score=max_score,
        truncated=truncated,
        insufficient=insufficient,
    )


def build_citations(hits: list[SearchHit], cited_numbers: set[int]) -> list[CitationOut]:
    """把回答中的编号映射为真实引用，未引用的命中标记 cited=False。"""
    citations: list[CitationOut] = []
    for index, hit in enumerate(hits, start=1):
        citations.append(
            CitationOut(
                chunk_id=hit.chunk_id,
                document_id=hit.document_id,
                document_name=hit.document_name,
                file_type=hit.file_type,
                page_from=hit.page_from,
                page_to=hit.page_to,
                snippet=hit.content.strip()[:200],
                score=round(float(hit.score), 4),
                cited=index in cited_numbers,
            )
        )
    return citations


_CITATION_PATTERN = re.compile(r"\[\s*(\d+)\s*\]")


def validate_citations(
    text: str, hit_count: int, refusal_text: str = ""
) -> tuple[str, set[int], bool]:
    """剔除越界引用编号，返回（清洗后文本、被引用编号、是否命中拒答话术）。"""
    cited: set[int] = set()

    def replace(match: re.Match[str]) -> str:
        number = int(match.group(1))
        if 1 <= number <= hit_count:
            cited.add(number)
            return f"[{number}]"
        return ""

    cleaned = _CITATION_PATTERN.sub(replace, text)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned).strip()
    refusal = bool(refusal_text) and refusal_text in cleaned
    return cleaned, cited, refusal

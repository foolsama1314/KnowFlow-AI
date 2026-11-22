"""RAG 生成服务：构造提示词、流式生成、引用校验与落库。"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import AsyncIterator
from typing import Any

from app.ai.registry import get_llm
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.errors import AIProviderError, NotFoundError
from app.models import ChatMessage, ChatSession
from app.repositories import chat_repository
from app.schemas import ChatAnswerOut, ChatMessageOut, CitationOut
from app.services import rag_service

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "你是知枢 AI 的知识库问答助手。你只能依据用户提供的资料片段回答问题。\n"
    "规则：\n"
    "1. 每个结论后面用 [编号] 标注来源，编号只能来自资料前的方括号编号。\n"
    "2. 严禁编造文档名称、页码、原文，也不要补充资料中没有的事实。\n"
    "3. 如果资料不足以回答，只回复：知识库中没有找到足够相关的内容，无法回答。\n"
    "4. 使用简体中文，回答简洁准确。"
)

REFUSAL_TEXT = "知识库中没有找到足够相关的内容，无法回答。"

_CITATION_PATTERN = re.compile(r"\[\s*(\d+)\s*\]")


def _build_messages(context_text: str, question: str) -> list[dict[str, str]]:
    user_prompt = (
        f"以下是从个人知识库检索到的资料：\n\n{context_text}\n\n"
        f"请回答这个问题：{question}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def _validate_answer(text: str, hit_count: int) -> tuple[str, set[int], bool]:
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
    refusal = REFUSAL_TEXT in cleaned
    return cleaned, cited, refusal


def _citation_payload(citations: list[CitationOut]) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in citations]


def _save_assistant(
    db,
    session: ChatSession,
    content: str,
    hits,
    cited: set[int],
) -> tuple[ChatMessage, list[CitationOut]]:
    citations = rag_service.build_citations(hits, cited)
    message = chat_repository.add_message(
        db,
        session=session,
        role="assistant",
        content=content,
        citations=_citation_payload(citations),
    )
    return message, citations


async def stream_answer(
    session_id: str,
    question: str,
    *,
    top_k: int | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """流式问答事件：meta / sources / delta / done / error。"""
    settings = get_settings()
    if not settings.llm_configured:
        raise AIProviderError(
            "尚未配置大语言模型。请到「系统设置 → 大模型（LLM）」填写接口地址、API Key 和模型名称。"
        )

    started = time.perf_counter()
    db = SessionLocal()
    accumulated = ""
    hits = []
    saved = False
    try:
        session = chat_repository.get_session(db, session_id)
        if session is None:
            raise NotFoundError("问答会话不存在")
        chat_repository.add_message(db, session=session, role="user", content=question)

        context = await rag_service.build_context(db, question, top_k=top_k)
        hits = context.hits
        llm = get_llm()

        yield {
            "event": "meta",
            "data": {
                "model": settings.llm_model,
                "retrieval_count": len(hits),
                "max_score": round(context.max_score, 4),
                "truncated": context.truncated,
                "refusal": context.insufficient,
            },
        }
        yield {
            "event": "sources",
            "data": {
                "citations": [
                    item.model_dump(mode="json")
                    for item in rag_service.build_citations(hits, set())
                ]
            },
        }

        if context.insufficient:
            accumulated = REFUSAL_TEXT
            yield {"event": "delta", "data": {"text": accumulated}}
        else:
            async for delta in llm.chat_stream(
                _build_messages(context.prompt_text, question), temperature=0.2
            ):
                accumulated += delta
                yield {"event": "delta", "data": {"text": delta}}

        cleaned, cited, refusal = _validate_answer(accumulated, len(hits))
        accumulated = cleaned or REFUSAL_TEXT
        message, citations = _save_assistant(db, session, accumulated, hits, cited)
        saved = True
        yield {
            "event": "done",
            "data": {
                "message_id": message.id,
                # 服务端清洗后的最终正文（已剔除越界引用编号），前端以此为准
                "content": accumulated,
                "citations": _citation_payload(citations),
                "refusal": refusal,
                "took_ms": int((time.perf_counter() - started) * 1000),
            },
        }
    except AIProviderError as exc:
        logger.warning("问答生成失败：%s", exc.message)
        yield {"event": "error", "data": {"message": exc.message}}
    except Exception as exc:  # noqa: BLE001 - 流式响应内不能抛结构化 HTTP 错误
        logger.exception("问答生成异常")
        yield {"event": "error", "data": {"message": f"生成回答失败：{exc}"}}
    finally:
        if not saved and accumulated.strip():
            try:
                session = chat_repository.get_session(db, session_id)
                if session is not None:
                    cleaned, cited, _refusal = _validate_answer(accumulated, len(hits))
                    if cleaned:
                        _save_assistant(db, session, cleaned + "\n\n（生成已中断）", hits, cited)
            except Exception:  # noqa: BLE001 - 中断时保存失败不应影响连接关闭
                logger.exception("保存中断回答失败")
        db.close()


async def answer_once(
    db,
    session_id: str,
    question: str,
    *,
    top_k: int | None = None,
) -> ChatAnswerOut:
    """非流式问答，供接口与测试使用。"""
    settings = get_settings()
    if not settings.llm_configured:
        raise AIProviderError(
            "尚未配置大语言模型。请到「系统设置 → 大模型（LLM）」填写接口地址、API Key 和模型名称。"
        )
    started = time.perf_counter()
    session = chat_repository.get_session(db, session_id)
    if session is None:
        raise NotFoundError("问答会话不存在")

    chat_repository.add_message(db, session=session, role="user", content=question)
    context = await rag_service.build_context(db, question, top_k=top_k)

    if context.insufficient:
        content = REFUSAL_TEXT
        refusal = True
    else:
        llm = get_llm()
        content = await llm.chat(
            _build_messages(context.prompt_text, question), temperature=0.2
        )
        refusal = False

    cleaned, cited, refusal_flag = _validate_answer(content, len(context.hits))
    content = cleaned or REFUSAL_TEXT
    message, citations = _save_assistant(db, session, content, context.hits, cited)
    return ChatAnswerOut(
        message=ChatMessageOut.model_validate(message),
        citations=citations,
        retrieval_count=len(context.hits),
        context_truncated=context.truncated,
        refusal=refusal or refusal_flag,
        took_ms=int((time.perf_counter() - started) * 1000),
    )

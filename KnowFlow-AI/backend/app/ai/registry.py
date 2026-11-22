"""模型实例注册：按当前配置创建并缓存适配器，设置变更后调用 reset_clients()。"""

from __future__ import annotations

import logging

from app.ai.base import EmbeddingProvider, LLMProvider
from app.ai.openai_compatible import OpenAICompatibleEmbedding, OpenAICompatibleLLM
from app.core.config import get_settings
from app.core.errors import AIProviderError

logger = logging.getLogger(__name__)

_llm: LLMProvider | None = None
_embedding: EmbeddingProvider | None = None


def get_llm() -> LLMProvider:
    global _llm
    if _llm is not None:
        return _llm
    settings = get_settings()
    if not settings.llm_configured:
        raise AIProviderError(
            "尚未配置大模型 API Key，请到「系统设置」填写 LLM API Key 与模型名称后重试。"
        )
    _llm = OpenAICompatibleLLM(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
    )
    return _llm


def get_embedding() -> EmbeddingProvider:
    global _embedding
    if _embedding is not None:
        return _embedding
    settings = get_settings()
    if not (settings.embedding_configured and settings.embedding_base_url):
        raise AIProviderError(
            "尚未配置 Embedding 向量服务。请到「系统设置」填写 OpenAI 兼容接口地址、"
            "API Key、模型名称和向量维度；正式检索不会使用本地哈希向量代替。"
        )
    _embedding = OpenAICompatibleEmbedding(
        api_key=settings.embedding_api_key,
        base_url=settings.embedding_base_url,
        model=settings.embedding_model,
        dim=settings.embedding_dim,
    )
    logger.info(
        "使用 API 向量模型：%s（%d 维）", settings.embedding_model, settings.embedding_dim
    )
    return _embedding


def embedding_is_degraded() -> bool:
    settings = get_settings()
    return not (settings.embedding_configured and settings.embedding_base_url)


def llm_is_configured() -> bool:
    return get_settings().llm_configured


def reset_clients() -> None:
    """模型配置变更后丢弃缓存实例。"""
    global _llm, _embedding
    _llm = None
    _embedding = None

"""模型适配与向量库。"""

from app.ai.base import EmbeddingProvider, LLMProvider
from app.ai.registry import (
    embedding_is_degraded,
    get_embedding,
    get_llm,
    llm_is_configured,
    reset_clients,
)
from app.ai.vector_store import vector_store

__all__ = [
    "EmbeddingProvider",
    "LLMProvider",
    "embedding_is_degraded",
    "get_embedding",
    "get_llm",
    "llm_is_configured",
    "reset_clients",
    "vector_store",
]

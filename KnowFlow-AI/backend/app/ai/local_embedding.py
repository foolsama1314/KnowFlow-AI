"""本地降级向量：无需任何 API Key 的离线实现，仅用于链路联调与演示。

它不是语义向量模型，而是基于字符 n-gram 的哈希向量，只能提供词面相近度。
生产环境请在设置页配置真实 Embedding 服务后重建索引。
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable

from app.ai.base import EmbeddingProvider

_LATIN_WORD = re.compile(r"[a-zA-Z0-9_]+")
_CJK = re.compile(r"[\u4e00-\u9fff]")


def _tokenize(text: str) -> Iterable[str]:
    lowered = text.lower()
    for word in _LATIN_WORD.findall(lowered):
        yield f"w:{word}"
    chars = _CJK.findall(text)
    for char in chars:
        yield f"c:{char}"
    for left, right in zip(chars, chars[1:]):
        yield f"b:{left}{right}"


class LocalHashingEmbedding(EmbeddingProvider):
    def __init__(self, dim: int = 1024) -> None:
        self._dim = dim

    @property
    def dimension(self) -> int:
        return self._dim

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self._dim
        for token in _tokenize(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self._dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

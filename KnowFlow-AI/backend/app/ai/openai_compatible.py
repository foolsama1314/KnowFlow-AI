"""OpenAI 兼容协议的 LLM / Embedding 适配器（适用于国内多数大模型服务）。"""

from __future__ import annotations

import json
import logging
import math
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.ai.base import EmbeddingProvider, LLMProvider
from app.core.errors import AIProviderError

logger = logging.getLogger(__name__)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _join(base_url: str, path: str) -> str:
    return base_url.strip().rstrip("/") + path


def _embeddings_url(base_url: str) -> str:
    """兼容两种填写习惯：只填到 /v1，或直接粘贴完整的 /embeddings 地址。"""
    base = base_url.strip().rstrip("/")
    return base if base.endswith("/embeddings") else base + "/embeddings"


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
        message = payload.get("error", {}).get("message") or json.dumps(payload, ensure_ascii=False)
    except (json.JSONDecodeError, ValueError):
        message = response.text
    return f"HTTP {response.status_code}: {message[:300]}"


class OpenAICompatibleLLM(LLMProvider):
    def __init__(self, *, api_key: str, base_url: str, model: str, timeout: float = 90.0) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.3),
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    _join(self.base_url, "/chat/completions"), headers=self._headers(), json=payload
                )
        except httpx.HTTPError as exc:
            raise AIProviderError(f"模型服务连接失败：{exc}") from exc
        if response.status_code >= 400:
            raise AIProviderError(f"模型服务返回错误：{_error_message(response)}")
        data = response.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise AIProviderError("模型返回结构异常，未找到 choices[0].message.content") from exc

    async def chat_stream(
        self, messages: list[dict[str, str]], **kwargs: Any
    ) -> AsyncIterator[str]:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.3),
            "stream": True,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    _join(self.base_url, "/chat/completions"),
                    headers=self._headers(),
                    json=payload,
                ) as response:
                    if response.status_code >= 400:
                        body = await response.aread()
                        raise AIProviderError(f"模型服务返回错误：{body.decode('utf-8', 'ignore')[:300]}")
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        chunk = line[5:].strip()
                        if not chunk or chunk == "[DONE]":
                            continue
                        try:
                            delta = json.loads(chunk)["choices"][0]["delta"].get("content")
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
                        if delta:
                            yield delta
        except httpx.HTTPError as exc:
            raise AIProviderError(f"模型流式服务连接失败：{exc}") from exc

    async def generate_json(
        self, messages: list[dict[str, str]], **kwargs: Any
    ) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.1),
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    _join(self.base_url, "/chat/completions"), headers=self._headers(), json=payload
                )
        except httpx.HTTPError as exc:
            raise AIProviderError(f"模型服务连接失败：{exc}") from exc
        if response.status_code >= 400:
            raise AIProviderError(f"模型服务返回错误：{_error_message(response)}")
        content = response.json()["choices"][0]["message"]["content"]
        cleaned = _FENCE.sub("", content).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise AIProviderError("模型未返回合法 JSON，请重试或更换模型") from exc


class OpenAICompatibleEmbedding(EmbeddingProvider):
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        dim: int,
        timeout: float = 60.0,
        batch_size: int = 16,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self._dim = dim
        self.timeout = timeout
        self.batch_size = batch_size

    @property
    def dimension(self) -> int:
        return self._dim

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    async def _request(self, texts: list[str]) -> list[list[float]]:
        payload = {"model": self.model, "input": texts}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    _embeddings_url(self.base_url), headers=self._headers(), json=payload
                )
        except httpx.HTTPError as exc:
            raise AIProviderError(f"向量服务连接失败：{exc}") from exc
        if response.status_code >= 400:
            raise AIProviderError(f"向量服务返回错误：{_error_message(response)}")
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise AIProviderError("向量服务未返回合法 JSON") from exc
        try:
            items = data["data"]
            if not isinstance(items, list):
                raise TypeError("data is not a list")
            if len(items) != len(texts):
                raise AIProviderError(
                    f"向量服务返回数量不一致：提交 {len(texts)} 条，返回 {len(items)} 条"
                )
            indexed_items = []
            for item in items:
                index = item["index"]
                if not isinstance(index, int) or isinstance(index, bool):
                    raise TypeError("invalid vector index")
                indexed_items.append((index, item["embedding"]))
            if sorted(index for index, _vector in indexed_items) != list(range(len(texts))):
                raise AIProviderError("向量服务返回的 data[].index 不完整或重复")
            indexed_items.sort(key=lambda item: item[0])
        except (KeyError, TypeError) as exc:
            raise AIProviderError(
                "向量服务返回结构异常，未找到有效的 data[].index 与 data[].embedding"
            ) from exc

        vectors: list[list[float]] = []
        for _index, raw_vector in indexed_items:
            if not isinstance(raw_vector, list) or len(raw_vector) != self._dim:
                actual_dim = len(raw_vector) if isinstance(raw_vector, list) else "未知"
                raise AIProviderError(
                    f"向量维度与配置不一致：服务返回 {actual_dim} 维，配置为 {self._dim} 维。"
                    "请到设置页修正向量维度后重建索引。"
                )
            try:
                vector = [float(value) for value in raw_vector]
            except (TypeError, ValueError) as exc:
                raise AIProviderError("向量服务返回了非数值向量") from exc
            if not all(math.isfinite(value) for value in vector):
                raise AIProviderError("向量服务返回了 NaN 或无穷大数值")
            vectors.append(vector)
        return vectors

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            vectors.extend(await self._request(batch))
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self._request([text])
        return vectors[0]

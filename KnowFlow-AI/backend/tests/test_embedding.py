"""Embedding 适配器协议与严格响应校验测试（仅模拟 HTTP 边界）。"""

from types import SimpleNamespace

import httpx
import pytest

from app.ai import registry
from app.ai.openai_compatible import OpenAICompatibleEmbedding
from app.core.errors import AIProviderError


class FakeAsyncClient:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.payloads: list[dict] = []
        self.urls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url: str, *, headers: dict, json: dict):
        assert headers["Authorization"] == "Bearer test-key"
        self.urls.append(url)
        self.payloads.append(json)
        return self.response


def provider() -> OpenAICompatibleEmbedding:
    return OpenAICompatibleEmbedding(
        api_key="test-key",
        base_url="https://embedding.example/v1",
        model="bge-m3",
        dim=3,
    )


def install_response(monkeypatch, response: httpx.Response) -> FakeAsyncClient:
    client = FakeAsyncClient(response)
    monkeypatch.setattr(
        "app.ai.openai_compatible.httpx.AsyncClient", lambda **_kwargs: client
    )
    return client


async def test_embedding_orders_vectors_by_index(monkeypatch):
    client = install_response(
        monkeypatch,
        httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [4, 5, 6]},
                    {"index": 0, "embedding": [1, 2, 3]},
                ]
            },
        ),
    )

    vectors = await provider().embed_documents(["第一段", "第二段"])

    assert vectors == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
    assert client.payloads[0]["input"] == ["第一段", "第二段"]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"data": [{"index": 0, "embedding": [1, 2, 3]}]}, "数量不一致"),
        (
            {
                "data": [
                    {"index": 0, "embedding": [1, 2, 3]},
                    {"index": 1, "embedding": [1, 2]},
                ]
            },
            "维度与配置不一致",
        ),
        ({"data": [{"embedding": [1, 2, 3]}]}, "返回结构异常"),
        (
            {"data": [{"index": 0, "embedding": [1, float("nan"), 3]}]},
            "NaN",
        ),
    ],
)
async def test_embedding_rejects_invalid_responses(monkeypatch, payload, message):
    response = (
        httpx.Response(200, content='{"data":[{"index":0,"embedding":[1,NaN,3]}]}')
        if message == "NaN"
        else httpx.Response(200, json=payload)
    )
    install_response(monkeypatch, response)
    texts = ["一", "二"] if message == "数量不一致" or len(payload["data"]) == 2 else ["一"]

    with pytest.raises(AIProviderError, match=message):
        await provider().embed_documents(texts)


async def test_embedding_url_tolerates_full_endpoint(monkeypatch):
    response = httpx.Response(200, json={"data": [{"index": 0, "embedding": [1, 2, 3]}]})

    client = install_response(monkeypatch, response)
    await OpenAICompatibleEmbedding(
        api_key="test-key",
        base_url="https://api.jina.ai/v1/embeddings",
        model="jina-embeddings-v4",
        dim=3,
    ).embed_query("测试")
    assert client.urls == ["https://api.jina.ai/v1/embeddings"]

    client = install_response(monkeypatch, response)
    await OpenAICompatibleEmbedding(
        api_key="test-key",
        base_url=" https://embedding.example/v1/ ",
        model="bge-m3",
        dim=3,
    ).embed_query("测试")
    assert client.urls == ["https://embedding.example/v1/embeddings"]


async def test_embedding_rejects_http_error(monkeypatch):
    install_response(
        monkeypatch,
        httpx.Response(401, json={"error": {"message": "invalid key"}}),
    )

    with pytest.raises(AIProviderError, match="HTTP 401"):
        await provider().embed_query("测试")


def test_registry_never_falls_back_to_hashing(monkeypatch):
    settings = SimpleNamespace(
        embedding_configured=False,
        embedding_base_url="",
        embedding_api_key="",
        embedding_model="",
        embedding_dim=1024,
    )
    monkeypatch.setattr(registry, "get_settings", lambda: settings)
    registry.reset_clients()

    with pytest.raises(AIProviderError, match="不会使用本地哈希向量"):
        registry.get_embedding()

    registry.reset_clients()

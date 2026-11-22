"""模型与处理参数配置。"""

from __future__ import annotations

import time

from app.ai.openai_compatible import OpenAICompatibleEmbedding, OpenAICompatibleLLM
from app.ai.registry import (
    embedding_is_degraded,
    reset_clients,
)
from app.ai.vector_store import vector_store
from app.core.config import get_settings, reload_settings
from app.core.database import SessionLocal
from app.core.errors import AIProviderError, AppError
from app.core.settings_store import write_overrides
from app.services.index_service import get_index_status, require_reindex
from app.schemas import (
    ModelSettingsOut,
    ModelSettingsUpdate,
    ModelTestResult,
    ProcessingSettings,
    RagSettings,
    SettingsOut,
    SettingsUpdate,
)

MASK = "••••••••"


def current() -> SettingsOut:
    settings = get_settings()
    return SettingsOut(
        models=ModelSettingsOut(
            llm_provider=settings.llm_provider,
            llm_base_url=settings.llm_base_url,
            llm_model=settings.llm_model,
            llm_has_key=bool(settings.llm_api_key),
            llm_configured=settings.llm_configured,
            embedding_provider=settings.embedding_provider,
            embedding_base_url=settings.embedding_base_url,
            embedding_model=settings.embedding_model,
            embedding_dim=settings.embedding_dim,
            embedding_has_key=bool(settings.embedding_api_key),
            embedding_configured=settings.embedding_configured,
            embedding_degraded=embedding_is_degraded(),
        ),
        processing=ProcessingSettings(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            default_top_k=settings.default_top_k,
            max_upload_mb=settings.max_upload_mb,
        ),
        rag=RagSettings(
            rag_top_k=settings.rag_top_k,
            rag_min_score=settings.rag_min_score,
            rag_context_chars=settings.rag_context_chars,
        ),
    )


def update(payload: SettingsUpdate) -> SettingsOut:
    before = get_settings()
    embedding_before = (
        before.embedding_provider,
        before.embedding_base_url,
        before.embedding_model,
        before.embedding_dim,
    )
    values: dict = {}
    if payload.models is not None:
        data = payload.models.model_dump(exclude_none=True)
        for key in ("llm_api_key", "embedding_api_key"):
            value = data.get(key)
            if value is None or value.strip() in ("", MASK) or "•" in value:
                data.pop(key, None)
        values.update(data)
    if payload.processing is not None:
        values.update(payload.processing.model_dump(exclude_none=True))
    if payload.rag is not None:
        values.update(payload.rag.model_dump(exclude_none=True))

    write_overrides(values)
    after = reload_settings()
    if payload.models is not None:
        reset_clients()
        vector_store.reset()
        embedding_after = (
            after.embedding_provider,
            after.embedding_base_url,
            after.embedding_model,
            after.embedding_dim,
        )
        db = SessionLocal()
        try:
            if embedding_before != embedding_after:
                require_reindex(db, "向量模型配置已变化，请重建索引后再检索")
            get_index_status(db)
        finally:
            db.close()
    return current()


async def test_model(
    target: str, models: ModelSettingsUpdate | None = None
) -> ModelTestResult:
    """测试连接：优先使用页面当前填写值，未填写的项回退到已保存配置。"""
    started = time.perf_counter()
    settings = get_settings()
    values = models.model_dump(exclude_none=True) if models is not None else {}

    def pick(key: str, current_value: str) -> str:
        value = values.get(key)
        if not isinstance(value, str):
            return current_value
        value = value.strip()
        if not value or value == MASK or "•" in value:
            return current_value
        return value

    try:
        if target == "llm":
            api_key = pick("llm_api_key", settings.llm_api_key)
            base_url = pick("llm_base_url", settings.llm_base_url)
            model = pick("llm_model", settings.llm_model)
            if not (api_key and base_url and model):
                raise AIProviderError(
                    "请先填写大模型接口地址、API Key 和模型名称，再测试连接。"
                )
            provider = OpenAICompatibleLLM(
                api_key=api_key, base_url=base_url, model=model
            )
            reply = await provider.chat(
                [{"role": "user", "content": "请只回复：连接成功"}], temperature=0
            )
            return ModelTestResult(
                ok=True,
                target="llm",
                message=f"大模型连接成功：{reply.strip()[:60]}",
                latency_ms=int((time.perf_counter() - started) * 1000),
                detail={"model": model},
            )

        api_key = pick("embedding_api_key", settings.embedding_api_key)
        base_url = pick("embedding_base_url", settings.embedding_base_url)
        model = pick("embedding_model", settings.embedding_model)
        dim = int(values.get("embedding_dim") or settings.embedding_dim)
        if not (api_key and base_url and model):
            raise AIProviderError(
                "请先填写向量服务接口地址、API Key 和模型名称，再测试连接。"
            )
        provider = OpenAICompatibleEmbedding(
            api_key=api_key, base_url=base_url, model=model, dim=dim
        )
        vector = await provider.embed_query("连接测试")
        return ModelTestResult(
            ok=True,
            target="embedding",
            message="向量服务连接成功，返回维度校验通过",
            latency_ms=int((time.perf_counter() - started) * 1000),
            detail={
                "model": model,
                "dimension": len(vector),
                "degraded": False,
            },
        )
    except (AIProviderError, AppError) as exc:
        return ModelTestResult(
            ok=False,
            target=target,
            message=exc.message,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
    except Exception as exc:  # noqa: BLE001
        return ModelTestResult(
            ok=False,
            target=target,
            message=f"测试失败：{exc}",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

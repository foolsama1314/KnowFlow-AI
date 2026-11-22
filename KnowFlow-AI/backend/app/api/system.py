"""系统信息与统计接口。"""

from __future__ import annotations

import platform

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai.registry import embedding_is_degraded
from app.ai.vector_store import vector_store
from app.core.config import get_settings
from app.core.database import get_db
from app.processors import ocr
from app.schemas import (
    HealthOut,
    StatsOut,
    StorageLocationOut,
    StorageLocationUpdate,
    SystemInfoOut,
)
from app.services import stats_service, storage_service
from app.services.index_service import get_index_status

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health", response_model=HealthOut)
def health(db: Session = Depends(get_db)) -> HealthOut:
    try:
        db.execute(text("SELECT 1"))
        database_ok = True
    except Exception:  # noqa: BLE001
        database_ok = False
    qdrant_ok = vector_store.healthy()
    return HealthOut(
        status="ok" if database_ok and qdrant_ok else "degraded",
        version=get_settings().app_version,
        database=database_ok,
        qdrant=qdrant_ok,
    )


@router.get("/info", response_model=SystemInfoOut)
def info(db: Session = Depends(get_db)) -> SystemInfoOut:
    settings = get_settings()
    index_status = get_index_status(db)
    return SystemInfoOut(
        app_name=settings.app_name,
        version=settings.app_version,
        api_prefix=settings.api_prefix,
        data_dir=str(settings.data_dir),
        data_dir_custom=storage_service.current().custom,
        database=settings.db_url,
        qdrant_mode=vector_store.mode,
        qdrant_collection=settings.qdrant_collection,
        embedding_provider=settings.embedding_provider,
        embedding_model=settings.embedding_model or "未配置",
        embedding_dim=settings.embedding_dim,
        embedding_degraded=embedding_is_degraded(),
        retrieval_mode="unconfigured" if embedding_is_degraded() else "semantic",
        index_status=index_status,
        llm_configured=settings.llm_configured,
        ocr_available=ocr.is_available(),
        supported_extensions=list(settings.allowed_extensions),
        python_version=platform.python_version(),
    )


@router.get("/stats", response_model=StatsOut)
def stats(db: Session = Depends(get_db)) -> StatsOut:
    return stats_service.stats(db)


@router.get("/storage", response_model=StorageLocationOut)
def storage_info() -> StorageLocationOut:
    return storage_service.current()


@router.put("/storage", response_model=StorageLocationOut)
def update_storage(payload: StorageLocationUpdate) -> StorageLocationOut:
    return storage_service.change(payload.data_dir, payload.migrate)


@router.delete("/storage", response_model=StorageLocationOut)
def reset_storage(migrate: bool = True) -> StorageLocationOut:
    return storage_service.reset_default(migrate)

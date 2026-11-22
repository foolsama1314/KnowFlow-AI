"""系统设置接口。"""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas import (
    ModelSettingsOut,
    ModelTestRequest,
    ModelTestResult,
    SettingsOut,
    SettingsUpdate,
)
from app.services import settings_service

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsOut)
def get_settings_api() -> SettingsOut:
    return settings_service.current()


@router.put("", response_model=SettingsOut)
def update_settings(payload: SettingsUpdate) -> SettingsOut:
    return settings_service.update(payload)


@router.get("/models", response_model=ModelSettingsOut)
def get_model_settings() -> ModelSettingsOut:
    return settings_service.current().models


@router.put("/models", response_model=ModelSettingsOut)
def update_model_settings(payload: SettingsUpdate) -> ModelSettingsOut:
    return settings_service.update(SettingsUpdate(models=payload.models)).models


@router.post("/models/test", response_model=ModelTestResult)
async def test_model(payload: ModelTestRequest) -> ModelTestResult:
    return await settings_service.test_model(payload.target, payload.models)

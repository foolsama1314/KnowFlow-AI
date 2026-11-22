"""API 路由聚合。"""

from fastapi import APIRouter

from app.api import (
    analysis,
    backup,
    chat,
    documents,
    report,
    search,
    settings_api,
    system,
    tasks,
)

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(settings_api.router)
api_router.include_router(documents.router)
api_router.include_router(tasks.router)
api_router.include_router(search.router)
api_router.include_router(chat.router)
api_router.include_router(analysis.router)
api_router.include_router(report.router)
api_router.include_router(backup.router)

__all__ = ["api_router"]

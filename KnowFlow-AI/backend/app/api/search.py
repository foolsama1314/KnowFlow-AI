"""语义检索接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas import ReindexProgressOut, SearchHistoryItem, SearchRequest, SearchResponse
from app.services import search_service

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def search(request: SearchRequest, db: Session = Depends(get_db)) -> SearchResponse:
    return await search_service.search(db, request)


@router.get("/history", response_model=list[SearchHistoryItem])
def history() -> list[SearchHistoryItem]:
    return [SearchHistoryItem(**item) for item in search_service.history()]


@router.post("/reindex")
async def reindex(db: Session = Depends(get_db)) -> dict:
    return await search_service.reindex(db)


@router.get("/reindex/status", response_model=ReindexProgressOut)
def reindex_status() -> ReindexProgressOut:
    return search_service.reindex_progress()

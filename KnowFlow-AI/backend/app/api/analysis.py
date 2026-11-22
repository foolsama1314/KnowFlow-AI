"""多文档联合分析与智能总结接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas import AnalysisRequest, AnalysisResultOut
from app.services import analysis_service

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.post("", response_model=AnalysisResultOut)
async def analyze(
    payload: AnalysisRequest, db: Session = Depends(get_db)
) -> AnalysisResultOut:
    return await analysis_service.analyze(db, payload)


@router.post("/summary", response_model=AnalysisResultOut)
async def summarize(
    payload: AnalysisRequest, db: Session = Depends(get_db)
) -> AnalysisResultOut:
    payload.mode = "summary"
    return await analysis_service.summarize(db, payload)

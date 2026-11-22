"""研究报告接口：生成、历史、预览与导出。"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas import ReportRequest, ReportResultOut, ReportSummaryOut
from app.services import report_service

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("/generate", response_model=ReportResultOut)
async def generate_report(
    payload: ReportRequest, db: Session = Depends(get_db)
) -> ReportResultOut:
    return await report_service.generate(db, payload)


@router.get("", response_model=list[ReportSummaryOut])
def list_reports(limit: int = Query(20, ge=1, le=100)) -> list[ReportSummaryOut]:
    return report_service.list_reports(limit)


@router.get("/{report_id}", response_model=ReportResultOut)
def get_report(report_id: str) -> ReportResultOut:
    return report_service.get_report(report_id)


@router.get("/{report_id}/download")
def download_report(
    report_id: str, format: str = Query("md", pattern="^(md|docx)$")
) -> FileResponse:
    result = report_service.get_report(report_id)
    path = report_service.download_path(report_id, format)
    filename = f"{result.title}.{format}"
    media = (
        "text/markdown; charset=utf-8"
        if format == "md"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    return FileResponse(
        path,
        media_type=media,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )

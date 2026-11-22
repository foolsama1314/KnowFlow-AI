"""数据备份与恢复接口。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.core.errors import ProcessingError
from app.schemas import (
    BackupCreateRequest,
    BackupInfoOut,
    BackupManifestOut,
    RestoreResultOut,
)
from app.services import backup_service

router = APIRouter(prefix="/backup", tags=["backup"])

READ_CHUNK = 1024 * 1024


async def _save_upload(file: UploadFile) -> Path:
    upload_dir = get_settings().data_dir / "backups" / "_upload"
    upload_dir.mkdir(parents=True, exist_ok=True)
    name = Path(file.filename or "backup.zip").name
    if not name.lower().endswith(".zip"):
        raise ProcessingError("请选择 .zip 格式的备份文件")
    target = upload_dir / f"{uuid4().hex}.zip"
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    size = 0
    try:
        with target.open("wb") as buffer:
            while True:
                chunk = await file.read(READ_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise ProcessingError(
                        f"备份文件超过 {get_settings().max_upload_mb} MB 上限"
                    )
                buffer.write(chunk)
        if size == 0:
            raise ProcessingError("备份文件为空")
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target


@router.post("", response_model=BackupInfoOut)
async def create_backup(payload: BackupCreateRequest | None = None) -> BackupInfoOut:
    include_secrets = bool(payload.include_secrets) if payload else False
    return await asyncio.to_thread(backup_service.create_backup, include_secrets)


@router.get("", response_model=list[BackupInfoOut])
def list_backups() -> list[BackupInfoOut]:
    return backup_service.list_backups()


@router.get("/{name}/download")
def download_backup(name: str) -> FileResponse:
    path = backup_service.backup_path(name)
    return FileResponse(
        path,
        media_type="application/zip",
        filename=name,
    )


@router.post("/validate", response_model=BackupManifestOut)
async def validate_backup(file: UploadFile = File(...)) -> BackupManifestOut:
    path = await _save_upload(file)
    try:
        return await asyncio.to_thread(backup_service.validate_backup, path)
    finally:
        path.unlink(missing_ok=True)


@router.post("/restore", response_model=RestoreResultOut)
async def restore_backup(file: UploadFile = File(...)) -> RestoreResultOut:
    path = await _save_upload(file)
    try:
        return await asyncio.to_thread(backup_service.restore_backup, path)
    finally:
        path.unlink(missing_ok=True)

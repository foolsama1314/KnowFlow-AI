"""知识库备份与恢复：SQLite 一致性快照 + 上传文件 + Qdrant 数据 + 脱敏配置。

安全策略：
- 默认不包含 API Key；
- 恢复前自动备份当前数据；
- 恢复前校验 manifest 与 SHA256，失败自动回滚；
- 备份与恢复期间禁止索引写入，避免 SQLite 与 Qdrant 不一致。
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import sqlite3
import time
import zipfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.ai.registry import reset_clients
from app.ai.vector_store import vector_store
from app.core.config import get_settings, reload_settings
from app.core.database import SessionLocal, engine
from app.core.errors import AppError, ConflictError, NotFoundError, ProcessingError
from app.core.settings_store import SETTINGS_FILE
from app.models import Document, DocumentChunk, ProcessingTask
from app.schemas import BackupInfoOut, BackupManifestOut, RestoreResultOut
from app.services.index_service import INDEX_LOCK

logger = logging.getLogger(__name__)

FORMAT_VERSION = 1
SECRET_KEYS = ("llm_api_key", "embedding_api_key")
_NAME_PATTERN = r"^[A-Za-z0-9._-]+\.zip$"


def _backup_dir() -> Path:
    path = get_settings().data_dir / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _db_path() -> Path:
    settings = get_settings()
    if settings.database_url and not settings.database_url.startswith("sqlite"):
        raise ProcessingError("当前数据库不是 SQLite，无法使用内置备份功能")
    return settings.data_dir / "database" / "knowflow.db"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ensure_idle() -> None:
    db = SessionLocal()
    try:
        running = (
            db.query(ProcessingTask)
            .filter(ProcessingTask.status.in_(["pending", "running"]))
            .count()
        )
        if running:
            raise ConflictError("当前有文档处理任务正在执行，请等待任务结束后再备份或恢复")
    finally:
        db.close()


def _sqlite_snapshot(destination: Path) -> None:
    source = _db_path()
    if not source.is_file():
        raise ProcessingError("数据库文件不存在，暂时无法备份")
    destination.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(source)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _read_settings(include_secrets: bool) -> dict:
    if not SETTINGS_FILE.is_file():
        return {}
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    if not include_secrets:
        for key in SECRET_KEYS:
            data.pop(key, None)
    return data


def _export_qdrant(destination: Path) -> str:
    """本地模式直接复制文件；服务模式导出点数据，保证备份可迁移。"""
    settings = get_settings()
    if not settings.qdrant_url:
        source = settings.qdrant_local_path
        if source.is_dir():
            # Qdrant 本地模式会锁定 .lock 文件，锁文件不参与备份
            shutil.copytree(
                source,
                destination,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(".lock", "*.lock"),
            )
        return "local"

    client = vector_store.client()
    collection = settings.qdrant_collection
    points: list[dict] = []
    if client.collection_exists(collection):
        offset = None
        while True:
            batch, offset = client.scroll(
                collection_name=collection,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )
            for point in batch:
                points.append(
                    {
                        "id": str(point.id),
                        "vector": point.vector,
                        "payload": point.payload or {},
                    }
                )
            if offset is None:
                break
    destination.write_text(
        json.dumps({"collection": collection, "points": points}, ensure_ascii=False),
        encoding="utf-8",
    )
    return "server"


def _db_counts(db_file: Path) -> tuple[int, int]:
    connection = sqlite3.connect(db_file)
    try:
        documents = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        chunks = connection.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0]
    finally:
        connection.close()
    return int(documents), int(chunks)


def create_backup(include_secrets: bool = False, prefix: str = "knowflow-backup") -> BackupInfoOut:
    settings = get_settings()
    _ensure_idle()
    if not INDEX_LOCK.acquire(blocking=False):
        raise ConflictError("索引正在写入或重建，请稍后再备份")
    staging = settings.data_dir / f".backup_staging_{uuid4().hex}"
    archive_path: Path | None = None
    try:
        staging.mkdir(parents=True, exist_ok=False)

        _sqlite_snapshot(staging / "database" / "knowflow.db")
        document_count, chunk_count = _db_counts(staging / "database" / "knowflow.db")

        uploads = settings.upload_dir
        if uploads.is_dir():
            shutil.copytree(uploads, staging / "uploads", dirs_exist_ok=True)

        qdrant_mode = _export_qdrant(staging / "qdrant")

        sanitized = _read_settings(include_secrets)
        (staging / "settings.json").write_text(
            json.dumps(sanitized, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        files: list[dict] = []
        for path in sorted(staging.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(staging).as_posix()
            files.append(
                {
                    "path": relative,
                    "size": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )

        created_at = datetime.now()
        manifest = {
            "format_version": FORMAT_VERSION,
            "app_version": settings.app_version,
            "created_at": created_at.isoformat(),
            "secrets_included": include_secrets,
            "qdrant_mode": qdrant_mode,
            "collection": settings.qdrant_collection,
            "dimension": settings.embedding_dim,
            "document_count": document_count,
            "chunk_count": chunk_count,
            "files": files,
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        name = f"{prefix}-{created_at.strftime('%Y%m%d-%H%M%S')}.zip"
        archive_path = _backup_dir() / name
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(staging.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(staging).as_posix())

        logger.info(
            "备份完成：%s（%d 文档，%d 文本块，敏感信息=%s）",
            archive_path,
            document_count,
            chunk_count,
            include_secrets,
        )
        return BackupInfoOut(
            name=name,
            size=archive_path.stat().st_size,
            created_at=created_at,
            secrets_included=include_secrets,
            format_version=FORMAT_VERSION,
        )
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("备份失败")
        raise ProcessingError(f"备份失败：{exc}") from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        INDEX_LOCK.release()


def validate_backup(path: Path) -> BackupManifestOut:
    if not path.is_file():
        raise NotFoundError("备份文件不存在")
    try:
        with zipfile.ZipFile(path) as archive:
            broken = archive.testzip()
            if broken:
                raise ProcessingError(f"备份文件已损坏（{broken}）")
            names = set(archive.namelist())
            if "manifest.json" not in names:
                raise ProcessingError("备份文件缺少 manifest.json，无法校验")
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            if int(manifest.get("format_version", 0)) != FORMAT_VERSION:
                raise ProcessingError("备份格式版本不兼容，请使用相同版本的知枢 AI")
            files = manifest.get("files")
            if not isinstance(files, list) or not files:
                raise ProcessingError("备份清单为空，文件可能不完整")

            for item in files:
                name = item.get("path")
                if not name or name not in names:
                    raise ProcessingError(f"备份缺少文件：{name or '未命名'}")
                digest = hashlib.sha256()
                with archive.open(name) as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                if digest.hexdigest() != item.get("sha256"):
                    raise ProcessingError(f"备份文件校验失败：{name} 内容不一致")

            if "database/knowflow.db" not in names:
                raise ProcessingError("备份缺少数据库文件")

            with archive.open("database/knowflow.db") as handle:
                temp_db = get_settings().data_dir / f".validate_{uuid4().hex}.db"
                temp_db.write_bytes(handle.read())
            try:
                connection = sqlite3.connect(temp_db)
                try:
                    tables = {
                        row[0]
                        for row in connection.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        )
                    }
                finally:
                    connection.close()
                if "documents" not in tables:
                    raise ProcessingError("备份数据库结构不完整（缺少 documents 表）")
            finally:
                temp_db.unlink(missing_ok=True)

            return BackupManifestOut(
                name=path.name,
                format_version=int(manifest["format_version"]),
                app_version=str(manifest.get("app_version", "unknown")),
                created_at=datetime.fromisoformat(manifest["created_at"]),
                secrets_included=bool(manifest.get("secrets_included", False)),
                qdrant_mode=str(manifest.get("qdrant_mode", "local")),
                collection=str(manifest.get("collection", "")),
                dimension=int(manifest.get("dimension", 0)),
                document_count=int(manifest.get("document_count", 0)),
                chunk_count=int(manifest.get("chunk_count", 0)),
                file_count=len(files),
            )
    except ProcessingError:
        raise
    except (zipfile.BadZipFile, json.JSONDecodeError, KeyError, ValueError, OSError) as exc:
        raise ProcessingError(f"备份文件校验失败：{exc}") from exc


def _move_with_retry(source: Path, destination: Path) -> None:
    last_error: Exception | None = None
    for _ in range(30):
        try:
            source.rename(destination)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.1)
    raise ProcessingError(f"文件被占用，无法替换：{source.name}（{last_error}）")


def _restore_qdrant(staging: Path, qdrant_mode: str, dimension: int) -> None:
    settings = get_settings()
    if qdrant_mode != "server":
        return
    points_file = staging / "qdrant_points.json"
    if not points_file.is_file():
        raise ProcessingError("备份中缺少 Qdrant 点数据")
    data = json.loads(points_file.read_text(encoding="utf-8"))
    points = data.get("points", [])
    if not points:
        return
    from qdrant_client import models

    client = vector_store.client()
    collection = settings.qdrant_collection
    vector_store.drop_collection(collection)
    client.create_collection(
        collection_name=collection,
        vectors_config=models.VectorParams(size=dimension, distance=models.Distance.COSINE),
    )
    for start in range(0, len(points), 128):
        batch = points[start : start + 128]
        client.upsert(
            collection_name=collection,
            points=[
                models.PointStruct(
                    id=item["id"], vector=item["vector"], payload=item.get("payload", {})
                )
                for item in batch
            ],
            wait=True,
        )


def restore_backup(path: Path) -> RestoreResultOut:
    settings = get_settings()
    _ensure_idle()
    manifest = validate_backup(path)

    pre_restore = create_backup(include_secrets=True, prefix="pre-restore")
    if not INDEX_LOCK.acquire(blocking=False):
        raise ConflictError("索引正在写入或重建，请稍后再恢复")
    staging = settings.data_dir / f".restore_staging_{uuid4().hex}"
    old = settings.data_dir / f".restore_old_{uuid4().hex}"
    moved_old: list[tuple[Path, Path]] = []
    placed: list[Path] = []
    try:
        staging.mkdir(parents=True, exist_ok=False)
        with zipfile.ZipFile(path) as archive:
            archive.extractall(staging)

        restored_settings = {}
        settings_path = staging / "settings.json"
        if settings_path.is_file():
            restored_settings = json.loads(settings_path.read_text(encoding="utf-8"))
        current_settings = _read_settings(include_secrets=True)
        for key in SECRET_KEYS:
            if not restored_settings.get(key) and current_settings.get(key):
                restored_settings[key] = current_settings[key]

        old.mkdir(parents=True, exist_ok=False)
        engine.dispose()
        vector_store.close()

        for name in ("database", "uploads", "qdrant"):
            source = settings.data_dir / name
            if source.exists():
                target = old / name
                _move_with_retry(source, target)
                moved_old.append((source, target))

        for name in ("database", "uploads", "qdrant"):
            source = staging / name
            if not source.exists():
                continue
            target = settings.data_dir / name
            if name == "database":
                target.mkdir(parents=True, exist_ok=True)
                for leftover in target.glob("knowflow.db-*"):
                    leftover.unlink(missing_ok=True)
                source_db = source / "knowflow.db"
                if not source_db.is_file():
                    raise ProcessingError("备份数据库文件缺失")
                shutil.copy2(source_db, target / "knowflow.db")
            else:
                shutil.copytree(source, target, dirs_exist_ok=True)
            placed.append(target)

        (settings.data_dir / "settings.json").write_text(
            json.dumps(restored_settings, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        reload_settings()
        reset_clients()
        vector_store.reset()
        _restore_qdrant(staging, manifest.qdrant_mode, manifest.dimension)

        db = SessionLocal()
        try:
            document_count = db.query(Document).count()
            chunk_count = db.query(DocumentChunk).count()
        finally:
            db.close()

        shutil.rmtree(old, ignore_errors=True)
        shutil.rmtree(staging, ignore_errors=True)
        logger.info("数据恢复完成：%s（%d 文档）", path.name, document_count)
        return RestoreResultOut(
            restored=True,
            message="数据已恢复，请刷新页面查看最新内容",
            pre_restore_backup=pre_restore.name,
            document_count=int(document_count),
            chunk_count=int(chunk_count),
            qdrant_mode=manifest.qdrant_mode,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("恢复失败，开始回滚")
        try:
            engine.dispose()
            vector_store.close()
            for target in placed:
                if target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                else:
                    target.unlink(missing_ok=True)
            for source, target in moved_old:
                if target.exists() and not source.exists():
                    _move_with_retry(target, source)
            reload_settings()
            reset_clients()
            vector_store.reset()
        except Exception:  # noqa: BLE001
            logger.exception("回滚也失败，请使用预备份恢复：%s", pre_restore.name)
        message = exc.message if hasattr(exc, "message") else str(exc)
        raise ProcessingError(
            f"恢复失败：{message}。当前数据已回滚，恢复前的自动备份：{pre_restore.name}"
        ) from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        INDEX_LOCK.release()


def list_backups() -> list[BackupInfoOut]:
    directory = _backup_dir()
    items: list[BackupInfoOut] = []
    for path in sorted(directory.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with zipfile.ZipFile(path) as archive:
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            items.append(
                BackupInfoOut(
                    name=path.name,
                    size=path.stat().st_size,
                    created_at=datetime.fromisoformat(manifest["created_at"]),
                    secrets_included=bool(manifest.get("secrets_included", False)),
                    format_version=int(manifest.get("format_version", FORMAT_VERSION)),
                )
            )
        except (zipfile.BadZipFile, json.JSONDecodeError, KeyError, ValueError, OSError):
            logger.warning("跳过损坏的备份文件：%s", path)
    return items


def backup_path(name: str) -> Path:
    import re

    if not re.match(_NAME_PATTERN, name):
        raise NotFoundError("备份文件不存在")
    path = (_backup_dir() / name).resolve()
    if path.parent != _backup_dir().resolve() or not path.is_file():
        raise NotFoundError("备份文件不存在")
    return path

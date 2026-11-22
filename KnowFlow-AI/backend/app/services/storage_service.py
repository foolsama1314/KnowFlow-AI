"""数据存储位置：查看当前目录、切换自定义目录并迁移已有数据。

切换后需要重启应用才会生效，因为数据库连接与向量库在启动时按目录创建。
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from pathlib import Path

from app.core.config import (
    DEFAULT_DATA_DIR,
    clear_custom_data_dir,
    custom_data_dir,
    get_settings,
    set_custom_data_dir,
)
from app.core.database import SessionLocal
from app.core.errors import ConflictError, ProcessingError
from app.models import ProcessingTask
from app.schemas import StorageLocationOut
from app.services.index_service import INDEX_LOCK

logger = logging.getLogger(__name__)

MIGRATED_DIRS = ("uploads", "processed", "exports", "backups", "qdrant")
# 日志与 WebView 缓存属于运行时产物，不随数据迁移
_IGNORE = shutil.ignore_patterns("webview", "logs", "*.lock", ".lock")


def _current_dir() -> Path:
    return Path(get_settings().data_dir)


def current() -> StorageLocationOut:
    settings = get_settings()
    configured = custom_data_dir()
    effective = configured or Path(settings.data_dir)
    running = Path(settings.data_dir)
    pending = configured is not None and configured.resolve() != running.resolve()
    return StorageLocationOut(
        data_dir=str(effective),
        default_data_dir=str(DEFAULT_DATA_DIR),
        custom=configured is not None,
        exists=effective.is_dir(),
        restart_required=pending,
        message="存储位置已更改，重启应用后生效" if pending else "",
    )


def _ensure_idle() -> None:
    db = SessionLocal()
    try:
        running = (
            db.query(ProcessingTask)
            .filter(ProcessingTask.status.in_(["pending", "running"]))
            .count()
        )
        if running:
            raise ConflictError("当前有文档处理任务正在执行，请等待任务结束后再修改存储位置")
    finally:
        db.close()


def _check_writable(target: Path) -> None:
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / f".write_test_{os.getpid()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        raise ProcessingError(f"目标目录不可写：{target}（{exc}）") from exc


def _copy_database(source: Path, destination: Path) -> None:
    """用 SQLite 在线备份 API 复制，保证 WAL 模式下的事务一致性。"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not source.is_file():
        return
    src = sqlite3.connect(source)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _migrate(source: Path, target: Path) -> None:
    _copy_database(source / "database" / "knowflow.db", target / "database" / "knowflow.db")
    for name in MIGRATED_DIRS:
        origin = source / name
        if not origin.is_dir():
            continue
        try:
            shutil.copytree(origin, target / name, dirs_exist_ok=True, ignore=_IGNORE)
        except OSError as exc:
            raise ProcessingError(f"迁移 {name} 目录失败：{exc}") from exc
    settings_file = source / "settings.json"
    if settings_file.is_file():
        shutil.copy2(settings_file, target / "settings.json")


def change(raw_path: str, migrate: bool) -> StorageLocationOut:
    text = (raw_path or "").strip().strip('"')
    if not text:
        raise ProcessingError("请填写新的存储目录")
    candidate = Path(os.path.expandvars(text)).expanduser()
    if not candidate.is_absolute():
        raise ProcessingError("请填写完整路径，例如 D:\\知枢AI数据")

    target = candidate.resolve()
    source = _current_dir().resolve()
    if target == source:
        raise ProcessingError("该目录已是当前存储位置，无需修改")
    if target.is_relative_to(source):
        raise ProcessingError("新目录不能位于当前数据目录内部，请选择其他位置")

    _ensure_idle()
    if not INDEX_LOCK.acquire(blocking=False):
        raise ConflictError("索引正在写入或重建，请稍后再修改存储位置")
    try:
        _check_writable(target)
        if any((target / name).exists() for name in ("database", "uploads", "qdrant")):
            raise ProcessingError("目标目录已存在知识库数据，请选择一个空目录，避免覆盖")
        if migrate:
            _migrate(source, target)
        # 无论是否迁移现有数据，模型配置都跟随到新目录
        elif (source / "settings.json").is_file():
            shutil.copy2(source / "settings.json", target / "settings.json")
        set_custom_data_dir(target)
        logger.info("存储位置已切换：%s -> %s（迁移数据=%s）", source, target, migrate)
        return StorageLocationOut(
            data_dir=str(target),
            default_data_dir=str(DEFAULT_DATA_DIR),
            custom=True,
            exists=True,
            restart_required=True,
            message="存储位置已保存，请关闭并重新打开应用后生效。"
            + ("原有数据已迁移到新目录。" if migrate else "新目录为空，旧数据仍保留在原目录。"),
        )
    finally:
        INDEX_LOCK.release()


def reset_default(migrate: bool) -> StorageLocationOut:
    """恢复默认数据目录（安装目录下的 data）。"""
    target = DEFAULT_DATA_DIR.resolve()
    source = _current_dir().resolve()
    if target == source:
        raise ProcessingError("当前已使用默认存储位置")

    _ensure_idle()
    if not INDEX_LOCK.acquire(blocking=False):
        raise ConflictError("索引正在写入或重建，请稍后再修改存储位置")
    try:
        _check_writable(target)
        has_existing = (target / "database" / "knowflow.db").exists()
        # 默认目录里已有旧数据时直接回到旧数据，避免覆盖；否则把当前数据迁移过去
        if migrate and not has_existing:
            _migrate(source, target)
        clear_custom_data_dir()
        logger.info("存储位置已恢复默认：%s -> %s", source, target)
        return StorageLocationOut(
            data_dir=str(target),
            default_data_dir=str(DEFAULT_DATA_DIR),
            custom=False,
            exists=True,
            restart_required=True,
            message="已恢复默认存储位置，请关闭并重新打开应用后生效。"
            + ("将使用默认目录中原有的数据。" if has_existing else "当前数据已迁移到默认目录。"),
        )
    finally:
        INDEX_LOCK.release()

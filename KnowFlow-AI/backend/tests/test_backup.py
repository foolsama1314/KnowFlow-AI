"""备份与恢复测试：临时数据目录、真实 SQLite、校验与回滚。"""

from __future__ import annotations

import json
import zipfile
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.errors import NotFoundError, ProcessingError
from app.models import Base, Document
from app.services import backup_service


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    (data_dir / "database").mkdir(parents=True)
    (data_dir / "uploads").mkdir()
    (data_dir / "qdrant").mkdir()
    (data_dir / "exports").mkdir()
    db_file = data_dir / "database" / "knowflow.db"

    engine = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    session.add(
        Document(
            name="示例",
            original_name="示例.pdf",
            file_type="pdf",
            file_size=10,
            file_path="uploads/a.txt",
            file_hash="hash-a",
            status="completed",
            page_count=1,
            chunk_count=0,
        )
    )
    session.commit()
    session.close()
    engine.dispose()

    (data_dir / "uploads" / "a.txt").write_text("原始文件", encoding="utf-8")
    (data_dir / "qdrant" / "meta.json").write_text("{}", encoding="utf-8")

    settings_file = data_dir / "settings.json"
    settings_file.write_text(
        json.dumps(
            {
                "llm_api_key": "secret-llm",
                "embedding_api_key": "secret-embedding",
                "chunk_size": 800,
                "rag_min_score": 0.4,
            }
        ),
        encoding="utf-8",
    )

    settings = SimpleNamespace(
        data_dir=data_dir,
        database_url="",
        qdrant_url="",
        qdrant_local_path=data_dir / "qdrant",
        upload_dir=data_dir / "uploads",
        export_dir=data_dir / "exports",
        app_version="test",
        embedding_dim=8,
        qdrant_collection="document_chunks",
        max_upload_mb=50,
    )

    def fake_session_local():
        local_engine = create_engine(f"sqlite:///{db_file.as_posix()}")
        return sessionmaker(bind=local_engine, expire_on_commit=False)()

    monkeypatch.setattr(backup_service, "get_settings", lambda: settings)
    monkeypatch.setattr(backup_service, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(backup_service, "_ensure_idle", lambda: None)
    monkeypatch.setattr(backup_service, "reload_settings", lambda: None)
    monkeypatch.setattr(backup_service, "reset_clients", lambda: None)
    monkeypatch.setattr(backup_service, "engine", SimpleNamespace(dispose=lambda: None))
    monkeypatch.setattr(
        backup_service,
        "vector_store",
        SimpleNamespace(close=lambda: None, reset=lambda: None),
    )
    monkeypatch.setattr(backup_service, "SessionLocal", fake_session_local)
    return SimpleNamespace(data_dir=data_dir, db_file=db_file, settings_file=settings_file)


def _document_count(db_file) -> int:
    engine = create_engine(f"sqlite:///{db_file.as_posix()}")
    factory = sessionmaker(bind=engine)
    session = factory()
    try:
        return session.query(Document).count()
    finally:
        session.close()
        engine.dispose()


def test_backup_excludes_secrets_by_default(workspace):
    backup = backup_service.create_backup(include_secrets=False)

    assert backup.secrets_included is False
    archive_path = workspace.data_dir / "backups" / backup.name
    assert archive_path.is_file()
    with zipfile.ZipFile(archive_path) as archive:
        stored = json.loads(archive.read("settings.json").decode("utf-8"))
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
    assert "llm_api_key" not in stored
    assert "embedding_api_key" not in stored
    assert stored["chunk_size"] == 800
    assert manifest["format_version"] == 1
    assert manifest["document_count"] == 1
    assert manifest["qdrant_mode"] == "local"

    manifest_out = backup_service.validate_backup(archive_path)
    assert manifest_out.name == backup.name
    assert manifest_out.document_count == 1
    assert manifest_out.secrets_included is False


def test_backup_can_include_secrets(workspace):
    backup = backup_service.create_backup(include_secrets=True)
    archive_path = workspace.data_dir / "backups" / backup.name
    with zipfile.ZipFile(archive_path) as archive:
        stored = json.loads(archive.read("settings.json").decode("utf-8"))
    assert stored["llm_api_key"] == "secret-llm"


def test_corrupted_backup_rejected(workspace):
    bad = workspace.data_dir / "backups" / "broken.zip"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(b"not a zip file")
    with pytest.raises(ProcessingError):
        backup_service.validate_backup(bad)


def test_backup_path_traversal_rejected(workspace):
    with pytest.raises(NotFoundError):
        backup_service.backup_path("../settings.json")
    with pytest.raises(NotFoundError):
        backup_service.backup_path("missing.zip")


def test_restore_recovers_data_and_keeps_current_keys(workspace):
    backup = backup_service.create_backup(include_secrets=False)
    archive_path = workspace.data_dir / "backups" / backup.name

    # 备份之后制造差异：新增文档、上传文件，并修改本机密钥
    engine = create_engine(f"sqlite:///{workspace.db_file.as_posix()}")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    session.add(
        Document(
            name="新增",
            original_name="新增.pdf",
            file_type="pdf",
            file_size=10,
            file_path="uploads/b.txt",
            file_hash="hash-b",
            status="completed",
            page_count=1,
            chunk_count=0,
        )
    )
    session.commit()
    session.close()
    engine.dispose()
    (workspace.data_dir / "uploads" / "b.txt").write_text("新增文件", encoding="utf-8")
    workspace.settings_file.write_text(
        json.dumps({"llm_api_key": "current-key", "chunk_size": 400}), encoding="utf-8"
    )
    assert _document_count(workspace.db_file) == 2

    result = backup_service.restore_backup(archive_path)

    assert result.restored is True
    assert result.document_count == 1
    assert _document_count(workspace.db_file) == 1
    assert (workspace.data_dir / "uploads" / "a.txt").is_file()
    assert not (workspace.data_dir / "uploads" / "b.txt").exists()
    assert (workspace.data_dir / "qdrant" / "meta.json").is_file()

    restored_settings = json.loads(workspace.settings_file.read_text(encoding="utf-8"))
    assert restored_settings["llm_api_key"] == "current-key"
    assert restored_settings["chunk_size"] == 800

    backups = {item.name for item in backup_service.list_backups()}
    assert result.pre_restore_backup in backups

    with pytest.raises(NotFoundError):
        backup_service.backup_path("../../secret.zip")

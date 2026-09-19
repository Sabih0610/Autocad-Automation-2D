import pytest
from src.logging import db


@pytest.fixture(autouse=True)
def isolated_jobs_db(tmp_path, tmp_path_factory, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "jobs.db")
    from src import backup
    monkeypatch.setattr(backup, "BACKUP_ROOT", tmp_path_factory.mktemp("cad-backups"))

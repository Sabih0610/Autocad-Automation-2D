import pytest

from src.logging import db


@pytest.fixture(autouse=True)
def isolated_api_storage(tmp_path, tmp_path_factory, monkeypatch):
    """Keep API tests away from the live audit database and CAD backups."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "jobs.db")

    from src import backup

    monkeypatch.setattr(
        backup,
        "BACKUP_ROOT",
        tmp_path_factory.mktemp("api-cad-backups"),
    )

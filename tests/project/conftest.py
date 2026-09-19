import pytest
from src.logging import db


@pytest.fixture(autouse=True)
def isolated_jobs_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "jobs.db")

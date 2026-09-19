import sqlite3
import pytest
from src.logging import db
from src.storage.database import connection
from src.storage.project_repository import register_project, list_projects, get_project


def test_register_and_list_without_scanning(tmp_path):
    project = register_project("Plant", str(tmp_path))
    assert list_projects() == [project]
    assert get_project(project["project_id"]) == project
    with connection() as conn:
        assert conn.execute("SELECT count(*) FROM drawings").fetchone()[0] == 0


def test_schema_is_additive_idempotent_and_wal(tmp_path):
    original = db.get_connection()
    before = list(original.execute("PRAGMA table_info(jobs)"))
    original.close()
    for _ in range(2):
        with connection() as conn:
            assert list(conn.execute("PRAGMA table_info(jobs)")) == before
            assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            assert conn.execute("SELECT count(*) FROM validation_results").fetchone()[0] == 0


def test_registration_rejects_invalid_and_duplicate_roots(tmp_path):
    with pytest.raises(ValueError):
        register_project("", str(tmp_path))
    with pytest.raises(FileNotFoundError):
        register_project("Plant", str(tmp_path / "absent"))
    register_project("Plant", str(tmp_path))
    with pytest.raises(sqlite3.IntegrityError):
        register_project("Duplicate", str(tmp_path / "."))
    with pytest.raises(KeyError):
        get_project("missing")

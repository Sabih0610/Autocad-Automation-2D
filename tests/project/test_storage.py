import sqlite3
import pytest
from src.logging import db
from src.storage.database import connection
from src.storage.project_repository import register_project, list_projects, get_project


def test_register_and_list_without_scanning(tmp_path):
    project_id = register_project("Plant", str(tmp_path))
    assert isinstance(project_id, str) and project_id
    project = get_project(project_id)
    assert list_projects() == [project]
    assert project["project_id"] == project_id
    assert project["name"] == "Plant"
    assert project["root_path"] == str(tmp_path.resolve())
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


def test_all_roadmap_tables_share_the_existing_jobs_database():
    required = {"projects", "drawings", "entities", "entity_properties", "entity_geometry",
                "relationships", "jobs_multi_file", "job_items", "change_sets",
                "change_set_items", "validation_results"}
    with connection() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert required | {"jobs"} <= tables
        databases = list(conn.execute("PRAGMA database_list"))
        assert len(databases) == 1
        assert databases[0][1] == "main"
        from pathlib import Path
        assert Path(databases[0][2]).resolve() == db.DB_PATH.resolve()


def test_initialization_preserves_existing_audit_schema_rows_and_logging(tmp_path):
    from src.logging.jobs import log_job_start, log_job_end, get_job
    job_id = log_job_start("step1-regression", "test", {"input": "retained"})
    original_job = get_job(job_id)
    audit = db.get_connection()
    try:
        original_schema = [tuple(row) for row in audit.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE tbl_name='jobs' ORDER BY name")]
    finally:
        audit.close()
    register_project("Plant", str(tmp_path))
    assert get_job(job_id) == original_job
    with connection() as conn:
        assert [tuple(row) for row in conn.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE tbl_name='jobs' ORDER BY name")] == original_schema
    log_job_end(job_id, "success", result_data={"result": "retained"})
    completed = get_job(job_id)
    assert completed["status"] == "success"
    assert completed["request_data"] == {"input": "retained"}
    assert completed["result_data"] == {"result": "retained"}
    assert completed["timestamp_end"] is not None


def test_list_projects_persists_multiple_registrations(tmp_path):
    assert list_projects() == []
    first = register_project("First", str(tmp_path))
    second_root = tmp_path / "second"
    second_root.mkdir()
    second = register_project("Second", str(second_root))
    assert first != second
    assert {project["project_id"] for project in list_projects()} == {first, second}

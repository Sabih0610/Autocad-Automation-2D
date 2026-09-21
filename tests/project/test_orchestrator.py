"""The project planner narrows scope before one mocked AI call or CAD write."""
import json
import threading

import ezdxf
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ai import project_planner
from src.cad.changes import ChangeManager
from src.cad.extractor import DXFExtractor
from src.cad.orchestrator import ProjectOrchestrator, get_multi_file_job
from src.cad.scanner import scan_project
from src.framework.commands import modification_executor as engine
from src.storage.database import connection
from src.storage.project_repository import register_project
from tests.project.fake_cad import Acad
from tests.project.test_extractor import make_dxf


def test_ten_drawings_plan_three_items_with_one_small_ai_prompt(tmp_path, monkeypatch):
    paths, handles = [], {}
    for index in range(10):
        path = tmp_path / f"drawing-{index:02}.dxf"
        handle = make_dxf(path)
        handles[path] = handle
        if index >= 3:
            doc = ezdxf.readfile(path)
            doc.entitydb[handle].set_xdata("AUTOCAD_AI", [(1000, f"TAG=OTHER-{index}")])
            doc.saveas(path)
        paths.append(path)
    project_id = register_project("Plant", str(tmp_path))
    assert scan_project(project_id, max_workers=1)["extracted"] == 10
    original = {path: path.read_bytes() for path in paths}

    ai_calls = []
    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1, max_tokens=None):
        ai_calls.append(dict(prompt=prompt, schema=schema, system_prompt=system_prompt,
                             max_retries=max_retries, max_tokens=max_tokens))
        return {"command": "RESIZE_COMPONENT", "dimension": "length", "delta_mm": 50}

    monkeypatch.setattr(project_planner, "ask_ai", fake_ask_ai)
    acad = Acad()
    manager = ChangeManager(acad=acad)
    writer_threads = []
    original_apply = manager.apply
    def traced_apply(*args, **kwargs):
        writer_threads.append(threading.current_thread().name)
        return original_apply(*args, **kwargs)
    manager.apply = traced_apply
    orchestrator = ProjectOrchestrator(manager=manager)

    job = orchestrator.plan(project_id, "increase P-101 by 50mm everywhere")
    assert len(ai_calls) == 1
    assert ai_calls[0]["schema"] == project_planner.PLAN_SCHEMA
    assert ai_calls[0]["max_tokens"] == 500
    prompt = ai_calls[0]["prompt"]
    record = json.loads(prompt.split("One selected indexed record:\n", 1)[1])
    assert record["tag"] == "P-101"
    assert record["occurrence_count"] == 3
    assert record["connection_count"] == 1
    assert set(record) <= {"tag", "entity_type", "handle", "units", "start_x", "start_y",
                           "start_z", "end_x", "end_y", "end_z", "occurrence_count",
                           "connection_count", "filename"}
    assert len(json.dumps(record)) < 500
    assert sum(path.name in prompt for path in paths[:3]) == 1
    assert all(path.name not in prompt for path in paths[3:])
    assert "entities" not in prompt and "properties" not in prompt

    assert len(job["items"]) == 3
    assert len({item["drawing_id"] for item in job["items"]}) == 3
    with connection() as conn:
        matching = {row[0] for row in conn.execute(
            "SELECT DISTINCT drawing_id FROM entities WHERE tag='P-101'")}
        assert {item["drawing_id"] for item in job["items"]} == matching
        assert conn.execute("SELECT count(*) FROM job_items WHERE job_id=?", (job["job_id"],)).fetchone()[0] == 3

    done = orchestrator.execute(job["job_id"])
    assert len(ai_calls) == 1
    assert done["status"] == "done"
    assert [item["status"] for item in done["items"]] == ["done"] * 3
    assert len(writer_threads) == 1 and writer_threads[0].startswith("cad-writer")
    assert set(acad.Documents.opened) == {str(path) for path in paths[:3]}
    assert all(path.read_bytes() == original[path] for path in paths[3:])
    assert all(DXFExtractor().extract_properties(path)[handles[path]]["end"] == [1050, 0, 0]
               for path in paths[:3])

    change = done["change_set"]
    assert change["status"] == "pending"
    assert len(change["files"]) == 3
    assert {item["drawing_id"] for item in change["files"]} == matching
    assert manager.revert(change["change_set_id"])["status"] == "reverted"
    assert all(path.read_bytes() == original[path] for path in paths)


def test_duplicate_tag_in_one_drawing_is_rejected_before_ai_or_job(tmp_path):
    path = tmp_path / "duplicate.dxf"
    make_dxf(path)
    doc = ezdxf.readfile(path)
    extra = doc.modelspace().add_line((0, 100, 0), (1000, 100, 0))
    extra.set_xdata("AUTOCAD_AI", [(1000, "TAG=P-101")])
    doc.saveas(path)
    project_id = register_project("Plant", str(tmp_path))
    scan_project(project_id, max_workers=1)
    def forbidden(*args):
        pytest.fail("An ambiguous tag must not call the AI")
    orchestrator = ProjectOrchestrator(planner=forbidden, manager=ChangeManager(acad=Acad()))
    with pytest.raises(ValueError, match="multiple entities"):
        orchestrator.plan(project_id, "increase P-101 by 50mm everywhere")
    with connection() as conn:
        assert conn.execute("SELECT count(*) FROM jobs_multi_file").fetchone()[0] == 0


def test_reconcile_recovers_a_job_stranded_by_a_process_crash(tmp_path, monkeypatch):
    """`_execute` claims a job by flipping it from 'pending' to 'running'
    *before* doing any of the actual work. If the process dies right there
    (a crash, not a caught exception, which would already mark it 'error'),
    the job is stuck at 'running' forever: a later `execute(job_id)` call
    can never claim it again, because claiming only matches
    status='pending'. `reconcile_interrupted_jobs`, called once at process
    startup, must recover it."""
    path = tmp_path / "a.dxf"
    handle = make_dxf(path)
    project_id = register_project("Plant", str(tmp_path))
    scan_project(project_id, max_workers=1)

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1, max_tokens=None):
        return {"command": "RESIZE_COMPONENT", "dimension": "length", "delta_mm": 50}
    monkeypatch.setattr(project_planner, "ask_ai", fake_ask_ai)

    orchestrator = ProjectOrchestrator(manager=ChangeManager(acad=Acad()))
    job = orchestrator.plan(project_id, "increase P-101 by 50mm")
    job_id = job["job_id"]

    # Simulate the exact moment a crash would strand the job: claimed, but
    # nothing has actually run yet.
    with connection() as conn:
        conn.execute("UPDATE jobs_multi_file SET status='running' WHERE job_id=?", (job_id,))
        conn.execute("UPDATE job_items SET status='running' WHERE job_id=?", (job_id,))

    with pytest.raises(ValueError, match="already executing"):
        orchestrator.execute(job_id)

    from src.cad.orchestrator import reconcile_interrupted_jobs
    recovered = reconcile_interrupted_jobs()
    assert job_id in recovered

    reconciled = get_multi_file_job(job_id)
    assert reconciled["status"] == "error"
    assert all(item["status"] == "error" for item in reconciled["items"])
    assert all("Interrupted by a process restart" in item["error"] for item in reconciled["items"])

    # A genuinely-pending job (never claimed) must be untouched by
    # reconciliation — only "running" rows are stale-by-definition here.
    other_job = orchestrator.plan(project_id, "increase P-101 by 25mm")
    assert reconcile_interrupted_jobs() == []
    assert get_multi_file_job(other_job["job_id"])["status"] == "pending"


def test_plan_rejects_invalid_radius_before_creating_a_job(tmp_path, monkeypatch):
    """Length resizing was validated for positivity at plan time (before
    any job row exists), but radius resizing was not — an invalid radius
    was only ever caught later, at execute time, by which point sibling
    job items in the same multi-file job may have already run and been
    persisted. This proves the radius check now runs at plan time too,
    symmetrically with the existing length check."""
    path = tmp_path / "a.dxf"
    doc = ezdxf.new()
    doc.units = 4
    circle = doc.modelspace().add_circle((500, 500, 0), 10)
    circle.set_xdata("AUTOCAD_AI", [(1000, "TAG=C-101")])
    doc.saveas(path)
    project_id = register_project("Plant", str(tmp_path))
    scan_project(project_id, max_workers=1)

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1, max_tokens=None):
        return {"command": "RESIZE_COMPONENT", "dimension": "radius", "delta_mm": -50}
    monkeypatch.setattr(project_planner, "ask_ai", fake_ask_ai)

    orchestrator = ProjectOrchestrator(manager=ChangeManager(acad=Acad()))
    with pytest.raises(ValueError, match="Planned radius must be positive"):
        orchestrator.plan(project_id, "shrink C-101 by 50mm")

    with connection() as conn:
        assert conn.execute("SELECT count(*) FROM jobs_multi_file").fetchone()[0] == 0


def test_project_http_plan_execute_and_keep(tmp_path, monkeypatch):
    from src.api.routes import projects as project_routes, changes as change_routes
    path = tmp_path / "one.dxf"
    make_dxf(path)
    project_id = register_project("Plant", str(tmp_path))
    scan_project(project_id, max_workers=1)
    monkeypatch.setattr(project_planner, "ask_ai", lambda **kwargs: {
        "command": "RESIZE_COMPONENT", "dimension": "length", "delta_mm": 50})
    manager = ChangeManager(acad=Acad())
    orchestrator = ProjectOrchestrator(manager=manager)
    monkeypatch.setattr(project_routes, "orchestrator", lambda: orchestrator)
    monkeypatch.setattr(change_routes, "manager", lambda: manager)
    app = FastAPI()
    app.include_router(project_routes.router)
    app.include_router(change_routes.router)
    client = TestClient(app)

    response = client.post(f"/api/projects/{project_id}/plan", json={
        "prompt": "increase P-101 by 50mm everywhere"})
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    assert len(response.json()["items"]) == 1
    applied = client.post(f"/api/projects/jobs/{job_id}/execute")
    assert applied.status_code == 200
    change_id = applied.json()["change_set"]["change_set_id"]
    saved = path.read_bytes()
    kept = client.post(f"/api/change-sets/{change_id}/keep")
    assert kept.status_code == 200 and kept.json()["status"] == "kept"
    assert path.read_bytes() == saved


def test_new_readonly_project_routes_are_audit_logged(tmp_path):
    """`GET /api/autocad/inspect` was already audited, but the newer
    read-only project routes (`drawings`, `entities`, `nearby`,
    `change-sets`, job lookup) weren't in `AUDIT_ROUTE_MAP` at all — every
    call to them was invisible to the jobs.db audit trail. Uses the real
    `app` (not a scoped-down one) since `AUDIT_ROUTE_MAP` and its
    middleware live in main.py, not in the router itself."""
    from src.api.main import app as real_app
    from src.logging.jobs import list_recent_jobs

    path = tmp_path / "a.dxf"
    make_dxf(path)
    project_id = register_project("Plant", str(tmp_path))
    scan_project(project_id, max_workers=1)

    client = TestClient(real_app)
    response = client.get(f"/api/projects/{project_id}/drawings")
    assert response.status_code == 200

    jobs = list_recent_jobs(use_case="project_drawings")
    assert len(jobs) == 1
    assert jobs[0]["status"] == "ok"


def test_projects_respond_maps_operational_error_to_409_not_500(tmp_path, monkeypatch):
    """Neither `respond()` helper (routes/projects.py, routes/changes.py)
    caught `sqlite3.OperationalError` (e.g. a lock timeout) — it fell
    through as a raw, unmapped 500 instead of the clean 409 every other
    "the requested operation can't proceed right now" case gets."""
    import sqlite3
    from src.api.routes import projects as project_routes

    project_id = register_project("Plant", str(tmp_path))

    def boom(project_id):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(project_routes, "list_drawings", boom)
    app = FastAPI()
    app.include_router(project_routes.router)
    client = TestClient(app)

    response = client.get(f"/api/projects/{project_id}/drawings")
    assert response.status_code == 409


def test_changes_respond_maps_operational_and_integrity_errors_to_409(monkeypatch):
    """`routes/changes.py`'s `respond()` disagreed with `routes/projects.py`'s
    on which exception types it caught — missing both `sqlite3.
    OperationalError` and `sqlite3.IntegrityError`. Both should now map to
    409, matching routes/projects.py."""
    import sqlite3
    from src.api.routes import changes as change_routes

    app = FastAPI()
    app.include_router(change_routes.router)
    client = TestClient(app)

    for error in (sqlite3.OperationalError("database is locked"), sqlite3.IntegrityError("constraint failed")):
        def boom(change_id, _error=error):
            raise _error
        monkeypatch.setattr(change_routes, "get_change_set", boom)
        response = client.get("/api/change-sets/some-id")
        assert response.status_code == 409

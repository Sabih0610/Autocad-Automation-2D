from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api import main as main_module
from src.api.routes import pid as pid_routes
from src.logging.jobs import list_recent_jobs


@pytest.fixture(autouse=True)
def clear_pid_cache():
    pid_routes._PID_CACHE.clear()
    yield
    pid_routes._PID_CACHE.clear()


def _only_job() -> dict:
    jobs = list_recent_jobs()
    assert len(jobs) == 1
    return jobs[0]


def test_validation_error_closes_audit_job() -> None:
    response = TestClient(main_module.app).post(
        "/api/pid/generate",
        json={"nope": 1},
    )

    assert response.status_code == 422
    job = _only_job()
    assert job["status"] == "error"
    assert job["timestamp_end"] is not None
    assert job["error_message"] == "HTTP 422"


@pytest.mark.parametrize("response_status", [404, 405])
def test_router_error_closes_audit_job(response_status: int) -> None:
    async def router_error(_scope, _receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": response_status,
                "headers": [],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    response = TestClient(main_module.AuditJobMiddleware(router_error)).get(
        "/api/pid/generate"
    )

    assert response.status_code == response_status
    job = _only_job()
    assert job["status"] == "error"
    assert job["timestamp_end"] is not None
    assert job["error_message"] == f"HTTP {response_status}"


def test_successful_wrapped_endpoint_closes_audit_job_once(monkeypatch) -> None:
    planned = {
        "component_scene": {
            "title": "Test P&ID",
            "drawing_type": "P&ID",
            "assumptions": [],
        },
        "command_sequence": {"summary": "Test P&ID", "commands": []},
        "component_count": 0,
        "planner_strategy": "test",
        "fallback_used": False,
        "fallback_reason": None,
        "template_name": None,
    }
    monkeypatch.setattr(
        pid_routes,
        "plan_and_render_pid_component_scene_resilient",
        lambda *_args, **_kwargs: planned,
    )

    end_calls: list[str] = []
    real_log_job_end = main_module.log_job_end

    def counting_log_job_end(job_id, *args, **kwargs):
        end_calls.append(job_id)
        return real_log_job_end(job_id, *args, **kwargs)

    monkeypatch.setattr(main_module, "log_job_end", counting_log_job_end)

    response = TestClient(main_module.app).post(
        "/api/pid/generate",
        json={"prompt": "Draw a test P&ID."},
    )

    assert response.status_code == 200
    job = _only_job()
    assert end_calls == [job["job_id"]]
    assert job["status"] == "ok"
    assert job["timestamp_end"] is not None


def test_raised_endpoint_error_closes_audit_job() -> None:
    async def failing_endpoint(_scope, _receive, _send):
        raise RuntimeError("endpoint exploded")

    client = TestClient(main_module.AuditJobMiddleware(failing_endpoint))

    with pytest.raises(RuntimeError, match="endpoint exploded"):
        client.post("/api/pid/generate", json={"prompt": "Draw a P&ID."})

    job = _only_job()
    assert job["status"] == "error"
    assert job["timestamp_end"] is not None
    assert job["error_message"] == "endpoint exploded"

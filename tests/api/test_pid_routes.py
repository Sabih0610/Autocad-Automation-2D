from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.routes import pid as pid_routes
from src.parametric.vessel.dwg_export import AutoCADNotRunningError


FAKE_COMPONENT_SCENE = {
    "schema_version": "1.0",
    "title": "AI Planned P&ID",
    "drawing_type": "P&ID",
    "assumptions": ["Used clean schematic layout."],
    "components": [
        {
            "component_type": "horizontal_vessel",
            "id": "V201",
            "tag": "V-201",
            "center": [0, 0],
            "length": 3200,
            "diameter": 800,
        }
    ],
}


FAKE_COMMAND_SEQUENCE = {
    "schema_version": "1.0",
    "summary": "P&ID component scene: AI Planned P&ID",
    "estimated_drawing_type": "P&ID schematic",
    "assumptions": ["Generated from reusable P&ID components."],
    "commands": [
        {"command": "LAYER", "layer_name": "PID_EQUIPMENT"},
        {"command": "LINE", "from": [0, 0], "to": [100, 0], "layer": "PID_EQUIPMENT"},
    ],
}


FAKE_PLANNED_RESULT = {
    "ok": True,
    "component_scene": FAKE_COMPONENT_SCENE,
    "command_sequence": FAKE_COMMAND_SEQUENCE,
    "component_count": 1,
    "planner_strategy": "ai_component_planner",
    "fallback_used": False,
    "fallback_reason": None,
    "template_name": None,
}


FAKE_FALLBACK_PLANNED_RESULT = {
    **FAKE_PLANNED_RESULT,
    "component_scene": {
        **FAKE_COMPONENT_SCENE,
        "metadata": {
            "planner_strategy": "template_fallback",
            "fallback_used": True,
            "fallback_reason": "RuntimeError: invalid JSON",
            "template_name": "horizontal_separator",
        },
    },
    "planner_strategy": "template_fallback",
    "fallback_used": True,
    "fallback_reason": "RuntimeError: invalid JSON",
    "template_name": "horizontal_separator",
}


FAKE_EXECUTION_RESULT = {
    "ok": True,
    "executed_count": 2,
    "total_count": 2,
    "errors": [],
    "dwg_path": "",
    "document_name": "Drawing1.dwg",
    "entity_count_before": 0,
    "entity_count_after": 2,
    "zoom_extents_called": True,
    "zoom_error": None,
}


@pytest.fixture(autouse=True)
def clear_pid_cache():
    pid_routes._PID_CACHE.clear()
    yield
    pid_routes._PID_CACHE.clear()


@pytest.fixture
def client():
    return TestClient(app)


def _patch_planner(
    monkeypatch,
    captured: dict | None = None,
    error: Exception | None = None,
    result: dict | None = None,
):
    captured = captured if captured is not None else {}
    captured.setdefault("planner_calls", [])

    def fake_plan_and_render(
        prompt,
        drawing_style="clean schematic P&ID",
        allow_template_fallback=True,
        template_first=False,
    ):
        captured["planner_calls"].append(
            {
                "prompt": prompt,
                "drawing_style": drawing_style,
                "allow_template_fallback": allow_template_fallback,
                "template_first": template_first,
            }
        )
        if error is not None:
            raise error
        return result or FAKE_PLANNED_RESULT

    monkeypatch.setattr(pid_routes, "plan_and_render_pid_component_scene_resilient", fake_plan_and_render)
    return captured


def _patch_executor(monkeypatch, captured: dict | None = None, error: Exception | None = None):
    captured = captured if captured is not None else {}
    captured.setdefault("execute_calls", [])

    def fake_execute(command_sequence, target_dwg_path=None, save=True, zoom_extents=True):
        captured["execute_calls"].append(
            {
                "command_sequence": command_sequence,
                "target_dwg_path": target_dwg_path,
                "save": save,
                "zoom_extents": zoom_extents,
            }
        )
        if error is not None:
            raise error
        return FAKE_EXECUTION_RESULT

    monkeypatch.setattr(pid_routes, "execute_command_sequence", fake_execute)
    return captured


def _generate(client, monkeypatch, payload: dict | None = None, captured: dict | None = None):
    captured = _patch_planner(monkeypatch, captured)
    response = client.post(
        "/api/pid/generate",
        json=payload or {"prompt": "Draw a separator P&ID."},
    )
    return response, captured


def test_pid_generate_with_valid_prompt_returns_200(client, monkeypatch) -> None:
    response, _captured = _generate(client, monkeypatch)

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_pid_generate_calls_planner(client, monkeypatch) -> None:
    response, captured = _generate(
        client,
        monkeypatch,
        payload={
            "prompt": "  Draw a separator P&ID.  ",
            "drawing_style": "company schematic",
        },
    )

    assert response.status_code == 200
    assert captured["planner_calls"] == [
        {
            "prompt": "Draw a separator P&ID.",
            "drawing_style": "company schematic",
            "allow_template_fallback": True,
            "template_first": False,
        }
    ]


def test_pid_generate_response_includes_token(client, monkeypatch) -> None:
    response, _captured = _generate(client, monkeypatch)

    assert response.json()["token"]


def test_pid_generate_response_includes_component_scene(client, monkeypatch) -> None:
    response, _captured = _generate(client, monkeypatch)

    assert response.json()["component_scene"] == FAKE_COMPONENT_SCENE


def test_pid_generate_response_includes_component_and_command_counts(client, monkeypatch) -> None:
    response, _captured = _generate(client, monkeypatch)
    data = response.json()

    assert data["component_count"] == 1
    assert data["command_count"] == 2


def test_pid_generate_response_includes_planner_fallback_metadata(client, monkeypatch) -> None:
    response, _captured = _generate(client, monkeypatch)
    data = response.json()

    assert data["planner_strategy"] == "ai_component_planner"
    assert data["fallback_used"] is False
    assert data["fallback_reason"] is None
    assert data["template_name"] is None


def test_pid_generate_with_empty_prompt_returns_400(client, monkeypatch) -> None:
    _patch_planner(monkeypatch)

    response = client.post("/api/pid/generate", json={"prompt": "   "})

    assert response.status_code == 400


def test_pid_generate_planner_value_error_returns_400(client, monkeypatch) -> None:
    _patch_planner(monkeypatch, error=ValueError("bad component scene"))

    response = client.post("/api/pid/generate", json={"prompt": "Draw P&ID."})

    assert response.status_code == 400
    assert "bad component scene" in response.json()["detail"]


def test_pid_generate_planner_generic_exception_returns_502(client, monkeypatch) -> None:
    _patch_planner(monkeypatch, error=RuntimeError("provider failed"))

    response = client.post("/api/pid/generate", json={"prompt": "Draw P&ID."})

    assert response.status_code == 502
    assert response.json()["detail"].startswith("P&ID component planning failed:")


def test_pid_generate_fallback_result_returns_200_and_token(client, monkeypatch) -> None:
    captured = _patch_planner(monkeypatch, result=FAKE_FALLBACK_PLANNED_RESULT)

    response = client.post("/api/pid/generate", json={"prompt": "Draw P&ID."})

    data = response.json()
    assert response.status_code == 200
    assert data["token"]
    assert data["planner_strategy"] == "template_fallback"
    assert data["fallback_used"] is True
    assert data["fallback_reason"] == "RuntimeError: invalid JSON"
    assert data["template_name"] == "horizontal_separator"
    assert captured["planner_calls"][0]["allow_template_fallback"] is True
    assert captured["planner_calls"][0]["template_first"] is False


def test_pid_approve_with_token_calls_executor(client, monkeypatch) -> None:
    response, captured = _generate(client, monkeypatch)
    token = response.json()["token"]
    _patch_executor(monkeypatch, captured)

    approve_response = client.post("/api/pid/approve", json={"token": token})

    assert approve_response.status_code == 200
    assert len(captured["execute_calls"]) == 1
    assert captured["execute_calls"][0]["command_sequence"] == FAKE_COMMAND_SEQUENCE
    assert captured["execute_calls"][0]["zoom_extents"] is True


def test_pid_approve_response_includes_execution_result(client, monkeypatch) -> None:
    response, captured = _generate(client, monkeypatch)
    token = response.json()["token"]
    _patch_executor(monkeypatch, captured)

    approve_response = client.post("/api/pid/approve", json={"token": token})

    data = approve_response.json()
    assert data["execution_result"] == FAKE_EXECUTION_RESULT
    assert data["component_count"] == 1
    assert data["command_count"] == 2
    assert data["title"] == "AI Planned P&ID"


def test_pid_approve_token_is_consumed_on_success_and_cannot_replay(client, monkeypatch) -> None:
    """`_PID_CACHE` never expires entries on its own — before this fix, the
    same token could be approved (re-executed into AutoCAD) an unlimited
    number of times. A successful approve must consume its token."""
    response, captured = _generate(client, monkeypatch)
    token = response.json()["token"]
    _patch_executor(monkeypatch, captured)

    first = client.post("/api/pid/approve", json={"token": token})
    assert first.status_code == 200
    assert len(captured["execute_calls"]) == 1

    replay = client.post("/api/pid/approve", json={"token": token})
    assert replay.status_code == 404
    assert len(captured["execute_calls"]) == 1  # not executed a second time


def test_pid_approve_missing_token_returns_404(client, monkeypatch) -> None:
    _patch_executor(monkeypatch)

    response = client.post("/api/pid/approve", json={"token": "missing"})

    assert response.status_code == 404


def test_pid_approve_passes_save_flag_to_executor(client, monkeypatch) -> None:
    response, captured = _generate(client, monkeypatch)
    token = response.json()["token"]
    _patch_executor(monkeypatch, captured)

    approve_response = client.post("/api/pid/approve", json={"token": token, "save": True})

    assert approve_response.status_code == 200
    assert captured["execute_calls"][0]["save"] is True


def test_pid_approve_passes_target_dwg_path_to_executor(client, monkeypatch) -> None:
    response, captured = _generate(client, monkeypatch)
    token = response.json()["token"]
    _patch_executor(monkeypatch, captured)

    approve_response = client.post(
        "/api/pid/approve",
        json={"token": token, "target_dwg_path": r"E:\RC-Projects\pid.dwg"},
    )

    assert approve_response.status_code == 200
    assert captured["execute_calls"][0]["target_dwg_path"] == r"E:\RC-Projects\pid.dwg"


def test_pid_approve_autocad_not_running_returns_503(client, monkeypatch) -> None:
    response, captured = _generate(client, monkeypatch)
    token = response.json()["token"]
    _patch_executor(monkeypatch, captured, error=AutoCADNotRunningError("missing"))

    approve_response = client.post("/api/pid/approve", json={"token": token})

    assert approve_response.status_code == 503
    assert token in pid_routes._PID_CACHE


def test_pid_approve_works_with_fallback_generated_token(client, monkeypatch) -> None:
    captured = _patch_planner(monkeypatch, result=FAKE_FALLBACK_PLANNED_RESULT)
    response = client.post("/api/pid/generate", json={"prompt": "Draw P&ID."})
    token = response.json()["token"]
    _patch_executor(monkeypatch, captured)

    approve_response = client.post("/api/pid/approve", json={"token": token})

    assert approve_response.status_code == 200
    assert approve_response.json()["ok"] is True
    assert captured["execute_calls"][0]["command_sequence"] == FAKE_COMMAND_SEQUENCE


def test_api_main_imports_with_pid_router() -> None:
    from src.api.main import app as imported_app

    paths = [
        route.path
        for route in imported_app.routes
        if hasattr(route, "path")
    ]

    assert "/api/pid/generate" in paths
    assert "/api/pid/approve" in paths

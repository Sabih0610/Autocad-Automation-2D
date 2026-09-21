from __future__ import annotations

import sys

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.routes import autocad_edit as edit_routes
from src.parametric.vessel.dwg_export import AutoCADNotRunningError


FAKE_INSPECTION = {
    "ok": True,
    "document_name": "Drawing10.dwg",
    "dwg_path": "",
    "entity_count_total": 5,
    "entity_count_returned": 5,
    "truncated": False,
    "entities": [
        {
            "index": 0,
            "handle": "268",
            "object_name": "AcDbLine",
            "entity_type": "AcDbLine",
            "layer": "BORDER",
            "start_point": [0, 0, 0],
            "end_point": [1000, 0, 0],
            "center": None,
            "radius": None,
            "position": None,
            "text": None,
            "bbox": None,
        },
        {
            "index": 4,
            "handle": "26D",
            "object_name": "AcDbText",
            "entity_type": "AcDbText",
            "layer": "TEXT",
            "position": [0, 650, 0],
            "text": "My Drawing",
            "center": None,
            "radius": None,
            "start_point": None,
            "end_point": None,
            "bbox": None,
        },
    ],
}


FAKE_EDIT_PLAN = {
    "schema_version": "1.0",
    "edit_intent": "Delete the title text.",
    "summary": "Delete one text entity.",
    "target_description": "Text entity saying My Drawing.",
    "assumptions": ["Interpreted title text as handle 26D."],
    "delete_handles": ["26D"],
    "commands": [],
}


FAKE_EXECUTION_RESULT = {
    "ok": True,
    "edit_intent": "Delete the title text.",
    "summary": "Delete one text entity.",
    "deleted_count": 1,
    "delete_count": 1,
    "added_executed_count": 0,
    "added_total_count": 0,
    "errors": [],
    "document_name": "Drawing10.dwg",
    "dwg_path": "",
    "entity_count_before": 5,
    "entity_count_after": 4,
    "zoom_extents_called": True,
    "zoom_error": None,
}


class FakePythoncom:
    def __init__(self):
        self.initialized = 0
        self.uninitialized = 0

    def CoInitialize(self):
        self.initialized += 1

    def CoUninitialize(self):
        self.uninitialized += 1


@pytest.fixture(autouse=True)
def fake_pythoncom(monkeypatch):
    fake_module = FakePythoncom()
    monkeypatch.setitem(sys.modules, "pythoncom", fake_module)
    return fake_module


@pytest.fixture
def client():
    return TestClient(app)


def _patch_edit_stack(
    monkeypatch,
    captured: dict | None = None,
    *,
    inspect_error: Exception | None = None,
    generator_error: Exception | None = None,
    executor_error: Exception | None = None,
    execution_result: dict | None = None,
):
    captured = captured if captured is not None else {}
    captured.setdefault("inspect_calls", [])
    captured.setdefault("generate_calls", [])
    captured.setdefault("execute_calls", [])

    def fake_inspect(max_entities=500, target_dwg_path=None):
        captured["inspect_calls"].append(max_entities)
        captured["inspection_target"] = target_dwg_path
        if inspect_error is not None:
            raise inspect_error
        return FAKE_INSPECTION

    def fake_summary(inspection):
        assert inspection == FAKE_INSPECTION
        return "Drawing10.dwg: 5 entities returned."

    def fake_generate(prompt, drawing_inspection):
        captured["generate_calls"].append(
            {
                "prompt": prompt,
                "drawing_inspection": drawing_inspection,
            }
        )
        if generator_error is not None:
            raise generator_error
        return FAKE_EDIT_PLAN

    def fake_execute(
        edit_plan,
        target_dwg_path=None,
        save=True,
        continue_on_error=True,
        zoom_extents=True,
    ):
        captured["execute_calls"].append(
            {
                "edit_plan": edit_plan,
                "target_dwg_path": target_dwg_path,
                "save": save,
                "continue_on_error": continue_on_error,
                "zoom_extents": zoom_extents,
            }
        )
        if executor_error is not None:
            raise executor_error
        return execution_result or FAKE_EXECUTION_RESULT

    monkeypatch.setattr(edit_routes, "inspect_active_drawing", fake_inspect)
    monkeypatch.setattr(edit_routes, "summarize_drawing_state", fake_summary)
    monkeypatch.setattr(edit_routes, "generate_edit_plan", fake_generate)
    monkeypatch.setattr(edit_routes, "execute_edit_plan", fake_execute)

    return captured


def test_edit_with_valid_prompt_auto_execute_returns_200_and_calls_stack(client, monkeypatch) -> None:
    captured = _patch_edit_stack(monkeypatch)

    response = client.post(
        "/api/autocad/edit",
        json={"prompt": "delete the title text"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["executed"] is True
    assert captured["inspect_calls"] == [200]
    assert captured["generate_calls"][0]["prompt"] == "delete the title text"
    assert captured["generate_calls"][0]["drawing_inspection"] == FAKE_INSPECTION
    assert len(captured["execute_calls"]) == 1
    assert captured["execute_calls"][0]["edit_plan"] == FAKE_EDIT_PLAN


def test_edit_response_includes_expected_fields(client, monkeypatch) -> None:
    _patch_edit_stack(monkeypatch)

    response = client.post(
        "/api/autocad/edit",
        json={"prompt": "delete the title text"},
    )

    data = response.json()
    assert response.status_code == 200
    assert "ok" in data
    assert "executed" in data
    assert data["inspection_summary"] == "Drawing10.dwg: 5 entities returned."
    assert data["edit_plan"] == FAKE_EDIT_PLAN
    assert data["execution_result"] == FAKE_EXECUTION_RESULT


def test_auto_execute_false_returns_edit_plan_without_calling_executor(client, monkeypatch) -> None:
    captured = _patch_edit_stack(monkeypatch)

    response = client.post(
        "/api/autocad/edit",
        json={"prompt": "delete the title text", "auto_execute": False},
    )

    data = response.json()
    assert response.status_code == 200
    assert data["ok"] is True
    assert data["executed"] is False
    assert data["edit_plan"] == FAKE_EDIT_PLAN
    assert data["execution_result"] is None
    assert captured["execute_calls"] == []


def test_empty_prompt_returns_400(client, monkeypatch) -> None:
    _patch_edit_stack(monkeypatch)

    response = client.post("/api/autocad/edit", json={"prompt": "   "})

    assert response.status_code == 400


def test_invalid_max_entities_zero_returns_validation_error(client, monkeypatch) -> None:
    _patch_edit_stack(monkeypatch)

    response = client.post(
        "/api/autocad/edit",
        json={"prompt": "delete text", "max_entities": 0},
    )

    assert response.status_code in {400, 422}


def test_invalid_max_entities_too_high_returns_validation_error(client, monkeypatch) -> None:
    _patch_edit_stack(monkeypatch)

    response = client.post(
        "/api/autocad/edit",
        json={"prompt": "delete text", "max_entities": 3000},
    )

    assert response.status_code in {400, 422}


def test_save_true_is_passed_to_execute_edit_plan(client, monkeypatch) -> None:
    captured = _patch_edit_stack(monkeypatch)

    response = client.post(
        "/api/autocad/edit",
        json={"prompt": "delete text", "save": True},
    )

    assert response.status_code == 200
    assert captured["execute_calls"][0]["save"] is True


def test_target_dwg_path_is_passed_to_execute_edit_plan(client, monkeypatch) -> None:
    captured = _patch_edit_stack(monkeypatch)

    response = client.post(
        "/api/autocad/edit",
        json={
            "prompt": "delete text",
            "target_dwg_path": r"E:\RC-Projects\test.dwg",
        },
    )

    assert response.status_code == 200
    assert captured["execute_calls"][0]["target_dwg_path"] == r"E:\RC-Projects\test.dwg"
    assert captured["inspection_target"] == r"E:\RC-Projects\test.dwg"


def test_empty_target_dwg_path_is_not_silently_dropped(client, monkeypatch) -> None:
    """An explicitly-sent empty `target_dwg_path` must still reach the
    inspector rather than being silently treated the same as "no target
    given" and falling back to whatever's currently active in AutoCAD."""
    captured = _patch_edit_stack(monkeypatch)

    response = client.post(
        "/api/autocad/edit",
        json={"prompt": "delete text", "target_dwg_path": ""},
    )

    assert response.status_code == 200
    assert captured["inspection_target"] == ""


def test_inspector_autocad_not_running_returns_503(client, monkeypatch) -> None:
    _patch_edit_stack(
        monkeypatch,
        inspect_error=AutoCADNotRunningError("AutoCAD unavailable"),
    )

    response = client.post(
        "/api/autocad/edit",
        json={"prompt": "delete text"},
    )

    assert response.status_code == 503
    assert (
        response.json()["detail"]
        == "AutoCAD is not running. Open AutoCAD with a drawing active and try again."
    )


def test_executor_autocad_not_running_returns_503(client, monkeypatch) -> None:
    _patch_edit_stack(
        monkeypatch,
        executor_error=AutoCADNotRunningError("AutoCAD unavailable"),
    )

    response = client.post(
        "/api/autocad/edit",
        json={"prompt": "delete text"},
    )

    assert response.status_code == 503
    assert (
        response.json()["detail"]
        == "AutoCAD is not running. Open AutoCAD with a drawing active and try again."
    )


def test_edit_generator_value_error_returns_400(client, monkeypatch) -> None:
    _patch_edit_stack(
        monkeypatch,
        generator_error=ValueError("edit request is ambiguous"),
    )

    response = client.post(
        "/api/autocad/edit",
        json={"prompt": "change it"},
    )

    assert response.status_code == 400
    assert "edit request is ambiguous" in response.json()["detail"]


def test_executor_ok_false_returns_200_with_errors(client, monkeypatch) -> None:
    failed_result = dict(FAKE_EXECUTION_RESULT)
    failed_result["ok"] = False
    failed_result["errors"] = [
        {
            "type": "delete",
            "handle": "26D",
            "error": "RuntimeError: delete failed",
        }
    ]
    _patch_edit_stack(monkeypatch, execution_result=failed_result)

    response = client.post(
        "/api/autocad/edit",
        json={"prompt": "delete text"},
    )

    data = response.json()
    assert response.status_code == 200
    assert data["ok"] is False
    assert data["executed"] is True
    assert data["execution_result"]["errors"] == failed_result["errors"]


def test_api_main_imports_with_autocad_edit_router() -> None:
    from src.api.main import app as imported_app

    paths = [
        route.path
        for route in imported_app.routes
        if hasattr(route, "path")
    ]

    assert "/api/autocad/edit" in paths

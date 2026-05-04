from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.routes import cad3d as cad3d_routes
from src.framework.cad3d.autocad_3d_executor import AutoCAD3DExecutionError
from src.framework.cad3d.component_examples import routed_tank_pump_separator_scene_data
from src.framework.cad3d.scene_store import CAD3DSceneStore, CAD3DSceneStoreError
from src.ai.cad3d_edit_planner import deterministic_edit_plan_from_request
from src.parametric.vessel.dwg_export import AutoCADNotRunningError


FAKE_CAD3D_SCENE_DATA = {
    "schema_version": "1.0",
    "title": "Fake 3D Scene",
    "units": "mm",
    "assumptions": ["Test scene."],
    "metadata": {"source": "test"},
    "components": [
        {
            "component_type": "vertical_tank_3d",
            "id": "T101",
            "tag": "T-101",
            "center": [0, 0, 1500],
            "diameter": 1000,
            "height": 3000,
        }
    ],
}


class FakeComponentScene:
    def to_scene_data(self):
        return FAKE_CAD3D_SCENE_DATA


FAKE_3D_EXECUTION_RESULT = {
    "ok": True,
    "executed_count": 1,
    "total_count": 1,
    "errors": [],
    "dwg_path": "",
    "document_name": "Drawing3D.dwg",
    "entity_count_before": 0,
    "entity_count_after": 1,
    "zoom_extents_called": True,
    "zoom_error": None,
}


FAKE_AI_CAD3D_SCENE_DATA = {
    **FAKE_CAD3D_SCENE_DATA,
    "title": "AI 3D Scene",
    "metadata": {
        "planner_strategy": "ai_cad3d_scene_planner",
        "fallback_used": False,
        "ai_planner_attempted": True,
        "ai_planner_error_type": None,
        "ai_planner_error": None,
    },
}


FAKE_FALLBACK_CAD3D_SCENE_DATA = {
    **FAKE_CAD3D_SCENE_DATA,
    "title": "Fallback 3D Scene",
    "metadata": {
        "planner_strategy": "template_fallback",
        "fallback_used": True,
        "fallback_reason": "RuntimeError: invalid JSON",
        "fallback_template_name": "heat_exchanger_skid",
        "fallback_example_name": "heat_exchanger_skid",
        "ai_planner_attempted": True,
        "ai_planner_error_type": "RuntimeError",
        "ai_planner_error": "invalid JSON",
    },
}


FAKE_EXPANDED_CAD3D_SCENE_DATA = {
    **FAKE_AI_CAD3D_SCENE_DATA,
    "components": [
        *FAKE_AI_CAD3D_SCENE_DATA["components"],
        {
            "component_type": "heat_exchanger_3d",
            "id": "E101",
            "tag": "E-101",
            "center": [2000, 0, 800],
            "length": 1800,
            "diameter": 500,
            "orientation": "X",
        },
        {
            "component_type": "valve_placeholder_3d",
            "id": "XV101",
            "center": [1000, 0, 500],
            "length": 400,
            "width": 300,
            "height": 300,
            "orientation": "X",
        },
    ],
}


FAKE_ROUTED_CAD3D_SCENE_DATA = {
    **FAKE_AI_CAD3D_SCENE_DATA,
    "title": "AI Routed 3D Scene",
    "components": [
        *FAKE_AI_CAD3D_SCENE_DATA["components"],
        {
            "component_type": "pump_placeholder_3d",
            "id": "P101",
            "tag": "P-101",
            "center": [1600, 0, 300],
            "length": 800,
            "width": 450,
            "height": 500,
        },
        {
            "component_type": "pipe_connection_3d",
            "id": "PIPE_T101_P101",
            "from_port": "T101.side_right",
            "to_port": "P101.suction",
            "diameter": 100,
            "routing_style": "orthogonal",
            "clearance": 400,
        },
    ],
}


@pytest.fixture
def scene_store(tmp_path, monkeypatch):
    store = CAD3DSceneStore(persist_dir=tmp_path / "cad3d-state")
    monkeypatch.setattr(cad3d_routes, "get_default_cad3d_scene_store", lambda: store)
    return store


@pytest.fixture(autouse=True)
def clear_cad3d_cache(scene_store):
    cad3d_routes._CAD3D_CACHE.clear()
    yield
    cad3d_routes._CAD3D_CACHE.clear()
    scene_store.clear()


@pytest.fixture(autouse=True)
def patch_cad3d_edit_planner(monkeypatch):
    monkeypatch.setattr(
        cad3d_routes,
        "plan_cad3d_edit_resilient",
        lambda prompt, scene: deterministic_edit_plan_from_request(prompt, scene),
    )


@pytest.fixture
def client():
    return TestClient(app)


def _patch_example(monkeypatch, captured: dict | None = None, error: Exception | None = None):
    captured = captured if captured is not None else {}
    captured.setdefault("example_calls", [])

    def fake_get_cad3d_component_example(name):
        captured["example_calls"].append(name)
        if error is not None:
            raise error
        return FakeComponentScene()

    monkeypatch.setattr(cad3d_routes, "get_cad3d_component_example", fake_get_cad3d_component_example)
    monkeypatch.setattr(
        cad3d_routes,
        "available_cad3d_component_examples",
        lambda: {"simple_component_layout": lambda: FakeComponentScene()},
    )
    return captured


def _patch_executor(monkeypatch, captured: dict | None = None, error: Exception | None = None):
    captured = captured if captured is not None else {}
    captured.setdefault("execute_calls", [])
    captured.setdefault("com_calls", [])

    def fake_execute(scene_data, target_dwg_path=None, save=False, zoom_extents=True):
        captured["execute_calls"].append(
            {
                "scene_data": scene_data,
                "target_dwg_path": target_dwg_path,
                "save": save,
                "zoom_extents": zoom_extents,
            }
        )
        if error is not None:
            raise error
        return FAKE_3D_EXECUTION_RESULT

    monkeypatch.setattr(cad3d_routes, "execute_cad3d_scene", fake_execute)
    monkeypatch.setattr(cad3d_routes.pythoncom, "CoInitialize", lambda: captured["com_calls"].append("init"))
    monkeypatch.setattr(cad3d_routes.pythoncom, "CoUninitialize", lambda: captured["com_calls"].append("uninit"))
    return captured


def _patch_planner(
    monkeypatch,
    captured: dict | None = None,
    error: Exception | None = None,
    result: dict | None = None,
):
    captured = captured if captured is not None else {}
    captured.setdefault("planner_calls", [])

    def fake_plan_cad3d_scene_resilient(
        user_request,
        drawing_style="simple clean 3D equipment layout",
        allow_example_fallback=True,
    ):
        captured["planner_calls"].append(
            {
                "user_request": user_request,
                "drawing_style": drawing_style,
                "allow_example_fallback": allow_example_fallback,
            }
        )
        if error is not None:
            raise error
        return deepcopy(result or FAKE_AI_CAD3D_SCENE_DATA)

    monkeypatch.setattr(cad3d_routes, "plan_cad3d_scene_resilient", fake_plan_cad3d_scene_resilient)
    return captured


def _generate(client, monkeypatch, payload: dict | None = None, captured: dict | None = None):
    captured = _patch_example(monkeypatch, captured)
    response = client.post("/api/cad3d/generate", json=payload or {})
    return response, captured


def _seed_routed_scene(scene_store, token: str = "source-token") -> str:
    scene_store.put_generated_scene(
        token=token,
        prompt="Create routed tank pump separator.",
        drawing_style="clean 3D",
        scene=routed_tank_pump_separator_scene_data(),
    )
    return token


def test_cad3d_generate_returns_200_for_default_request(client, monkeypatch) -> None:
    response, _captured = _generate(client, monkeypatch)

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_cad3d_generate_with_no_prompt_uses_deterministic_example_path(client, monkeypatch) -> None:
    response, captured = _generate(client, monkeypatch)

    assert response.status_code == 200
    assert captured["example_calls"] == ["simple_component_layout"]
    assert response.json()["generation_strategy"] == "component_example"


def test_cad3d_generate_response_includes_token(client, monkeypatch) -> None:
    response, _captured = _generate(client, monkeypatch)

    assert response.json()["token"]


def test_cad3d_generate_response_includes_generation_strategy(client, monkeypatch) -> None:
    response, _captured = _generate(client, monkeypatch)

    assert response.json()["generation_strategy"] == "component_example"


def test_cad3d_generate_response_includes_component_count(client, monkeypatch) -> None:
    response, _captured = _generate(client, monkeypatch)

    assert response.json()["component_count"] == 1


def test_cad3d_generate_response_includes_component_types(client, monkeypatch) -> None:
    response, _captured = _generate(client, monkeypatch)

    assert response.json()["component_types"] == ["vertical_tank_3d"]


def test_cad3d_generate_unknown_example_returns_400(client, monkeypatch) -> None:
    _patch_example(monkeypatch, error=ValueError("Unknown CAD3D component example: bad"))

    response = client.post("/api/cad3d/generate", json={"example_name": "bad"})

    assert response.status_code == 400
    assert "Unknown CAD3D component example" in response.json()["detail"]


def test_cad3d_generate_does_not_call_autocad_executor(client, monkeypatch) -> None:
    _patch_example(monkeypatch)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("generate must not execute AutoCAD")

    monkeypatch.setattr(cad3d_routes, "execute_cad3d_scene", fail_if_called)

    response = client.post("/api/cad3d/generate", json={})

    assert response.status_code == 200


def test_cad3d_generate_with_prompt_calls_resilient_planner(client, monkeypatch) -> None:
    captured = _patch_planner(monkeypatch)

    response = client.post(
        "/api/cad3d/generate",
        json={
            "prompt": "Create a 3D tank and pump layout.",
            "drawing_style": "compact skid layout",
        },
    )

    assert response.status_code == 200
    assert captured["planner_calls"] == [
        {
            "user_request": "Create a 3D tank and pump layout.",
            "drawing_style": "compact skid layout",
            "allow_example_fallback": True,
        }
    ]


def test_cad3d_generate_with_prompt_returns_ai_metadata(client, monkeypatch) -> None:
    _patch_planner(monkeypatch)

    response = client.post(
        "/api/cad3d/generate",
        json={"prompt": "Create a 3D tank and pump layout."},
    )
    data = response.json()

    assert response.status_code == 200
    assert data["generation_strategy"] == "ai_cad3d_scene_planner"
    assert data["fallback_used"] is False
    assert data["ai_planner_attempted"] is True
    assert data["component_count"] == 1
    assert data["component_types"] == ["vertical_tank_3d"]


def test_cad3d_generate_with_ai_success_stores_token(client, monkeypatch) -> None:
    _patch_planner(monkeypatch)

    response = client.post(
        "/api/cad3d/generate",
        json={"prompt": "Create a 3D tank and pump layout."},
    )

    token = response.json()["token"]
    assert token in cad3d_routes._CAD3D_CACHE
    assert cad3d_routes._CAD3D_CACHE[token]["scene_data"]["title"] == "AI 3D Scene"


def test_cad3d_generate_saves_scene_state(client, monkeypatch, scene_store) -> None:
    _patch_planner(monkeypatch)

    response = client.post(
        "/api/cad3d/generate",
        json={"prompt": "Create a 3D tank and pump layout."},
    )
    token = response.json()["token"]

    assert response.status_code == 200
    assert scene_store.get(token).scene["title"] == "AI 3D Scene"
    assert scene_store.get_latest().token == token


def test_cad3d_generate_response_includes_scene_state_fields(client, monkeypatch) -> None:
    _patch_planner(monkeypatch)

    response = client.post(
        "/api/cad3d/generate",
        json={"prompt": "Create a 3D tank and pump layout."},
    )
    data = response.json()

    assert response.status_code == 200
    assert data["scene_state_saved"] is True
    assert data["scene_token"] == data["token"]
    assert data["component_ids"] == ["T101"]
    assert data["component_count"] == 1


def test_cad3d_approve_works_with_ai_generated_token(client, monkeypatch) -> None:
    captured = _patch_planner(monkeypatch)
    response = client.post(
        "/api/cad3d/generate",
        json={"prompt": "Create a 3D tank and pump layout."},
    )
    _patch_executor(monkeypatch, captured)

    approve = client.post("/api/cad3d/approve", json={"token": response.json()["token"]})

    assert approve.status_code == 200
    assert captured["execute_calls"][0]["scene_data"]["title"] == "AI 3D Scene"


def test_cad3d_approve_updates_scene_state_after_success(client, monkeypatch, scene_store) -> None:
    response, captured = _generate(client, monkeypatch)
    token = response.json()["token"]
    _patch_executor(monkeypatch, captured)

    approve = client.post("/api/cad3d/approve", json={"token": token})
    record = scene_store.get(token)

    assert approve.status_code == 200
    assert record.status == "approved"
    assert record.document_name == "Drawing3D.dwg"
    assert record.approval_result["ok"] is True


def test_cad3d_approve_response_includes_scene_state_fields(client, monkeypatch) -> None:
    response, captured = _generate(client, monkeypatch)
    token = response.json()["token"]
    _patch_executor(monkeypatch, captured)

    approve = client.post("/api/cad3d/approve", json={"token": token})
    data = approve.json()

    assert approve.status_code == 200
    assert data["scene_state_updated"] is True
    assert data["scene_status"] == "approved"
    assert data["scene_token"] == token


def test_cad3d_generate_with_planner_fallback_returns_200_and_token(client, monkeypatch) -> None:
    _patch_planner(monkeypatch, result=FAKE_FALLBACK_CAD3D_SCENE_DATA)

    response = client.post(
        "/api/cad3d/generate",
        json={"prompt": "Create a 3D tank and pump layout."},
    )
    data = response.json()

    assert response.status_code == 200
    assert data["token"]
    assert data["generation_strategy"] == "template_fallback"
    assert data["fallback_used"] is True
    assert data["fallback_template_name"] == "heat_exchanger_skid"
    assert data["fallback_example_name"] == "heat_exchanger_skid"
    assert data["ai_planner_error_type"] == "RuntimeError"


def test_cad3d_generate_response_includes_fallback_template_name(client, monkeypatch) -> None:
    _patch_planner(monkeypatch, result=FAKE_FALLBACK_CAD3D_SCENE_DATA)

    response = client.post(
        "/api/cad3d/generate",
        json={"prompt": "Create a heat exchanger skid."},
    )

    assert response.status_code == 200
    assert response.json()["fallback_template_name"] == "heat_exchanger_skid"


def test_cad3d_generate_response_includes_expanded_component_types(client, monkeypatch) -> None:
    _patch_planner(monkeypatch, result=FAKE_EXPANDED_CAD3D_SCENE_DATA)

    response = client.post(
        "/api/cad3d/generate",
        json={"prompt": "Create a 3D heat exchanger skid with valves."},
    )
    component_types = response.json()["component_types"]

    assert response.status_code == 200
    assert "heat_exchanger_3d" in component_types
    assert "valve_placeholder_3d" in component_types


def test_cad3d_generate_can_return_token_for_scene_with_pipe_connection(client, monkeypatch) -> None:
    _patch_planner(monkeypatch, result=FAKE_ROUTED_CAD3D_SCENE_DATA)

    response = client.post(
        "/api/cad3d/generate",
        json={"prompt": "Create a 3D routed tank and pump layout."},
    )

    assert response.status_code == 200
    assert response.json()["token"]
    assert cad3d_routes._CAD3D_CACHE[response.json()["token"]]["scene_data"]["title"] == "AI Routed 3D Scene"


def test_cad3d_generate_component_types_may_include_pipe_connection(client, monkeypatch) -> None:
    _patch_planner(monkeypatch, result=FAKE_ROUTED_CAD3D_SCENE_DATA)

    response = client.post(
        "/api/cad3d/generate",
        json={"prompt": "Create a 3D routed tank and pump layout."},
    )

    assert response.status_code == 200
    assert "pipe_connection_3d" in response.json()["component_types"]


def test_cad3d_approve_passes_pipe_connection_scene_to_executor(client, monkeypatch) -> None:
    captured = _patch_planner(monkeypatch, result=FAKE_ROUTED_CAD3D_SCENE_DATA)
    response = client.post(
        "/api/cad3d/generate",
        json={"prompt": "Create a 3D routed tank and pump layout."},
    )
    _patch_executor(monkeypatch, captured)

    approve = client.post("/api/cad3d/approve", json={"token": response.json()["token"]})

    assert approve.status_code == 200
    assert any(
        component["component_type"] == "pipe_connection_3d"
        for component in captured["execute_calls"][0]["scene_data"]["components"]
    )


def test_cad3d_state_latest_returns_latest_record(client, monkeypatch) -> None:
    _patch_planner(monkeypatch)
    response = client.post(
        "/api/cad3d/generate",
        json={"prompt": "Create a 3D tank and pump layout."},
    )

    state = client.get("/api/cad3d/state/latest")

    assert state.status_code == 200
    assert state.json()["ok"] is True
    assert state.json()["record"]["token"] == response.json()["token"]
    assert state.json()["record"]["status"] == "generated"


def test_cad3d_state_token_returns_record_with_full_scene(client, monkeypatch) -> None:
    _patch_planner(monkeypatch)
    response = client.post(
        "/api/cad3d/generate",
        json={"prompt": "Create a 3D tank and pump layout."},
    )

    state = client.get(f"/api/cad3d/state/{response.json()['token']}")

    assert state.status_code == 200
    assert state.json()["record"]["scene"]["title"] == "AI 3D Scene"
    assert "expanded_scene" in state.json()["record"]


def test_cad3d_state_list_returns_records(client, monkeypatch) -> None:
    _patch_planner(monkeypatch)
    response = client.post(
        "/api/cad3d/generate",
        json={"prompt": "Create a 3D tank and pump layout."},
    )

    state = client.get("/api/cad3d/state")

    assert state.status_code == 200
    assert state.json()["records"][0]["token"] == response.json()["token"]


def test_cad3d_state_missing_token_returns_404(client) -> None:
    response = client.get("/api/cad3d/state/missing")

    assert response.status_code == 404


def test_scene_state_update_failure_does_not_break_successful_approval(client, monkeypatch) -> None:
    response, captured = _generate(client, monkeypatch)
    token = response.json()["token"]
    _patch_executor(monkeypatch, captured)

    class FailingStore:
        def mark_approved(self, *args, **kwargs):
            raise CAD3DSceneStoreError("state update failed")

    monkeypatch.setattr(cad3d_routes, "get_default_cad3d_scene_store", lambda: FailingStore())

    approve = client.post("/api/cad3d/approve", json={"token": token})

    assert approve.status_code == 200
    assert approve.json()["ok"] is True
    assert approve.json()["scene_state_updated"] is False
    assert "state update failed" in approve.json()["scene_state_error"]


def test_cad3d_edit_uses_latest_scene_when_token_missing(client, scene_store) -> None:
    token = _seed_routed_scene(scene_store)

    response = client.post(
        "/api/cad3d/edit",
        json={"prompt": "Move pump P-101 1000 mm to the right.", "execute": False},
    )

    assert response.status_code == 200
    assert response.json()["source_token"] == token
    assert response.json()["edited_token"] != token


def test_cad3d_edit_uses_provided_token_when_present(client, scene_store) -> None:
    token = _seed_routed_scene(scene_store, "provided-token")

    response = client.post(
        "/api/cad3d/edit",
        json={"token": token, "prompt": "Move pump P-101 1000 mm to the right.", "execute": False},
    )

    assert response.status_code == 200
    assert response.json()["source_token"] == token


def test_cad3d_edit_returns_edited_token_and_edit_plan(client, scene_store) -> None:
    token = _seed_routed_scene(scene_store)

    response = client.post(
        "/api/cad3d/edit",
        json={"token": token, "prompt": "Move pump P-101 1000 mm to the right.", "execute": False},
    )

    assert response.status_code == 200
    assert response.json()["edited_token"]
    assert response.json()["edit_plan"]["operations"][0]["operation_type"] == "move_component"
    assert response.json()["scene_status"] == "generated"
    assert response.json()["scene_state_updated"] is False


def test_cad3d_edit_stores_edited_scene_state(client, scene_store) -> None:
    token = _seed_routed_scene(scene_store)

    response = client.post(
        "/api/cad3d/edit",
        json={"token": token, "prompt": "Move pump P-101 1000 mm to the right.", "execute": False},
    )

    record = scene_store.get(response.json()["edited_token"])
    assert record.status == "generated"
    assert record.scene["metadata"]["last_edit_operation_count"] == 1


def test_cad3d_edit_execute_false_does_not_call_executor(client, monkeypatch, scene_store) -> None:
    token = _seed_routed_scene(scene_store)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("execute_cad3d_scene should not be called")

    monkeypatch.setattr(cad3d_routes, "execute_cad3d_scene", fail_if_called)

    response = client.post(
        "/api/cad3d/edit",
        json={"token": token, "prompt": "Move pump P-101 1000 mm to the right.", "execute": False},
    )

    assert response.status_code == 200
    assert response.json()["executed"] is False


def test_cad3d_edit_execute_true_calls_fake_executor(client, monkeypatch, scene_store) -> None:
    token = _seed_routed_scene(scene_store)
    captured = _patch_executor(monkeypatch)

    response = client.post(
        "/api/cad3d/edit",
        json={"token": token, "prompt": "Move pump P-101 1000 mm to the right.", "execute": True},
    )

    assert response.status_code == 200
    assert response.json()["executed"] is True
    assert captured["execute_calls"]


def test_cad3d_edit_execute_true_marks_edited_scene_approved(client, monkeypatch, scene_store) -> None:
    token = _seed_routed_scene(scene_store)
    _patch_executor(monkeypatch)

    response = client.post(
        "/api/cad3d/edit",
        json={"token": token, "prompt": "Move pump P-101 1000 mm to the right.", "execute": True},
    )

    record = scene_store.get(response.json()["edited_token"])
    assert response.status_code == 200
    assert record.status == "approved"
    assert record.approval_result["ok"] is True


def test_cad3d_edit_returns_404_for_missing_token(client) -> None:
    response = client.post(
        "/api/cad3d/edit",
        json={"token": "missing", "prompt": "Move pump P-101 1000 mm to the right."},
    )

    assert response.status_code == 404


def test_cad3d_edit_returns_400_for_invalid_edit(client, scene_store) -> None:
    token = _seed_routed_scene(scene_store)

    response = client.post(
        "/api/cad3d/edit",
        json={"token": token, "prompt": "Make the model more beautiful."},
    )

    assert response.status_code == 400


def test_cad3d_edit_simple_move_changes_component_center(client, scene_store) -> None:
    token = _seed_routed_scene(scene_store)

    response = client.post(
        "/api/cad3d/edit",
        json={"token": token, "prompt": "Move pump P-101 1000 mm to the right."},
    )
    edited = scene_store.get(response.json()["edited_token"]).scene
    pump = next(component for component in edited["components"] if component["id"] == "P101")

    assert pump["center"] == [1300.0, 0.0, 250.0]


def test_cad3d_edit_delete_removes_component_from_stored_scene(client, scene_store) -> None:
    token = _seed_routed_scene(scene_store)

    response = client.post(
        "/api/cad3d/edit",
        json={"token": token, "prompt": "Delete pump P-101."},
    )
    edited = scene_store.get(response.json()["edited_token"]).scene
    component_ids = {component["id"] for component in edited["components"]}

    assert "P101" not in component_ids
    assert "PIPE_T101_P101" not in component_ids
    assert "PIPE_P101_V201" not in component_ids


def test_cad3d_edit_update_dimension_changes_stored_scene_field(client, scene_store) -> None:
    token = _seed_routed_scene(scene_store)

    response = client.post(
        "/api/cad3d/edit",
        json={"token": token, "prompt": "Change V-201 length to 4500 mm."},
    )
    edited = scene_store.get(response.json()["edited_token"]).scene
    vessel = next(component for component in edited["components"] if component["id"] == "V201")

    assert vessel["length"] == 4500.0


def test_cad3d_generate_with_planner_hard_failure_returns_502(client, monkeypatch) -> None:
    _patch_planner(monkeypatch, error=RuntimeError("fallback failed"))

    response = client.post(
        "/api/cad3d/generate",
        json={"prompt": "Create a 3D tank and pump layout."},
    )

    assert response.status_code == 502
    assert "3D CAD scene planning failed" in response.json()["detail"]


def test_cad3d_approve_with_valid_token_calls_executor(client, monkeypatch) -> None:
    response, captured = _generate(client, monkeypatch)
    token = response.json()["token"]
    _patch_executor(monkeypatch, captured)

    approve = client.post("/api/cad3d/approve", json={"token": token})

    assert approve.status_code == 200
    assert captured["execute_calls"][0]["scene_data"] == FAKE_CAD3D_SCENE_DATA
    assert captured["execute_calls"][0]["zoom_extents"] is True
    assert captured["com_calls"] == ["init", "uninit"]


def test_cad3d_approve_response_includes_execution_result(client, monkeypatch) -> None:
    response, captured = _generate(client, monkeypatch)
    _patch_executor(monkeypatch, captured)

    approve = client.post("/api/cad3d/approve", json={"token": response.json()["token"]})

    assert approve.json()["execution_result"] == FAKE_3D_EXECUTION_RESULT


def test_cad3d_approve_missing_token_returns_404(client, monkeypatch) -> None:
    _patch_executor(monkeypatch)

    response = client.post("/api/cad3d/approve", json={"token": "missing"})

    assert response.status_code == 404


def test_cad3d_approve_passes_save_flag_to_executor(client, monkeypatch) -> None:
    response, captured = _generate(client, monkeypatch)
    _patch_executor(monkeypatch, captured)

    client.post("/api/cad3d/approve", json={"token": response.json()["token"], "save": True})

    assert captured["execute_calls"][0]["save"] is True


def test_cad3d_approve_passes_target_dwg_path_to_executor(client, monkeypatch) -> None:
    response, captured = _generate(client, monkeypatch)
    _patch_executor(monkeypatch, captured)

    client.post(
        "/api/cad3d/approve",
        json={"token": response.json()["token"], "target_dwg_path": "C:/Temp/test.dwg"},
    )

    assert captured["execute_calls"][0]["target_dwg_path"] == "C:/Temp/test.dwg"


def test_cad3d_approve_handles_execution_failure(client, monkeypatch) -> None:
    response, captured = _generate(client, monkeypatch)
    _patch_executor(monkeypatch, captured, error=AutoCAD3DExecutionError("bad 3D scene"))

    approve = client.post("/api/cad3d/approve", json={"token": response.json()["token"]})

    assert approve.status_code == 500
    assert "3D CAD execution failed" in approve.json()["detail"]


def test_cad3d_approve_handles_autocad_not_running(client, monkeypatch) -> None:
    response, captured = _generate(client, monkeypatch)
    _patch_executor(monkeypatch, captured, error=AutoCADNotRunningError("AutoCAD unavailable"))

    approve = client.post("/api/cad3d/approve", json={"token": response.json()["token"]})

    assert approve.status_code == 503
    assert "AutoCAD is not running" in approve.json()["detail"]


def test_src_api_main_imports_successfully() -> None:
    from src.api.main import app as imported_app

    assert imported_app is not None

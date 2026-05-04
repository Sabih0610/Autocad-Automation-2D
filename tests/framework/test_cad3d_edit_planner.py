from __future__ import annotations

from copy import deepcopy

import pytest

from src.ai import cad3d_edit_planner
from src.ai.cad3d_edit_planner import (
    CAD3D_EDIT_PLANNER_SYSTEM_PROMPT,
    build_cad3d_edit_planner_prompt,
    deterministic_edit_plan_from_request,
    plan_cad3d_edit,
    plan_cad3d_edit_resilient,
)
from src.framework.cad3d.component_examples import routed_tank_pump_separator_scene_data
from src.framework.cad3d.edit_schema import CAD3DEditValidationError
from src.framework.cad3d.scene_editor import CAD3DSceneEditError


def _scene() -> dict:
    return routed_tank_pump_separator_scene_data()


VALID_EDIT_PLAN = {
    "schema_version": "1.0",
    "edit_intent": "Move pump P-101 1000 mm to the right.",
    "summary": "Move P101 right.",
    "operations": [
        {"operation_type": "move_component", "component_id": "P101", "delta": [1000, 0, 0]}
    ],
    "metadata": {},
}


def test_build_cad3d_edit_planner_prompt_includes_component_ids_and_tags() -> None:
    prompt = build_cad3d_edit_planner_prompt("Move pump.", _scene())

    assert "P101" in prompt
    assert "P-101" in prompt


def test_planner_prompt_includes_operation_types() -> None:
    prompt = build_cad3d_edit_planner_prompt("Move pump.", _scene())

    assert "move_component" in prompt
    assert "update_component" in prompt
    assert "add_component" in prompt
    assert "delete_component" in prompt


def test_planner_prompt_explains_direction_mapping() -> None:
    prompt = build_cad3d_edit_planner_prompt("Move pump.", _scene())

    assert "right = +X" in prompt
    assert "left = -X" in prompt
    assert "up = +Z" in prompt
    assert "down = -Z" in prompt
    assert "right = +X" in CAD3D_EDIT_PLANNER_SYSTEM_PROMPT


def test_mocked_ai_valid_edit_plan_passes(monkeypatch) -> None:
    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1, max_tokens=None):
        return deepcopy(VALID_EDIT_PLAN)

    monkeypatch.setattr(cad3d_edit_planner, "ask_ai", fake_ask_ai)

    plan = plan_cad3d_edit("Move pump P-101 1000 mm to the right.", _scene())

    assert plan["operations"][0]["component_id"] == "P101"


def test_mocked_ai_invalid_edit_plan_fails(monkeypatch) -> None:
    invalid_plan = deepcopy(VALID_EDIT_PLAN)
    invalid_plan["operations"][0].pop("delta")

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1, max_tokens=None):
        return invalid_plan

    monkeypatch.setattr(cad3d_edit_planner, "ask_ai", fake_ask_ai)

    with pytest.raises(CAD3DEditValidationError):
        plan_cad3d_edit("Move pump P-101 1000 mm to the right.", _scene())


def test_resilient_fallback_move_prompt_creates_move_component_plan(monkeypatch) -> None:
    monkeypatch.setattr(cad3d_edit_planner, "plan_cad3d_edit", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("AI failed")))

    plan = plan_cad3d_edit_resilient("Move pump P-101 1000 mm to the right.", _scene())

    assert plan["operations"][0]["operation_type"] == "move_component"
    assert plan["operations"][0]["delta"] == [1000.0, 0.0, 0.0]


def test_fallback_maps_tag_to_component_id() -> None:
    plan = deterministic_edit_plan_from_request("Move P-101 right 500", _scene())

    assert plan["operations"][0]["component_id"] == "P101"


def test_fallback_delete_prompt_creates_delete_component_plan() -> None:
    plan = deterministic_edit_plan_from_request("Delete pump P-101", _scene())

    assert plan["operations"][0] == {
        "operation_type": "delete_component",
        "component_id": "P101",
    }


def test_fallback_dimension_update_creates_update_component_plan() -> None:
    plan = deterministic_edit_plan_from_request("Change V-201 length to 4500 mm", _scene())

    assert plan["operations"][0]["operation_type"] == "update_component"
    assert plan["operations"][0]["component_id"] == "V201"
    assert plan["operations"][0]["updates"] == {"length": 4500.0}


def test_fallback_fails_cleanly_for_unsupported_edit() -> None:
    with pytest.raises(CAD3DSceneEditError):
        deterministic_edit_plan_from_request("Make the model more beautiful", _scene())


def test_resilient_metadata_indicates_fallback_when_ai_fails(monkeypatch) -> None:
    monkeypatch.setattr(cad3d_edit_planner, "plan_cad3d_edit", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("AI failed")))

    plan = plan_cad3d_edit_resilient("Move pump P-101 1000 mm to the right.", _scene())

    assert plan["metadata"]["planner_strategy"] == "deterministic_edit_fallback"
    assert plan["metadata"]["fallback_used"] is True
    assert plan["metadata"]["ai_planner_error_type"] == "RuntimeError"


def test_resilient_metadata_indicates_ai_success(monkeypatch) -> None:
    monkeypatch.setattr(cad3d_edit_planner, "plan_cad3d_edit", lambda *_args, **_kwargs: deepcopy(VALID_EDIT_PLAN))

    plan = plan_cad3d_edit_resilient("Move pump P-101 1000 mm to the right.", _scene())

    assert plan["metadata"]["planner_strategy"] == "ai_cad3d_edit_planner"
    assert plan["metadata"]["fallback_used"] is False
    assert plan["metadata"]["ai_planner_error_type"] is None

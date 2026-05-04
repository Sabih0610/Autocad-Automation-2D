from __future__ import annotations

from copy import deepcopy
import os

import pytest

from src.ai import cad3d_scene_planner
from src.ai.cad3d_scene_planner import (
    CAD3D_SCENE_PLANNER_MAX_TOKENS,
    CAD3D_SCENE_PLANNER_SYSTEM_PROMPT,
    build_cad3d_planner_prompt,
    plan_cad3d_scene,
    plan_cad3d_scene_resilient,
)
from src.framework.cad3d.component_templates import heat_exchanger_skid_template_scene
from src.framework.cad3d.routing import count_pipe_connections
from src.framework.cad3d.scene_schema import (
    CAD3D_SCENE_SCHEMA,
    CAD3D_SCENE_SCHEMA_VERSION,
    validate_cad3d_scene,
)


FAKE_AI_CAD3D_SCENE = {
    "schema_version": "1.0",
    "title": "AI 3D Equipment Layout",
    "units": "mm",
    "assumptions": ["Generated from prompt."],
    "components": [
        {
            "component_type": "vertical_tank_3d",
            "id": "T101",
            "tag": "T-101",
            "center": [0, 0, 2000],
            "diameter": 1600,
            "height": 4000,
        },
        {
            "component_type": "pump_placeholder_3d",
            "id": "P101",
            "tag": "P-101",
            "center": [2500, -700, 350],
            "length": 900,
            "width": 600,
            "height": 500,
        },
        {
            "component_type": "horizontal_vessel_3d",
            "id": "V201",
            "tag": "V-201",
            "center": [5500, 0, 1800],
            "diameter": 1200,
            "length": 3000,
            "orientation": "X",
        },
        {
            "component_type": "pipe_run_3d",
            "id": "P1",
            "points": [[0, -800, 400], [2500, -800, 400]],
            "diameter": 100,
        },
    ],
}


FAKE_AI_CAD3D_SCENE_WITH_PIPE_CONNECTION = {
    "schema_version": "1.0",
    "title": "AI Routed 3D Equipment Layout",
    "units": "mm",
    "assumptions": ["Generated with logical pipe routing."],
    "components": [
        {
            "component_type": "vertical_tank_3d",
            "id": "T101",
            "tag": "T-101",
            "center": [0, 0, 1000],
            "diameter": 1000,
            "height": 2000,
        },
        {
            "component_type": "pump_placeholder_3d",
            "id": "P101",
            "tag": "P-101",
            "center": [1800, 0, 300],
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


def test_empty_request_raises_value_error() -> None:
    with pytest.raises(ValueError, match="user_request cannot be empty"):
        plan_cad3d_scene("  ")


def test_planner_prompt_includes_original_user_request() -> None:
    prompt = build_cad3d_planner_prompt("Create a tank and pump.")

    assert "Create a tank and pump." in prompt


def test_planner_prompt_includes_drawing_style() -> None:
    prompt = build_cad3d_planner_prompt(
        "Create a tank and pump.",
        drawing_style="compact skid layout",
    )

    assert "compact skid layout" in prompt


def test_planner_prompt_mentions_supported_component_types() -> None:
    prompt = build_cad3d_planner_prompt("Create a tank and pump.")

    for component_type in [
        "vertical_tank_3d",
        "horizontal_vessel_3d",
        "pump_placeholder_3d",
        "pipe_run_3d",
        "pipe_connection_3d",
        "skid_base_3d",
        "box_3d",
        "label_3d",
        "heat_exchanger_3d",
        "pipe_connection_3d",
        "valve_placeholder_3d",
        "nozzle_3d",
        "flange_3d",
        "support_leg_3d",
        "saddle_support_3d",
        "pipe_support_3d",
    ]:
        assert component_type in prompt


def test_system_prompt_mentions_expanded_component_types() -> None:
    for component_type in [
        "heat_exchanger_3d",
        "valve_placeholder_3d",
        "nozzle_3d",
        "flange_3d",
        "support_leg_3d",
        "saddle_support_3d",
        "pipe_support_3d",
    ]:
        assert component_type in CAD3D_SCENE_PLANNER_SYSTEM_PROMPT


def test_planner_system_prompt_includes_pipe_connection_3d() -> None:
    assert "pipe_connection_3d" in CAD3D_SCENE_PLANNER_SYSTEM_PROMPT


def test_planner_system_prompt_includes_pipe_routing_guidance() -> None:
    prompt = CAD3D_SCENE_PLANNER_SYSTEM_PROMPT.lower()

    assert "prefer pipe_connection_3d" in prompt
    assert "equipment-to-equipment" in prompt
    assert "port" in prompt
    assert "component_id.port_name" in prompt


def test_planner_prompt_includes_design_family_hints() -> None:
    prompt = build_cad3d_planner_prompt("Create an industrial skid.")

    assert "tank pump separator" in prompt
    assert "dual pump skid" in prompt
    assert "heat exchanger skid" in prompt
    assert "vertical scrubber package" in prompt
    assert "extended process unit" in prompt


def test_planner_prompt_includes_expanded_component_example() -> None:
    prompt = build_cad3d_planner_prompt("Create an exchanger skid.")

    assert "heat_exchanger_3d" in prompt
    assert "valve_placeholder_3d" in prompt
    assert "flange_3d" in prompt
    assert "pipe_support_3d" in prompt


def test_planner_prompt_includes_known_pipe_port_examples() -> None:
    prompt = build_cad3d_planner_prompt("Create a routed tank pump exchanger.")

    assert "T101.side_right" in prompt
    assert "P101.suction" in prompt
    assert "P101.discharge" in prompt
    assert "E101.inlet" in prompt


def test_planner_prompt_compact_example_uses_pipe_connection_3d() -> None:
    prompt = build_cad3d_planner_prompt("Create a routed tank pump exchanger.")

    assert '"component_type": "pipe_connection_3d"' in prompt


def test_plan_cad3d_scene_calls_ask_ai_with_expected_arguments(monkeypatch) -> None:
    captured = {}

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1, max_tokens=None):
        captured["prompt"] = prompt
        captured["schema"] = schema
        captured["system_prompt"] = system_prompt
        captured["max_retries"] = max_retries
        captured["max_tokens"] = max_tokens
        return deepcopy(FAKE_AI_CAD3D_SCENE)

    monkeypatch.setattr(cad3d_scene_planner, "ask_ai", fake_ask_ai)

    plan_cad3d_scene("Create a 3D tank and pump.", drawing_style="simple skid")

    assert captured["schema"] == CAD3D_SCENE_SCHEMA
    assert captured["system_prompt"] == CAD3D_SCENE_PLANNER_SYSTEM_PROMPT
    assert captured["max_retries"] == 2
    assert captured["max_tokens"] == CAD3D_SCENE_PLANNER_MAX_TOKENS
    assert "Create a 3D tank and pump." in captured["prompt"]


def test_valid_ai_scene_is_returned_and_validates(monkeypatch) -> None:
    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1, max_tokens=None):
        return deepcopy(FAKE_AI_CAD3D_SCENE)

    monkeypatch.setattr(cad3d_scene_planner, "ask_ai", fake_ask_ai)

    result = plan_cad3d_scene("Create a 3D tank and pump.")

    assert validate_cad3d_scene(result) == []
    assert result["metadata"]["planner_strategy"] == "ai_cad3d_scene_planner"


def test_valid_ai_scene_with_pipe_connection_is_returned_and_validates(monkeypatch) -> None:
    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1, max_tokens=None):
        return deepcopy(FAKE_AI_CAD3D_SCENE_WITH_PIPE_CONNECTION)

    monkeypatch.setattr(cad3d_scene_planner, "ask_ai", fake_ask_ai)

    result = plan_cad3d_scene("Create a 3D routed tank and pump.")

    assert validate_cad3d_scene(result) == []
    assert count_pipe_connections(result) == 1
    assert result["metadata"]["planner_strategy"] == "ai_cad3d_scene_planner"


def test_missing_schema_version_is_added(monkeypatch) -> None:
    response = deepcopy(FAKE_AI_CAD3D_SCENE)
    response.pop("schema_version")

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1, max_tokens=None):
        return response

    monkeypatch.setattr(cad3d_scene_planner, "ask_ai", fake_ask_ai)

    result = plan_cad3d_scene("Create a 3D tank and pump.")

    assert result["schema_version"] == CAD3D_SCENE_SCHEMA_VERSION
    assert validate_cad3d_scene(result) == []


def test_invalid_ai_scene_raises_value_error(monkeypatch) -> None:
    response = deepcopy(FAKE_AI_CAD3D_SCENE)
    response["components"][0].pop("diameter")

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1, max_tokens=None):
        return response

    monkeypatch.setattr(cad3d_scene_planner, "ask_ai", fake_ask_ai)

    with pytest.raises(ValueError, match="CAD3D scene failed validation"):
        plan_cad3d_scene("Create a 3D tank and pump.")


def test_invalid_ai_pipe_connection_scene_raises_value_error(monkeypatch) -> None:
    response = deepcopy(FAKE_AI_CAD3D_SCENE_WITH_PIPE_CONNECTION)
    response["components"][-1].pop("to_port")

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1, max_tokens=None):
        return response

    monkeypatch.setattr(cad3d_scene_planner, "ask_ai", fake_ask_ai)

    with pytest.raises(ValueError, match="CAD3D scene failed validation"):
        plan_cad3d_scene("Create a 3D routed tank and pump.")


def test_resilient_planner_returns_ai_scene_when_ai_succeeds(monkeypatch) -> None:
    def fake_plan(user_request, drawing_style="simple clean 3D equipment layout"):
        result = deepcopy(FAKE_AI_CAD3D_SCENE)
        result["metadata"] = {
            "planner_strategy": "ai_cad3d_scene_planner",
            "fallback_used": False,
        }
        return result

    monkeypatch.setattr(cad3d_scene_planner, "plan_cad3d_scene", fake_plan)

    result = plan_cad3d_scene_resilient("Create a 3D tank and pump.")

    metadata = result["metadata"]
    assert metadata["planner_strategy"] == "ai_cad3d_scene_planner"
    assert metadata["fallback_used"] is False
    assert metadata["ai_planner_attempted"] is True
    assert metadata["ai_planner_error_type"] is None
    assert validate_cad3d_scene(result) == []


def test_resilient_planner_returns_fallback_scene_when_ai_fails(monkeypatch) -> None:
    def fake_plan(user_request, drawing_style="simple clean 3D equipment layout"):
        raise RuntimeError("invalid JSON")

    monkeypatch.setattr(cad3d_scene_planner, "plan_cad3d_scene", fake_plan)

    result = plan_cad3d_scene_resilient("Create a 3D tank and pump.")

    metadata = result["metadata"]
    assert metadata["planner_strategy"] == "template_fallback"
    assert metadata["fallback_used"] is True
    assert metadata["fallback_template_name"] == "tank_pump_separator"
    assert metadata["fallback_example_name"] == "tank_pump_separator"
    assert metadata["ai_planner_error_type"] == "RuntimeError"
    assert metadata["ai_planner_error"] == "invalid JSON"
    assert any("AI 3D planner failed" in assumption for assumption in result["assumptions"])
    assert validate_cad3d_scene(result) == []
    assert count_pipe_connections(result) >= 1


def test_resilient_fallback_uses_choose_cad3d_template(monkeypatch) -> None:
    captured = {}

    def fake_plan(user_request, drawing_style="simple clean 3D equipment layout"):
        raise RuntimeError("invalid JSON")

    def fake_choose(user_request):
        captured["user_request"] = user_request
        return "heat_exchanger_skid", heat_exchanger_skid_template_scene()

    monkeypatch.setattr(cad3d_scene_planner, "plan_cad3d_scene", fake_plan)
    monkeypatch.setattr(cad3d_scene_planner, "choose_cad3d_template", fake_choose)

    result = plan_cad3d_scene_resilient("Create a 3D heat exchanger skid.")

    metadata = result["metadata"]
    assert captured["user_request"] == "Create a 3D heat exchanger skid."
    assert metadata["planner_strategy"] == "template_fallback"
    assert metadata["fallback_used"] is True
    assert metadata["fallback_template_name"] == "heat_exchanger_skid"
    assert validate_cad3d_scene(result) == []


def test_resilient_heat_exchanger_prompt_falls_back_to_heat_exchanger_template(monkeypatch) -> None:
    def fake_plan(user_request, drawing_style="simple clean 3D equipment layout"):
        raise RuntimeError("invalid JSON")

    monkeypatch.setattr(cad3d_scene_planner, "plan_cad3d_scene", fake_plan)

    result = plan_cad3d_scene_resilient(
        "Create a heat exchanger skid with pump bypass inlet and outlet"
    )

    metadata = result["metadata"]
    assert metadata["planner_strategy"] == "template_fallback"
    assert metadata["fallback_used"] is True
    assert metadata["fallback_template_name"] == "heat_exchanger_skid"
    assert count_pipe_connections(result) >= 1


def test_resilient_planner_reraises_when_fallback_disabled(monkeypatch) -> None:
    def fake_plan(user_request, drawing_style="simple clean 3D equipment layout"):
        raise RuntimeError("invalid JSON")

    monkeypatch.setattr(cad3d_scene_planner, "plan_cad3d_scene", fake_plan)

    with pytest.raises(RuntimeError, match="invalid JSON"):
        plan_cad3d_scene_resilient(
            "Create a 3D tank and pump.",
            allow_example_fallback=False,
        )


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_AI_TESTS") != "1",
    reason="Set RUN_LIVE_AI_TESTS=1 to run live AI CAD3D planner tests.",
)
def test_live_ai_plans_cad3d_scene() -> None:
    result = plan_cad3d_scene(
        (
            "Create a simple 3D equipment layout with one vertical tank, one pump, "
            "one horizontal vessel, skid base, and connecting pipes."
        )
    )

    assert validate_cad3d_scene(result) == []

from __future__ import annotations

import os
from copy import deepcopy

import pytest

from src.ai import pid_component_planner
from src.ai.pid_component_planner import (
    PID_COMPONENT_PLANNER_SYSTEM_PROMPT,
    PID_COMPONENT_PLANNER_MAX_TOKENS,
    plan_and_render_pid_component_scene,
    plan_and_render_pid_component_scene_resilient,
    plan_pid_component_scene_resilient,
    plan_pid_component_scene,
)
from src.framework.commands.schema import validate_command_sequence
from src.framework.pid.component_schema import (
    PID_COMPONENT_SCENE_SCHEMA,
    PID_COMPONENT_SCHEMA_VERSION,
    validate_pid_component_scene_data,
)
from src.framework.pid.component_templates import (
    ensure_addressable_component_tags,
)


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
        },
        {
            "component_type": "pipe_run",
            "id": "P_IN",
            "points": [[-2600, 0], [-1600, 0]],
            "label": "3 Phase Inlet",
            "flow_direction": "RIGHT",
        },
        {
            "component_type": "gate_valve",
            "id": "XV_IN",
            "center": [-2100, 0],
            "orientation": "H",
        },
        {
            "component_type": "instrument_bubble",
            "id": "PI201",
            "tag": "PI-201",
            "center": [0, 700],
        },
    ],
}


def test_empty_user_request_raises_value_error() -> None:
    with pytest.raises(ValueError, match="user_request cannot be empty"):
        plan_pid_component_scene("  ")


def test_planner_calls_ask_ai_with_expected_arguments(monkeypatch) -> None:
    captured = {}

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1, max_tokens=None):
        captured["prompt"] = prompt
        captured["schema"] = schema
        captured["system_prompt"] = system_prompt
        captured["max_retries"] = max_retries
        captured["max_tokens"] = max_tokens
        return deepcopy(FAKE_COMPONENT_SCENE)

    monkeypatch.setattr(pid_component_planner, "ask_ai", fake_ask_ai)

    plan_pid_component_scene(
        "Draw a horizontal separator P&ID.",
        drawing_style="plant standard schematic",
    )

    assert captured["schema"] == PID_COMPONENT_SCENE_SCHEMA
    assert captured["system_prompt"] == PID_COMPONENT_PLANNER_SYSTEM_PROMPT
    assert captured["max_retries"] == 2
    assert captured["max_tokens"] == PID_COMPONENT_PLANNER_MAX_TOKENS
    assert "Draw a horizontal separator P&ID." in captured["prompt"]
    assert "plant standard schematic" in captured["prompt"]
    assert "horizontal_vessel" in captured["prompt"]
    assert "pipe_run" in captured["prompt"]
    assert "instrument_bubble" in captured["prompt"]


def test_valid_ai_scene_is_returned(monkeypatch) -> None:
    expected = deepcopy(FAKE_COMPONENT_SCENE)

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1, max_tokens=None):
        return expected

    monkeypatch.setattr(pid_component_planner, "ask_ai", fake_ask_ai)

    assert plan_pid_component_scene("Draw a P&ID.") == expected


def test_missing_schema_version_is_added(monkeypatch) -> None:
    response = deepcopy(FAKE_COMPONENT_SCENE)
    response.pop("schema_version")

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1, max_tokens=None):
        return response

    monkeypatch.setattr(pid_component_planner, "ask_ai", fake_ask_ai)

    result = plan_pid_component_scene("Draw a P&ID.")

    assert result["schema_version"] == PID_COMPONENT_SCHEMA_VERSION
    assert validate_pid_component_scene_data(result) == []


def test_invalid_ai_scene_raises_value_error(monkeypatch) -> None:
    response = deepcopy(FAKE_COMPONENT_SCENE)
    response["components"][0].pop("length")

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1, max_tokens=None):
        return response

    monkeypatch.setattr(pid_component_planner, "ask_ai", fake_ask_ai)

    with pytest.raises(ValueError, match="P&ID component scene failed validation"):
        plan_pid_component_scene("Draw a P&ID.")


def test_returned_scene_passes_component_scene_validation(monkeypatch) -> None:
    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1, max_tokens=None):
        return deepcopy(FAKE_COMPONENT_SCENE)

    monkeypatch.setattr(pid_component_planner, "ask_ai", fake_ask_ai)

    result = plan_pid_component_scene("Draw a P&ID.")

    assert validate_pid_component_scene_data(result) == []


def test_plan_and_render_pid_component_scene_returns_expected_result(
    monkeypatch,
) -> None:
    def fake_ask_ai(
        prompt,
        schema,
        system_prompt=None,
        max_retries=1,
        max_tokens=None,
    ):
        return deepcopy(
            FAKE_COMPONENT_SCENE
        )

    monkeypatch.setattr(
        pid_component_planner,
        "ask_ai",
        fake_ask_ai,
    )

    result = (
        plan_and_render_pid_component_scene(
            "Draw a P&ID."
        )
    )

    assert result["ok"] is True

    # C1 contract:
    #
    # AI output is normalized before it becomes the returned component
    # scene. Missing pipe/valve engineering tags are deterministically
    # assigned so the rendered entities remain addressable after scanning.
    expected_scene = deepcopy(
        FAKE_COMPONENT_SCENE
    )

    ensure_addressable_component_tags(
        expected_scene
    )

    assert (
        result["component_scene"]
        == expected_scene
    )


def test_resilient_planner_returns_ai_scene_when_strict_planner_succeeds(monkeypatch) -> None:
    def fake_plan(user_request, drawing_style="clean schematic P&ID"):
        return deepcopy(FAKE_COMPONENT_SCENE)

    monkeypatch.setattr(pid_component_planner, "plan_pid_component_scene", fake_plan)

    result = plan_pid_component_scene_resilient("Draw a P&ID.")

    assert result["title"] == "AI Planned P&ID"
    assert result["metadata"]["planner_strategy"] == "ai_component_planner"
    assert result["metadata"]["fallback_used"] is False
    assert result["metadata"]["ai_planner_attempted"] is True
    assert result["metadata"]["ai_planner_error_type"] is None
    assert result["metadata"]["ai_planner_error"] is None


def test_resilient_planner_returns_template_scene_when_strict_planner_fails(monkeypatch) -> None:
    def fake_plan(user_request, drawing_style="clean schematic P&ID"):
        raise RuntimeError("invalid JSON")

    monkeypatch.setattr(pid_component_planner, "plan_pid_component_scene", fake_plan)

    result = plan_pid_component_scene_resilient("horizontal 3 phase separator with oil water vapor")

    metadata = result["metadata"]
    assert metadata["planner_strategy"] == "template_fallback"
    assert metadata["fallback_used"] is True
    assert metadata["template_name"] == "horizontal_separator"
    assert "RuntimeError: invalid JSON" in metadata["fallback_reason"]
    assert metadata["ai_planner_attempted"] is True
    assert metadata["ai_planner_error_type"] == "RuntimeError"
    assert metadata["ai_planner_error"] == "invalid JSON"
    assert any("deterministic template fallback" in assumption for assumption in result["assumptions"])
    assert validate_pid_component_scene_data(result) == []


def test_resilient_planner_reraises_when_fallback_disabled(monkeypatch) -> None:
    def fake_plan(user_request, drawing_style="clean schematic P&ID"):
        raise RuntimeError("invalid JSON")

    monkeypatch.setattr(pid_component_planner, "plan_pid_component_scene", fake_plan)

    with pytest.raises(RuntimeError, match="invalid JSON"):
        plan_pid_component_scene_resilient(
            "Draw a P&ID.",
            allow_template_fallback=False,
        )


def test_resilient_plan_and_render_returns_expected_metadata(monkeypatch) -> None:
    def fake_plan(user_request, drawing_style="clean schematic P&ID"):
        raise RuntimeError("invalid JSON")

    monkeypatch.setattr(pid_component_planner, "plan_pid_component_scene", fake_plan)

    result = plan_and_render_pid_component_scene_resilient("tank pump suction discharge")

    assert result["ok"] is True
    assert result["component_scene"]
    assert result["command_sequence"]
    assert result["component_count"] == len(result["component_scene"]["components"])
    assert result["planner_strategy"] == "template_fallback"
    assert result["fallback_used"] is True
    assert result["template_name"] == "pump_tank"
    assert validate_command_sequence(result["command_sequence"]) == []


def test_resilient_planner_template_first_marks_ai_not_attempted() -> None:
    result = plan_pid_component_scene_resilient(
        "tank pump suction discharge",
        template_first=True,
    )

    metadata = result["metadata"]
    assert metadata["planner_strategy"] == "template_selected"
    assert metadata["ai_planner_attempted"] is False
    assert metadata["ai_planner_error_type"] is None
    assert metadata["ai_planner_error"] is None
    assert metadata["template_name"] == "pump_tank"


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_AI_TESTS") != "1",
    reason="Set RUN_LIVE_AI_TESTS=1 to run live AI P&ID component planner tests.",
)
def test_live_ai_plans_and_renders_pid_component_scene() -> None:
    result = plan_and_render_pid_component_scene(
        (
            "Draw a P&ID with one horizontal separator vessel, 3 phase inlet, "
            "vapor outlet, oil outlet, water outlet, gate valves, and PI/LT/LC "
            "instruments."
        )
    )

    assert validate_pid_component_scene_data(result["component_scene"]) == []
    assert result["component_count"] >= 8
    assert validate_command_sequence(result["command_sequence"]) == []

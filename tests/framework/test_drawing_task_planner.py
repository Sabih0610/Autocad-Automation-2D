from __future__ import annotations

import os

import pytest

from src.ai import drawing_task_planner
from src.ai.drawing_task_planner import (
    DRAWING_TASK_PLANNER_SYSTEM_PROMPT,
    plan_drawing_tasks,
)
from src.framework.commands.planning_schema import (
    DRAWING_TASK_PLAN_SCHEMA,
    is_valid_drawing_task_plan,
)


FAKE_PLAN = {
    "schema_version": "1.0",
    "drawing_type": "P&ID-style sketch",
    "summary": "Central vessel with piping, valves, instruments, and labels.",
    "assumptions": ["Used a clean orthogonal schematic layout."],
    "layout_strategy": "Place vessel centrally, route piping orthogonally around it.",
    "chunks": [
        {
            "chunk_id": "equipment",
            "title": "Central vessel",
            "goal": "Draw the central vertical vessel and vessel label.",
            "priority": 1,
            "expected_elements": ["vertical vessel", "vessel tag"],
            "layout_hint": "Place vessel at the center of the drawing.",
        },
        {
            "chunk_id": "piping",
            "title": "Header and branches",
            "goal": "Draw top header, vertical drops, inlet, and outlet piping.",
            "priority": 2,
            "expected_elements": [
                "top header",
                "two drops",
                "left inlet",
                "lower-right outlet",
            ],
        },
    ],
}


def test_empty_user_request_raises_value_error() -> None:
    with pytest.raises(ValueError, match="user_request cannot be empty"):
        plan_drawing_tasks("   ")


def test_invalid_max_chunks_raises_value_error() -> None:
    with pytest.raises(ValueError, match="max_chunks must be between 1 and 12"):
        plan_drawing_tasks("draw a layout", max_chunks=0)

    with pytest.raises(ValueError, match="max_chunks must be between 1 and 12"):
        plan_drawing_tasks("draw a layout", max_chunks=13)


def test_planner_calls_ask_ai_with_schema_system_prompt_and_retries(monkeypatch) -> None:
    captured = {}

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        captured["prompt"] = prompt
        captured["schema"] = schema
        captured["system_prompt"] = system_prompt
        captured["max_retries"] = max_retries
        return FAKE_PLAN

    monkeypatch.setattr(drawing_task_planner, "ask_ai", fake_ask_ai)

    plan_drawing_tasks("Draw a P&ID layout.", max_chunks=5)

    assert captured["schema"] == DRAWING_TASK_PLAN_SCHEMA
    assert captured["system_prompt"] == DRAWING_TASK_PLANNER_SYSTEM_PROMPT
    assert captured["max_retries"] == 2


def test_prompt_includes_original_user_request(monkeypatch) -> None:
    captured = {}

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        captured["prompt"] = prompt
        return FAKE_PLAN

    monkeypatch.setattr(drawing_task_planner, "ask_ai", fake_ask_ai)

    plan_drawing_tasks("Draw a pump station plot plan.", max_chunks=4)

    assert "Draw a pump station plot plan." in captured["prompt"]


def test_prompt_includes_max_chunks(monkeypatch) -> None:
    captured = {}

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        captured["prompt"] = prompt
        return FAKE_PLAN

    monkeypatch.setattr(drawing_task_planner, "ask_ai", fake_ask_ai)

    plan_drawing_tasks("Draw a P&ID layout.", max_chunks=4)

    assert "at most 4 logical chunks" in captured["prompt"]


def test_valid_plan_is_returned(monkeypatch) -> None:
    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        return FAKE_PLAN

    monkeypatch.setattr(drawing_task_planner, "ask_ai", fake_ask_ai)

    assert plan_drawing_tasks("Draw a P&ID layout.") == FAKE_PLAN


def test_missing_schema_version_is_added(monkeypatch) -> None:
    response = dict(FAKE_PLAN)
    response.pop("schema_version")

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        return response

    monkeypatch.setattr(drawing_task_planner, "ask_ai", fake_ask_ai)

    result = plan_drawing_tasks("Draw a P&ID layout.")

    assert result["schema_version"] == "1.0"
    assert is_valid_drawing_task_plan(result)


def test_invalid_plan_raises_value_error(monkeypatch) -> None:
    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        return {
            "schema_version": "1.0",
            "drawing_type": "P&ID-style sketch",
            "summary": "Invalid plan.",
            "assumptions": [],
            "chunks": [],
        }

    monkeypatch.setattr(drawing_task_planner, "ask_ai", fake_ask_ai)

    with pytest.raises(ValueError, match="Drawing task plan failed validation"):
        plan_drawing_tasks("Draw a P&ID layout.")


def test_returned_plan_passes_validation(monkeypatch) -> None:
    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        return FAKE_PLAN

    monkeypatch.setattr(drawing_task_planner, "ask_ai", fake_ask_ai)

    result = plan_drawing_tasks("Draw a P&ID layout.")

    assert is_valid_drawing_task_plan(result)


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_AI_TESTS") != "1",
    reason="Set RUN_LIVE_AI_TESTS=1 to run live AI drawing task planner tests.",
)
def test_live_ai_plans_pid_style_layout() -> None:
    plan = plan_drawing_tasks(
        (
            "Draw a simple P&ID-style layout with one central vertical vessel, "
            "header, branches, gate valves, and instruments."
        )
    )

    assert is_valid_drawing_task_plan(plan)
    assert len(plan["chunks"]) >= 3
    assert plan["summary"]

from __future__ import annotations

from copy import deepcopy

from src.framework.commands.planning_schema import (
    PLANNING_SCHEMA_VERSION,
    is_valid_drawing_task_plan,
    validate_drawing_task_plan,
)


def _valid_plan() -> dict:
    return {
        "schema_version": PLANNING_SCHEMA_VERSION,
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
            }
        ],
    }


def test_valid_plan_passes() -> None:
    assert validate_drawing_task_plan(_valid_plan()) == []


def test_missing_chunks_fails() -> None:
    plan = _valid_plan()
    plan.pop("chunks")

    assert validate_drawing_task_plan(plan)


def test_empty_chunks_fails() -> None:
    plan = _valid_plan()
    plan["chunks"] = []

    assert validate_drawing_task_plan(plan)


def test_too_many_chunks_fails() -> None:
    plan = _valid_plan()
    chunk = plan["chunks"][0]
    plan["chunks"] = [
        {
            **chunk,
            "chunk_id": f"chunk_{index}",
            "priority": index + 1,
        }
        for index in range(13)
    ]

    assert validate_drawing_task_plan(plan)


def test_chunk_missing_goal_fails() -> None:
    plan = _valid_plan()
    plan["chunks"][0].pop("goal")

    assert validate_drawing_task_plan(plan)


def test_empty_expected_element_fails() -> None:
    plan = _valid_plan()
    plan["chunks"][0]["expected_elements"] = ["vertical vessel", ""]

    assert validate_drawing_task_plan(plan)


def test_extra_top_level_property_fails() -> None:
    plan = _valid_plan()
    plan["extra"] = True

    assert validate_drawing_task_plan(plan)


def test_wrong_schema_version_fails() -> None:
    plan = _valid_plan()
    plan["schema_version"] = "2.0"

    assert validate_drawing_task_plan(plan)


def test_is_valid_drawing_task_plan_returns_true_false_correctly() -> None:
    valid_plan = _valid_plan()
    invalid_plan = deepcopy(valid_plan)
    invalid_plan["chunks"][0].pop("title")

    assert is_valid_drawing_task_plan(valid_plan) is True
    assert is_valid_drawing_task_plan(invalid_plan) is False

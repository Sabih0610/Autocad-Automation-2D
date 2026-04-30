from __future__ import annotations

from copy import deepcopy

from src.framework.commands.edit_schema import (
    EDIT_SCHEMA_VERSION,
    is_valid_edit_plan,
    validate_edit_plan,
)


def _delete_only_edit() -> dict:
    return {
        "schema_version": EDIT_SCHEMA_VERSION,
        "edit_intent": "Delete the center circle.",
        "summary": "Delete one circle entity from the active drawing.",
        "target_description": "Center circle on layer CENTERLINE.",
        "assumptions": [],
        "delete_handles": ["26C"],
        "commands": [],
    }


def _add_only_edit() -> dict:
    return {
        "schema_version": EDIT_SCHEMA_VERSION,
        "edit_intent": "Add a second circle to the right of the existing one.",
        "summary": "Add a new circle at x=800, y=250.",
        "assumptions": ["Used same radius as the existing circle."],
        "delete_handles": [],
        "commands": [
            {
                "command": "CIRCLE",
                "center": [800, 250],
                "radius": 100,
                "layer": "CENTERLINE",
            }
        ],
    }


def _replace_style_edit() -> dict:
    return {
        "schema_version": EDIT_SCHEMA_VERSION,
        "edit_intent": "Move the title text upward.",
        "summary": "Delete old title text and add replacement text 150mm higher.",
        "assumptions": [
            "Moving text is represented as delete old entity plus add new text."
        ],
        "delete_handles": ["26D"],
        "commands": [
            {
                "command": "TEXT",
                "text": "My Drawing",
                "position": [0, 800],
                "height": 80,
                "layer": "TEXT",
            }
        ],
    }


def test_valid_delete_only_edit_passes() -> None:
    assert validate_edit_plan(_delete_only_edit()) == []


def test_valid_add_only_edit_passes() -> None:
    assert validate_edit_plan(_add_only_edit()) == []


def test_valid_replace_style_edit_with_delete_handles_and_commands_passes() -> None:
    assert validate_edit_plan(_replace_style_edit()) == []


def test_missing_edit_intent_fails() -> None:
    plan = _delete_only_edit()
    plan.pop("edit_intent")

    assert validate_edit_plan(plan)


def test_empty_edit_intent_fails() -> None:
    plan = _delete_only_edit()
    plan["edit_intent"] = ""

    assert validate_edit_plan(plan)


def test_missing_delete_handles_fails() -> None:
    plan = _add_only_edit()
    plan.pop("delete_handles")

    assert validate_edit_plan(plan)


def test_missing_commands_fails() -> None:
    plan = _delete_only_edit()
    plan.pop("commands")

    assert validate_edit_plan(plan)


def test_both_delete_handles_and_commands_empty_fails() -> None:
    plan = _delete_only_edit()
    plan["delete_handles"] = []
    plan["commands"] = []

    errors = validate_edit_plan(plan)

    assert errors
    assert any("at least one of delete_handles or commands" in error for error in errors)


def test_empty_handle_string_fails() -> None:
    plan = _delete_only_edit()
    plan["delete_handles"] = [""]

    assert validate_edit_plan(plan)


def test_invalid_command_inside_commands_fails() -> None:
    plan = _add_only_edit()
    plan["commands"][0]["radius"] = -100

    assert validate_edit_plan(plan)


def test_unknown_command_type_inside_commands_fails() -> None:
    plan = _add_only_edit()
    plan["commands"] = [{"command": "SPLINE", "points": [[0, 0], [1, 1]]}]

    errors = validate_edit_plan(plan)

    assert errors
    assert any("unknown command type" in error for error in errors)


def test_extra_top_level_property_fails() -> None:
    plan = _delete_only_edit()
    plan["unexpected"] = True

    assert validate_edit_plan(plan)


def test_wrong_schema_version_fails() -> None:
    plan = _delete_only_edit()
    plan["schema_version"] = "2.0"

    assert validate_edit_plan(plan)


def test_is_valid_edit_plan_returns_true_false_correctly() -> None:
    valid_plan = _replace_style_edit()
    invalid_plan = deepcopy(valid_plan)
    invalid_plan["commands"][0].pop("position")

    assert is_valid_edit_plan(valid_plan) is True
    assert is_valid_edit_plan(invalid_plan) is False

from __future__ import annotations

import os
from copy import deepcopy

import pytest

from src.ai import edit_generator
from src.ai.edit_generator import (
    EDIT_GENERATOR_SYSTEM_PROMPT,
    generate_edit_plan,
)
from src.framework.commands.edit_schema import (
    EDIT_PLAN_SCHEMA,
    EDIT_SCHEMA_VERSION,
    is_valid_edit_plan,
)


FAKE_INSPECTION = {
    "ok": True,
    "document_name": "Drawing10.dwg",
    "entity_count_total": 6,
    "entity_count_returned": 6,
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
            "handle": "26C",
            "object_name": "AcDbCircle",
            "entity_type": "AcDbCircle",
            "layer": "CENTERLINE",
            "center": [500, 250, 0],
            "radius": 100,
            "start_point": None,
            "end_point": None,
            "position": None,
            "text": None,
            "bbox": None,
        },
        {
            "index": 5,
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


def _valid_delete_only_edit() -> dict:
    return {
        "schema_version": EDIT_SCHEMA_VERSION,
        "edit_intent": "Delete the center circle.",
        "summary": "Delete one circle entity from the active drawing.",
        "target_description": "Center circle on layer CENTERLINE.",
        "assumptions": [
            "Interpreted 'center circle' as handle 26C because it is the only circle."
        ],
        "delete_handles": ["26C"],
        "commands": [],
    }


def test_generate_edit_plan_raises_value_error_on_empty_user_request() -> None:
    with pytest.raises(ValueError, match="user_request cannot be empty"):
        generate_edit_plan("  ", FAKE_INSPECTION)


def test_generate_edit_plan_raises_value_error_when_inspection_is_not_dict() -> None:
    with pytest.raises(ValueError, match="drawing_inspection must be a dict"):
        generate_edit_plan("delete the center circle", ["not", "a", "dict"])  # type: ignore[arg-type]


def test_generate_edit_plan_raises_value_error_when_inspection_misses_entities() -> None:
    inspection = deepcopy(FAKE_INSPECTION)
    inspection.pop("entities")

    with pytest.raises(ValueError, match="drawing_inspection missing required fields"):
        generate_edit_plan("delete the center circle", inspection)


def test_generate_edit_plan_calls_ask_ai_with_expected_arguments(monkeypatch) -> None:
    captured = {}

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        captured["prompt"] = prompt
        captured["schema"] = schema
        captured["system_prompt"] = system_prompt
        captured["max_retries"] = max_retries
        return _valid_delete_only_edit()

    monkeypatch.setattr(edit_generator, "ask_ai", fake_ask_ai)

    generate_edit_plan("  delete the center circle  ", FAKE_INSPECTION)

    assert captured["schema"] == EDIT_PLAN_SCHEMA
    assert captured["system_prompt"] == EDIT_GENERATOR_SYSTEM_PROMPT
    assert captured["max_retries"] == 2
    assert "delete the center circle" in captured["prompt"]
    assert "Drawing10.dwg" in captured["prompt"]
    assert "268" in captured["prompt"]
    assert "26C" in captured["prompt"]
    assert "26D" in captured["prompt"]


def test_generate_edit_plan_returns_valid_delete_only_edit(monkeypatch) -> None:
    expected = _valid_delete_only_edit()

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        return expected

    monkeypatch.setattr(edit_generator, "ask_ai", fake_ask_ai)

    assert generate_edit_plan("delete the center circle", FAKE_INSPECTION) == expected


def test_generate_edit_plan_adds_missing_schema_version(monkeypatch) -> None:
    response = _valid_delete_only_edit()
    response.pop("schema_version")

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        return response

    monkeypatch.setattr(edit_generator, "ask_ai", fake_ask_ai)

    result = generate_edit_plan("delete the center circle", FAKE_INSPECTION)

    assert result["schema_version"] == EDIT_SCHEMA_VERSION
    assert is_valid_edit_plan(result)


def test_generate_edit_plan_raises_value_error_for_invalid_edit_plan(monkeypatch) -> None:
    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        return {
            "schema_version": EDIT_SCHEMA_VERSION,
            "edit_intent": "Ambiguous edit.",
            "summary": "No safe edit was selected.",
            "assumptions": [],
            "delete_handles": [],
            "commands": [],
        }

    monkeypatch.setattr(edit_generator, "ask_ai", fake_ask_ai)

    with pytest.raises(ValueError, match="Generated edit plan failed validation"):
        generate_edit_plan("change it", FAKE_INSPECTION)


def test_returned_valid_object_passes_edit_schema(monkeypatch) -> None:
    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        return _valid_delete_only_edit()

    monkeypatch.setattr(edit_generator, "ask_ai", fake_ask_ai)

    result = generate_edit_plan("delete the center circle", FAKE_INSPECTION)

    assert is_valid_edit_plan(result) is True


def test_prompt_truncates_entity_list_to_at_most_100_entities(monkeypatch) -> None:
    inspection = deepcopy(FAKE_INSPECTION)
    inspection["entities"] = [
        {
            "handle": f"H{index:03d}",
            "object_name": "AcDbLine",
            "entity_type": "AcDbLine",
            "layer": "BORDER",
            "start_point": [index, 0, 0],
            "end_point": [index + 1, 0, 0],
        }
        for index in range(105)
    ]
    inspection["entity_count_returned"] = 105

    captured = {}

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        captured["prompt"] = prompt
        return _valid_delete_only_edit()

    monkeypatch.setattr(edit_generator, "ask_ai", fake_ask_ai)

    generate_edit_plan("delete one line", inspection)

    assert "first 100 of 105 returned" in captured["prompt"]
    assert "H000" in captured["prompt"]
    assert "H099" in captured["prompt"]
    assert "H100" not in captured["prompt"]
    assert "H104" not in captured["prompt"]


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_AI_TESTS") != "1",
    reason="Set RUN_LIVE_AI_TESTS=1 to run live AI edit generator tests.",
)
def test_live_ai_generates_delete_center_circle_edit_plan() -> None:
    result = generate_edit_plan("Delete the center circle.", FAKE_INSPECTION)

    assert is_valid_edit_plan(result)
    assert result["delete_handles"]
    assert "26C" in result["delete_handles"] or result["delete_handles"][0]
    assert result["summary"]

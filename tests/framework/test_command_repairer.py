from __future__ import annotations

import os

import pytest

from src.ai import command_repairer
from src.ai.command_repairer import (
    COMMAND_REPAIR_SYSTEM_PROMPT,
    repair_command_sequence,
)
from src.framework.commands.schema import COMMAND_SCHEMA, validate_command_sequence


FAKE_REPAIRED_SEQUENCE = {
    "schema_version": "1.0",
    "summary": "Repaired simple drawing command sequence.",
    "estimated_drawing_type": "test",
    "assumptions": ["Simplified the drawing to a valid draft-quality layout."],
    "commands": [
        {"command": "LAYER", "layer_name": "TEST"},
        {"command": "LINE", "from": [0, 0], "to": [1000, 0], "layer": "TEST"},
        {"command": "CIRCLE", "center": [500, 250], "radius": 100, "layer": "TEST"},
    ],
}


def _fake_verifier_result() -> dict:
    return {
        "schema_version": "1.0",
        "verdict": "APPROVE_WITH_NOTES",
        "summary": "The sequence is missing one requested instrument bubble.",
        "issues": [
            {
                "severity": "WARNING",
                "description": "Instrument bubble requested by user is missing.",
                "command_index": 4,
                "suggested_fix": "Add a circle and text label for the instrument.",
            }
        ],
        "command_annotations": [],
    }


def _previous_command_sequence() -> dict:
    return {
        "schema_version": "1.0",
        "summary": "Previous partial drawing.",
        "assumptions": [],
        "commands": [
            {"command": "LINE", "from": [0, 0], "to": [100, 0]},
        ],
    }


def test_repair_command_sequence_raises_value_error_on_empty_user_request() -> None:
    with pytest.raises(ValueError, match="user_request cannot be empty"):
        repair_command_sequence("   ")


def test_repair_command_sequence_calls_ask_ai_with_expected_arguments(monkeypatch) -> None:
    captured = {}

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        captured["prompt"] = prompt
        captured["schema"] = schema
        captured["system_prompt"] = system_prompt
        captured["max_retries"] = max_retries
        return FAKE_REPAIRED_SEQUENCE

    monkeypatch.setattr(command_repairer, "ask_ai", fake_ask_ai)

    repair_command_sequence("repair the drawing")

    assert captured["schema"] == COMMAND_SCHEMA
    assert captured["system_prompt"] == COMMAND_REPAIR_SYSTEM_PROMPT
    assert captured["max_retries"] == 2


def test_prompt_includes_original_user_request(monkeypatch) -> None:
    captured = {}

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        captured["prompt"] = prompt
        return FAKE_REPAIRED_SEQUENCE

    monkeypatch.setattr(command_repairer, "ask_ai", fake_ask_ai)

    repair_command_sequence("Draw a P&ID style pump layout.")

    assert "Draw a P&ID style pump layout." in captured["prompt"]


def test_prompt_includes_bad_output_when_provided_as_string(monkeypatch) -> None:
    captured = {}
    bad_output = '{"schema_version": "1.0", "summary": "broken"'

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        captured["prompt"] = prompt
        return FAKE_REPAIRED_SEQUENCE

    monkeypatch.setattr(command_repairer, "ask_ai", fake_ask_ai)

    repair_command_sequence("repair this", bad_output=bad_output)

    assert bad_output in captured["prompt"]


def test_prompt_includes_bad_output_when_provided_as_dict(monkeypatch) -> None:
    captured = {}
    bad_output = {
        "summary": "bad command",
        "commands": [{"command": "LINE", "from": [0, 0]}],
    }

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        captured["prompt"] = prompt
        return FAKE_REPAIRED_SEQUENCE

    monkeypatch.setattr(command_repairer, "ask_ai", fake_ask_ai)

    repair_command_sequence("repair this", bad_output=bad_output)

    assert '"summary": "bad command"' in captured["prompt"]
    assert '"command": "LINE"' in captured["prompt"]


def test_prompt_includes_validation_errors_when_provided(monkeypatch) -> None:
    captured = {}
    errors = ["root.commands[0].to: 'to' is a required property"]

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        captured["prompt"] = prompt
        return FAKE_REPAIRED_SEQUENCE

    monkeypatch.setattr(command_repairer, "ask_ai", fake_ask_ai)

    repair_command_sequence("repair this", validation_errors=errors)

    assert errors[0] in captured["prompt"]


def test_prompt_includes_verifier_issues_when_provided(monkeypatch) -> None:
    captured = {}

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        captured["prompt"] = prompt
        return FAKE_REPAIRED_SEQUENCE

    monkeypatch.setattr(command_repairer, "ask_ai", fake_ask_ai)

    repair_command_sequence("repair this", verifier_result=_fake_verifier_result())

    assert "Instrument bubble requested by user is missing." in captured["prompt"]
    assert "APPROVE_WITH_NOTES" in captured["prompt"]


def test_prompt_includes_previous_command_sequence_when_provided(monkeypatch) -> None:
    captured = {}

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        captured["prompt"] = prompt
        return FAKE_REPAIRED_SEQUENCE

    monkeypatch.setattr(command_repairer, "ask_ai", fake_ask_ai)

    repair_command_sequence(
        "repair this",
        previous_command_sequence=_previous_command_sequence(),
    )

    assert "Previous partial drawing." in captured["prompt"]
    assert '"from": [' in captured["prompt"]


def test_repair_command_sequence_returns_valid_command_json(monkeypatch) -> None:
    expected = dict(FAKE_REPAIRED_SEQUENCE)

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        return expected

    monkeypatch.setattr(command_repairer, "ask_ai", fake_ask_ai)

    assert repair_command_sequence("repair this") == expected


def test_repair_command_sequence_adds_missing_schema_version(monkeypatch) -> None:
    response = dict(FAKE_REPAIRED_SEQUENCE)
    response.pop("schema_version")

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        return response

    monkeypatch.setattr(command_repairer, "ask_ai", fake_ask_ai)

    result = repair_command_sequence("repair this")

    assert result["schema_version"] == "1.0"
    assert validate_command_sequence(result) == []


def test_repair_command_sequence_raises_value_error_for_invalid_command_json(monkeypatch) -> None:
    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        return {
            "schema_version": "1.0",
            "summary": "Still broken.",
            "assumptions": [],
            "commands": [
                {"command": "LINE", "from": [0, 0]},
            ],
        }

    monkeypatch.setattr(command_repairer, "ask_ai", fake_ask_ai)

    with pytest.raises(ValueError, match="Repaired command sequence failed validation"):
        repair_command_sequence("repair this")


def test_returned_repaired_object_passes_command_schema(monkeypatch) -> None:
    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        return FAKE_REPAIRED_SEQUENCE

    monkeypatch.setattr(command_repairer, "ask_ai", fake_ask_ai)

    result = repair_command_sequence("repair this")

    assert validate_command_sequence(result) == []


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_AI_TESTS") != "1",
    reason="Set RUN_LIVE_AI_TESTS=1 to run live AI command repair tests.",
)
def test_live_ai_repairs_complex_pid_style_layout() -> None:
    result = repair_command_sequence(
        (
            "Draw a simple P&ID-style layout with one central vertical vessel, "
            "one top header, two branches, two gate valves, and two instrument bubbles."
        ),
        bad_output=(
            '{"schema_version": "1.0", "summary": "broken", '
            '"commands": [{"command": "LINE"'
        ),
    )

    assert validate_command_sequence(result) == []
    assert len(result["commands"]) > 0
    assert any(command["command"] == "LINE" for command in result["commands"])

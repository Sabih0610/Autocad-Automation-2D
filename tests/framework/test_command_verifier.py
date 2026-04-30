from __future__ import annotations

import os

import pytest

from src.ai import command_verifier
from src.ai.command_verifier import (
    COMMAND_VERIFIER_SYSTEM_PROMPT,
    verify_commands,
)
from src.framework.commands.verification_schema import (
    VERIFICATION_SCHEMA,
    VERIFICATION_SCHEMA_VERSION,
    is_valid_verification_result,
)


def _generator_output() -> dict:
    return {
        "schema_version": "1.0",
        "summary": "Simple rectangle",
        "estimated_drawing_type": "test",
        "assumptions": ["Draft-quality test."],
        "commands": [
            {"command": "LAYER", "layer_name": "BORDER"},
            {"command": "LINE", "from": [0, 0], "to": [1000, 0], "layer": "BORDER"},
            {"command": "LINE", "from": [1000, 0], "to": [1000, 500], "layer": "BORDER"},
            {"command": "LINE", "from": [1000, 500], "to": [0, 500], "layer": "BORDER"},
            {"command": "LINE", "from": [0, 500], "to": [0, 0], "layer": "BORDER"},
        ],
    }


def _valid_verifier_result() -> dict:
    return {
        "schema_version": VERIFICATION_SCHEMA_VERSION,
        "verdict": "APPROVE",
        "summary": "The command sequence appears internally consistent.",
        "issues": [],
        "command_annotations": [],
    }


def test_verify_commands_raises_value_error_on_empty_user_request() -> None:
    with pytest.raises(ValueError, match="user_request cannot be empty"):
        verify_commands("  ", _generator_output())


def test_verify_commands_raises_value_error_when_generator_output_is_not_dict() -> None:
    with pytest.raises(ValueError, match="generator_output must be a dict"):
        verify_commands("draw a rectangle", ["not", "a", "dict"])  # type: ignore[arg-type]


def test_verify_commands_raises_value_error_when_generator_output_misses_fields() -> None:
    output = _generator_output()
    output.pop("commands")

    with pytest.raises(ValueError, match="generator_output missing required fields"):
        verify_commands("draw a rectangle", output)


def test_verify_commands_calls_ask_ai_with_expected_arguments(monkeypatch) -> None:
    captured = {}

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        captured["prompt"] = prompt
        captured["schema"] = schema
        captured["system_prompt"] = system_prompt
        captured["max_retries"] = max_retries
        return _valid_verifier_result()

    monkeypatch.setattr(command_verifier, "ask_ai", fake_ask_ai)

    verify_commands("draw a rectangle", _generator_output())

    assert captured["schema"] == VERIFICATION_SCHEMA
    assert captured["system_prompt"] == COMMAND_VERIFIER_SYSTEM_PROMPT
    assert captured["max_retries"] == 2
    assert "draw a rectangle" in captured["prompt"]
    assert '"commands"' in captured["prompt"]
    assert '"LINE"' in captured["prompt"]


def test_verify_commands_returns_valid_verifier_json(monkeypatch) -> None:
    expected = _valid_verifier_result()

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        return expected

    monkeypatch.setattr(command_verifier, "ask_ai", fake_ask_ai)

    assert verify_commands("draw a rectangle", _generator_output()) == expected


def test_verify_commands_adds_missing_schema_version(monkeypatch) -> None:
    response = _valid_verifier_result()
    response.pop("schema_version")

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        return response

    monkeypatch.setattr(command_verifier, "ask_ai", fake_ask_ai)

    result = verify_commands("draw a rectangle", _generator_output())

    assert result["schema_version"] == VERIFICATION_SCHEMA_VERSION
    assert is_valid_verification_result(result)


def test_verify_commands_raises_value_error_for_invalid_verifier_json(monkeypatch) -> None:
    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        return {
            "schema_version": VERIFICATION_SCHEMA_VERSION,
            "verdict": "INVALID",
            "summary": "Invalid result.",
            "issues": [],
            "command_annotations": [],
        }

    monkeypatch.setattr(command_verifier, "ask_ai", fake_ask_ai)

    with pytest.raises(ValueError, match="Verifier result failed validation"):
        verify_commands("draw a rectangle", _generator_output())


def test_returned_valid_object_passes_verification_schema(monkeypatch) -> None:
    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        return _valid_verifier_result()

    monkeypatch.setattr(command_verifier, "ask_ai", fake_ask_ai)

    result = verify_commands("draw a rectangle", _generator_output())

    assert is_valid_verification_result(result) is True


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_AI_TESTS") != "1",
    reason="Set RUN_LIVE_AI_TESTS=1 to run live AI command verifier tests.",
)
def test_live_ai_verifies_rectangle_command_sequence() -> None:
    result = verify_commands(
        "Draw a simple rectangle 1000mm wide and 500mm high at the origin.",
        _generator_output(),
    )

    assert is_valid_verification_result(result)
    assert result["verdict"] in {"APPROVE", "APPROVE_WITH_NOTES", "REJECT"}
    assert result["summary"]

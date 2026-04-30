from __future__ import annotations

import os

import pytest

from src.ai import command_generator
from src.ai.command_generator import (
    COMMAND_GENERATOR_SYSTEM_PROMPT,
    generate_commands,
)
from src.framework.commands.schema import (
    COMMAND_SCHEMA,
    COMMAND_SCHEMA_VERSION,
    is_valid_command_sequence,
)


def _valid_command_sequence() -> dict:
    return {
        "schema_version": COMMAND_SCHEMA_VERSION,
        "summary": "Draw a simple line.",
        "estimated_drawing_type": "concept",
        "assumptions": [],
        "commands": [
            {
                "command": "LAYER",
                "layer_name": "BORDER",
                "color": 7,
            },
            {
                "command": "LINE",
                "from": [0, 0],
                "to": [100, 0],
                "layer": "BORDER",
            },
        ],
    }


def test_generate_commands_raises_value_error_on_empty_prompt() -> None:
    with pytest.raises(ValueError, match="user_request cannot be empty"):
        generate_commands("  ")


def test_generate_commands_calls_ask_ai_with_expected_arguments(monkeypatch) -> None:
    captured = {}

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        captured["prompt"] = prompt
        captured["schema"] = schema
        captured["system_prompt"] = system_prompt
        captured["max_retries"] = max_retries
        return _valid_command_sequence()

    monkeypatch.setattr(command_generator, "ask_ai", fake_ask_ai)

    generate_commands("  draw a line  ")

    assert captured["prompt"] == "draw a line"
    assert captured["schema"] == COMMAND_SCHEMA
    assert captured["system_prompt"] == COMMAND_GENERATOR_SYSTEM_PROMPT
    assert captured["max_retries"] == 2


def test_generate_commands_returns_valid_command_json(monkeypatch) -> None:
    expected = _valid_command_sequence()

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        return expected

    monkeypatch.setattr(command_generator, "ask_ai", fake_ask_ai)

    assert generate_commands("draw a line") == expected


def test_generate_commands_adds_missing_schema_version(monkeypatch) -> None:
    response = _valid_command_sequence()
    response.pop("schema_version")

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        return response

    monkeypatch.setattr(command_generator, "ask_ai", fake_ask_ai)

    result = generate_commands("draw a line")

    assert result["schema_version"] == COMMAND_SCHEMA_VERSION
    assert is_valid_command_sequence(result)


def test_generate_commands_raises_value_error_for_invalid_json(monkeypatch) -> None:
    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        return {
            "schema_version": COMMAND_SCHEMA_VERSION,
            "summary": "Bad command.",
            "assumptions": [],
            "commands": [
                {
                    "command": "LINE",
                    "from": [0, 0],
                }
            ],
        }

    monkeypatch.setattr(command_generator, "ask_ai", fake_ask_ai)

    with pytest.raises(ValueError, match="Generated command sequence failed validation"):
        generate_commands("draw a broken line")


def test_returned_valid_object_passes_schema_validation(monkeypatch) -> None:
    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        return _valid_command_sequence()

    monkeypatch.setattr(command_generator, "ask_ai", fake_ask_ai)

    result = generate_commands("draw a line")

    assert is_valid_command_sequence(result) is True


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_AI_TESTS") != "1",
    reason="Set RUN_LIVE_AI_TESTS=1 to run live AI command generator tests.",
)
def test_live_ai_generates_rectangle_command_sequence() -> None:
    result = generate_commands(
        "Draw a simple rectangle 1000mm wide and 500mm high at the origin."
    )

    assert is_valid_command_sequence(result)
    assert len(result["commands"]) >= 4
    assert any(command["command"] == "LINE" for command in result["commands"])

from __future__ import annotations

import os
from copy import deepcopy

import pytest

from src.ai import chunked_command_generator
from src.ai.chunked_command_generator import (
    ChunkedCommandGenerationError,
    generate_chunked_command_sequence,
    generate_commands_for_chunk,
    merge_chunk_command_sequences,
)
from src.framework.commands.schema import validate_command_sequence


FAKE_TASK_PLAN = {
    "schema_version": "1.0",
    "drawing_type": "P&ID-style sketch",
    "summary": "Central vessel with piping, valves, instruments, and labels.",
    "assumptions": ["Used clean orthogonal layout."],
    "layout_strategy": "Place vessel centrally, route piping around it.",
    "chunks": [
        {
            "chunk_id": "equipment",
            "title": "Central vessel",
            "goal": "Draw central vertical vessel and vessel label.",
            "priority": 1,
            "expected_elements": ["vertical vessel", "vessel label"],
            "layout_hint": "Place vessel at center.",
        },
        {
            "chunk_id": "piping",
            "title": "Piping",
            "goal": "Draw header, drops, inlet, and outlet lines.",
            "priority": 2,
            "expected_elements": ["top header", "drops", "inlet", "outlet"],
        },
    ],
}


CHUNK_EQUIPMENT_SEQUENCE = {
    "schema_version": "1.0",
    "summary": "Central vessel.",
    "estimated_drawing_type": "P&ID-style sketch",
    "assumptions": ["Used capsule vessel symbol."],
    "commands": [
        {"command": "LAYER", "layer_name": "EQUIPMENT"},
        {"command": "CIRCLE", "center": [0, 500], "radius": 250, "layer": "EQUIPMENT"},
        {
            "command": "TEXT",
            "text": "V-101",
            "position": [-120, 500],
            "height": 80,
            "layer": "EQUIPMENT",
        },
    ],
}


CHUNK_PIPING_SEQUENCE = {
    "schema_version": "1.0",
    "summary": "Piping layout.",
    "estimated_drawing_type": "P&ID-style sketch",
    "assumptions": ["Used orthogonal pipe routing."],
    "commands": [
        {"command": "LAYER", "layer_name": "PIPING"},
        {"command": "LAYER", "layer_name": "EQUIPMENT"},
        {"command": "LINE", "from": [-1000, 1200], "to": [1000, 1200], "layer": "PIPING"},
    ],
}


INVALID_CHUNK_SEQUENCE = {
    "schema_version": "1.0",
    "summary": "Invalid chunk.",
    "assumptions": [],
    "commands": [
        {"command": "LINE", "from": [0, 0], "layer": "TEST"},
    ],
}


def _chunk_result(chunk_id: str, sequence: dict) -> dict:
    return {
        "chunk_id": chunk_id,
        "title": chunk_id.title(),
        "command_sequence": deepcopy(sequence),
        "repair_attempts_used": 0,
        "errors": [],
    }


def test_generate_commands_for_chunk_rejects_empty_original_request() -> None:
    with pytest.raises(ValueError, match="original_user_request cannot be empty"):
        generate_commands_for_chunk("   ", FAKE_TASK_PLAN, FAKE_TASK_PLAN["chunks"][0])


def test_generate_commands_for_chunk_rejects_missing_chunk_goal() -> None:
    chunk = deepcopy(FAKE_TASK_PLAN["chunks"][0])
    chunk.pop("goal")

    with pytest.raises(ValueError, match="chunk missing required fields"):
        generate_commands_for_chunk("draw P&ID", FAKE_TASK_PLAN, chunk)


def test_generate_commands_for_chunk_builds_prompt_with_required_context(monkeypatch) -> None:
    captured = {}

    def fake_generate(prompt):
        captured["prompt"] = prompt
        return deepcopy(CHUNK_EQUIPMENT_SEQUENCE)

    monkeypatch.setattr(chunked_command_generator, "generate_commands", fake_generate)

    result = generate_commands_for_chunk(
        "Draw a P&ID layout.",
        FAKE_TASK_PLAN,
        FAKE_TASK_PLAN["chunks"][0],
    )

    assert result["chunk_id"] == "equipment"
    assert "Draw a P&ID layout." in captured["prompt"]
    assert FAKE_TASK_PLAN["summary"] in captured["prompt"]
    assert '"chunk_id": "equipment"' in captured["prompt"]
    assert "Draw central vertical vessel and vessel label." in captured["prompt"]
    assert "vertical vessel" in captured["prompt"]
    assert "vessel label" in captured["prompt"]


def test_valid_chunk_generation_returns_chunk_result(monkeypatch) -> None:
    def fake_generate(prompt):
        return deepcopy(CHUNK_EQUIPMENT_SEQUENCE)

    monkeypatch.setattr(chunked_command_generator, "generate_commands", fake_generate)

    result = generate_commands_for_chunk(
        "draw P&ID",
        FAKE_TASK_PLAN,
        FAKE_TASK_PLAN["chunks"][0],
    )

    assert result["chunk_id"] == "equipment"
    assert result["title"] == "Central vessel"
    assert result["command_sequence"] == CHUNK_EQUIPMENT_SEQUENCE
    assert result["repair_attempts_used"] == 0
    assert result["errors"] == []


def test_invalid_chunk_sequence_triggers_repair(monkeypatch) -> None:
    captured = {}

    def fake_generate(prompt):
        captured["generate_prompt"] = prompt
        return deepcopy(INVALID_CHUNK_SEQUENCE)

    def fake_repair(
        user_request,
        bad_output=None,
        validation_errors=None,
        previous_command_sequence=None,
        **_kwargs,
    ):
        captured["repair_user_request"] = user_request
        captured["bad_output"] = deepcopy(bad_output)
        captured["validation_errors"] = validation_errors
        captured["previous_command_sequence"] = deepcopy(previous_command_sequence)
        return deepcopy(CHUNK_EQUIPMENT_SEQUENCE)

    monkeypatch.setattr(chunked_command_generator, "generate_commands", fake_generate)
    monkeypatch.setattr(chunked_command_generator, "repair_command_sequence", fake_repair)

    result = generate_commands_for_chunk(
        "draw P&ID",
        FAKE_TASK_PLAN,
        FAKE_TASK_PLAN["chunks"][0],
    )

    assert result["repair_attempts_used"] == 1
    assert result["command_sequence"] == CHUNK_EQUIPMENT_SEQUENCE
    assert "Current chunk" in captured["repair_user_request"]
    assert captured["bad_output"] == INVALID_CHUNK_SEQUENCE
    assert captured["validation_errors"]
    assert captured["previous_command_sequence"] == INVALID_CHUNK_SEQUENCE


def test_invalid_chunk_sequence_with_no_repair_attempts_raises(monkeypatch) -> None:
    def fake_generate(prompt):
        return deepcopy(INVALID_CHUNK_SEQUENCE)

    monkeypatch.setattr(chunked_command_generator, "generate_commands", fake_generate)

    with pytest.raises(ChunkedCommandGenerationError, match="no repair attempts remain"):
        generate_commands_for_chunk(
            "draw P&ID",
            FAKE_TASK_PLAN,
            FAKE_TASK_PLAN["chunks"][0],
            max_repair_attempts=0,
        )


def test_merge_chunk_command_sequences_merges_commands_in_order() -> None:
    merged = merge_chunk_command_sequences(
        "draw P&ID",
        FAKE_TASK_PLAN,
        [
            _chunk_result("equipment", CHUNK_EQUIPMENT_SEQUENCE),
            _chunk_result("piping", CHUNK_PIPING_SEQUENCE),
        ],
    )

    commands = merged["commands"]
    assert commands[0] == {"command": "LAYER", "layer_name": "EQUIPMENT"}
    assert commands[1]["command"] == "CIRCLE"
    assert commands[2]["command"] == "TEXT"
    assert commands[3] == {"command": "LAYER", "layer_name": "PIPING"}
    assert commands[4]["command"] == "LINE"


def test_merge_removes_duplicate_layer_commands_for_same_layer() -> None:
    merged = merge_chunk_command_sequences(
        "draw P&ID",
        FAKE_TASK_PLAN,
        [
            _chunk_result("equipment", CHUNK_EQUIPMENT_SEQUENCE),
            _chunk_result("piping", CHUNK_PIPING_SEQUENCE),
        ],
    )

    equipment_layers = [
        command
        for command in merged["commands"]
        if command.get("command") == "LAYER" and command.get("layer_name") == "EQUIPMENT"
    ]
    assert len(equipment_layers) == 1


def test_merged_sequence_validates() -> None:
    merged = merge_chunk_command_sequences(
        "draw P&ID",
        FAKE_TASK_PLAN,
        [
            _chunk_result("equipment", CHUNK_EQUIPMENT_SEQUENCE),
            _chunk_result("piping", CHUNK_PIPING_SEQUENCE),
        ],
    )

    assert validate_command_sequence(merged) == []


def test_merged_assumptions_include_task_plan_and_chunk_assumptions() -> None:
    merged = merge_chunk_command_sequences(
        "draw P&ID",
        FAKE_TASK_PLAN,
        [
            _chunk_result("equipment", CHUNK_EQUIPMENT_SEQUENCE),
            _chunk_result("piping", CHUNK_PIPING_SEQUENCE),
        ],
    )

    assert "Used clean orthogonal layout." in merged["assumptions"]
    assert "Used capsule vessel symbol." in merged["assumptions"]
    assert "Used orthogonal pipe routing." in merged["assumptions"]
    assert "Layout was generated as a draft-quality schematic from chunked generation." in merged["assumptions"]


def test_generate_chunked_command_sequence_sorts_chunks_by_priority(monkeypatch) -> None:
    task_plan = deepcopy(FAKE_TASK_PLAN)
    task_plan["chunks"] = list(reversed(task_plan["chunks"]))
    seen_chunk_ids = []

    def fake_generate_for_chunk(
        original_user_request,
        task_plan,
        chunk,
        previous_chunks=None,
        max_repair_attempts=1,
    ):
        seen_chunk_ids.append(chunk["chunk_id"])
        sequence = (
            deepcopy(CHUNK_EQUIPMENT_SEQUENCE)
            if chunk["chunk_id"] == "equipment"
            else deepcopy(CHUNK_PIPING_SEQUENCE)
        )
        return _chunk_result(chunk["chunk_id"], sequence)

    monkeypatch.setattr(
        chunked_command_generator,
        "generate_commands_for_chunk",
        fake_generate_for_chunk,
    )

    result = generate_chunked_command_sequence("draw P&ID", task_plan)

    assert seen_chunk_ids == ["equipment", "piping"]
    assert result["ok"] is True


def test_generate_chunked_command_sequence_returns_counts(monkeypatch) -> None:
    def fake_generate_for_chunk(
        original_user_request,
        task_plan,
        chunk,
        previous_chunks=None,
        max_repair_attempts=1,
    ):
        sequence = (
            deepcopy(CHUNK_EQUIPMENT_SEQUENCE)
            if chunk["chunk_id"] == "equipment"
            else deepcopy(CHUNK_PIPING_SEQUENCE)
        )
        result = _chunk_result(chunk["chunk_id"], sequence)
        result["repair_attempts_used"] = 1 if chunk["chunk_id"] == "piping" else 0
        return result

    monkeypatch.setattr(
        chunked_command_generator,
        "generate_commands_for_chunk",
        fake_generate_for_chunk,
    )

    result = generate_chunked_command_sequence("draw P&ID", FAKE_TASK_PLAN)

    assert result["chunk_count"] == 2
    assert result["total_repair_attempts_used"] == 1


def test_invalid_merged_result_raises(monkeypatch) -> None:
    task_plan = deepcopy(FAKE_TASK_PLAN)
    task_plan["drawing_type"] = ""

    with pytest.raises(ChunkedCommandGenerationError, match="Merged command sequence failed validation"):
        merge_chunk_command_sequences(
            "draw P&ID",
            task_plan,
            [_chunk_result("equipment", CHUNK_EQUIPMENT_SEQUENCE)],
        )


def test_empty_chunk_results_raises() -> None:
    with pytest.raises(ChunkedCommandGenerationError, match="non-empty list"):
        merge_chunk_command_sequences("draw P&ID", FAKE_TASK_PLAN, [])


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_AI_TESTS") != "1",
    reason="Set RUN_LIVE_AI_TESTS=1 to run live AI chunked command tests.",
)
def test_live_ai_generates_chunked_pid_style_sequence() -> None:
    result = generate_chunked_command_sequence(
        (
            "Draw a simple P&ID-style layout with one central vertical vessel, "
            "one top header, two branches, two gate valves, and two instrument bubbles."
        ),
        FAKE_TASK_PLAN,
    )

    assert validate_command_sequence(result["command_sequence"]) == []
    assert len(result["command_sequence"]["commands"]) > 0
    assert result["chunk_count"] >= 2

from __future__ import annotations

import os
from copy import deepcopy

import pytest

from src.ai import chunked_command_orchestrator
from src.ai.chunked_command_orchestrator import (
    ChunkedCommandOrchestrationError,
    generate_chunked_verified_command_sequence,
)
from src.framework.commands.schema import validate_command_sequence


FAKE_TASK_PLAN = {
    "schema_version": "1.0",
    "drawing_type": "P&ID-style sketch",
    "summary": "Central vessel with piping and instruments.",
    "assumptions": ["Draft schematic layout."],
    "layout_strategy": "Central equipment with orthogonal piping.",
    "chunks": [
        {
            "chunk_id": "equipment",
            "title": "Equipment",
            "goal": "Draw central vessel.",
            "priority": 1,
            "expected_elements": ["vessel"],
        }
    ],
}


VALID_SEQUENCE = {
    "schema_version": "1.0",
    "summary": "Merged chunked drawing.",
    "estimated_drawing_type": "P&ID-style sketch",
    "assumptions": ["Draft layout."],
    "commands": [
        {"command": "LAYER", "layer_name": "TEST"},
        {"command": "LINE", "from": [0, 0], "to": [100, 0], "layer": "TEST"},
    ],
}


INVALID_SEQUENCE = {
    "schema_version": "1.0",
    "summary": "Invalid merged drawing.",
    "assumptions": [],
    "commands": [
        {"command": "LINE", "from": [0, 0], "layer": "TEST"},
    ],
}


APPROVE_VERIFIER = {
    "schema_version": "1.0",
    "verdict": "APPROVE",
    "summary": "Looks valid.",
    "issues": [],
    "command_annotations": [],
}


NOTES_VERIFIER = {
    "schema_version": "1.0",
    "verdict": "APPROVE_WITH_NOTES",
    "summary": "Minor notes.",
    "issues": [{"severity": "WARNING", "description": "Minor issue."}],
    "command_annotations": [],
}


REJECT_VERIFIER = {
    "schema_version": "1.0",
    "verdict": "REJECT",
    "summary": "Rejected.",
    "issues": [{"severity": "BLOCKER", "description": "Missing element."}],
    "command_annotations": [],
}


def _chunked_result(sequence: dict | None = None, total_repair_attempts: int = 0) -> dict:
    return {
        "ok": True,
        "command_sequence": deepcopy(sequence if sequence is not None else VALID_SEQUENCE),
        "chunk_results": [
            {
                "chunk_id": "equipment",
                "title": "Equipment",
                "command_sequence": deepcopy(VALID_SEQUENCE),
                "repair_attempts_used": total_repair_attempts,
                "errors": [],
            }
        ],
        "chunk_count": 1,
        "total_repair_attempts_used": total_repair_attempts,
    }


def _patch_stack(
    monkeypatch,
    *,
    chunked_result: dict | None = None,
    verifier_results: list[dict] | None = None,
    verifier_error: Exception | None = None,
    repair_results: list[dict] | None = None,
):
    captured = {
        "plan_calls": [],
        "chunked_calls": [],
        "verify_calls": [],
        "repair_calls": [],
    }
    chunked_result = deepcopy(chunked_result if chunked_result is not None else _chunked_result())
    verifier_results = [
        deepcopy(result)
        for result in (verifier_results if verifier_results is not None else [APPROVE_VERIFIER])
    ]
    repair_results = [
        deepcopy(result)
        for result in (repair_results if repair_results is not None else [VALID_SEQUENCE])
    ]

    def fake_plan(user_request, max_chunks=6):
        captured["plan_calls"].append(
            {
                "user_request": user_request,
                "max_chunks": max_chunks,
            }
        )
        return deepcopy(FAKE_TASK_PLAN)

    def fake_chunked(user_request, task_plan, max_repair_attempts_per_chunk=1):
        captured["chunked_calls"].append(
            {
                "user_request": user_request,
                "task_plan": deepcopy(task_plan),
                "max_repair_attempts_per_chunk": max_repair_attempts_per_chunk,
            }
        )
        return deepcopy(chunked_result)

    def fake_verify(user_request, command_sequence):
        captured["verify_calls"].append(
            {
                "user_request": user_request,
                "command_sequence": deepcopy(command_sequence),
            }
        )
        if verifier_error is not None:
            raise verifier_error
        if len(verifier_results) > 1:
            return verifier_results.pop(0)
        return deepcopy(verifier_results[0])

    def fake_repair(
        user_request,
        bad_output=None,
        validation_errors=None,
        verifier_result=None,
        previous_command_sequence=None,
    ):
        captured["repair_calls"].append(
            {
                "user_request": user_request,
                "bad_output": deepcopy(bad_output),
                "validation_errors": deepcopy(validation_errors),
                "verifier_result": deepcopy(verifier_result),
                "previous_command_sequence": deepcopy(previous_command_sequence),
            }
        )
        if len(repair_results) > 1:
            return repair_results.pop(0)
        return deepcopy(repair_results[0])

    monkeypatch.setattr(chunked_command_orchestrator, "plan_drawing_tasks", fake_plan)
    monkeypatch.setattr(
        chunked_command_orchestrator,
        "generate_chunked_command_sequence",
        fake_chunked,
    )
    monkeypatch.setattr(chunked_command_orchestrator, "verify_commands", fake_verify)
    monkeypatch.setattr(chunked_command_orchestrator, "repair_command_sequence", fake_repair)

    return captured


def test_empty_user_request_raises_value_error() -> None:
    with pytest.raises(ValueError, match="user_request cannot be empty"):
        generate_chunked_verified_command_sequence("   ")


def test_invalid_max_chunks_raises_value_error() -> None:
    with pytest.raises(ValueError, match="max_chunks must be between 1 and 12"):
        generate_chunked_verified_command_sequence("draw P&ID", max_chunks=0)

    with pytest.raises(ValueError, match="max_chunks must be between 1 and 12"):
        generate_chunked_verified_command_sequence("draw P&ID", max_chunks=13)


def test_negative_chunk_repair_attempts_raises_value_error() -> None:
    with pytest.raises(ValueError, match="max_repair_attempts_per_chunk must be >= 0"):
        generate_chunked_verified_command_sequence(
            "draw P&ID",
            max_repair_attempts_per_chunk=-1,
        )


def test_negative_final_repair_attempts_raises_value_error() -> None:
    with pytest.raises(ValueError, match="final_repair_attempts must be >= 0"):
        generate_chunked_verified_command_sequence(
            "draw P&ID",
            final_repair_attempts=-1,
        )


def test_valid_chunked_result_with_approve_returns_ok(monkeypatch) -> None:
    captured = _patch_stack(monkeypatch)

    result = generate_chunked_verified_command_sequence("draw P&ID")

    assert result["ok"] is True
    assert result["command_sequence"] == VALID_SEQUENCE
    assert result["verifier_verdict"] == "APPROVE"
    assert result["final_repair_attempts_used"] == 0
    assert captured["repair_calls"] == []


def test_result_includes_task_plan_sequence_verifier_and_chunk_results(monkeypatch) -> None:
    _patch_stack(monkeypatch)

    result = generate_chunked_verified_command_sequence("draw P&ID")

    assert result["task_plan"] == FAKE_TASK_PLAN
    assert result["command_sequence"] == VALID_SEQUENCE
    assert result["verifier_result"] == APPROVE_VERIFIER
    assert result["chunk_results"]
    assert result["chunk_count"] == 1


def test_final_invalid_merged_sequence_triggers_final_repair(monkeypatch) -> None:
    captured = _patch_stack(
        monkeypatch,
        chunked_result=_chunked_result(INVALID_SEQUENCE),
    )

    result = generate_chunked_verified_command_sequence("draw P&ID")

    assert result["ok"] is True
    assert result["final_repair_attempts_used"] == 1
    assert len(captured["repair_calls"]) == 1
    assert captured["repair_calls"][0]["bad_output"] == INVALID_SEQUENCE
    assert captured["repair_calls"][0]["validation_errors"]
    assert captured["repair_calls"][0]["previous_command_sequence"] == INVALID_SEQUENCE


def test_final_invalid_merged_sequence_with_no_repairs_raises(monkeypatch) -> None:
    _patch_stack(
        monkeypatch,
        chunked_result=_chunked_result(INVALID_SEQUENCE),
    )

    with pytest.raises(ChunkedCommandOrchestrationError, match="failed validation"):
        generate_chunked_verified_command_sequence("draw P&ID", final_repair_attempts=0)


def test_verifier_reject_triggers_final_repair(monkeypatch) -> None:
    captured = _patch_stack(
        monkeypatch,
        verifier_results=[REJECT_VERIFIER, APPROVE_VERIFIER],
    )

    result = generate_chunked_verified_command_sequence("draw P&ID")

    assert result["ok"] is True
    assert result["final_repair_attempts_used"] == 1
    assert len(captured["repair_calls"]) == 1
    assert captured["repair_calls"][0]["verifier_result"] == REJECT_VERIFIER
    assert captured["repair_calls"][0]["previous_command_sequence"] == VALID_SEQUENCE


def test_verifier_reject_with_no_final_repairs_raises(monkeypatch) -> None:
    _patch_stack(monkeypatch, verifier_results=[REJECT_VERIFIER])

    with pytest.raises(ChunkedCommandOrchestrationError, match="not accepted by verifier"):
        generate_chunked_verified_command_sequence("draw P&ID", final_repair_attempts=0)


def test_approve_with_notes_succeeds_by_default_without_repair(monkeypatch) -> None:
    captured = _patch_stack(monkeypatch, verifier_results=[NOTES_VERIFIER])

    result = generate_chunked_verified_command_sequence("draw P&ID")

    assert result["ok"] is True
    assert result["verifier_verdict"] == "APPROVE_WITH_NOTES"
    assert result["final_repair_attempts_used"] == 0
    assert captured["repair_calls"] == []


def test_approve_with_notes_triggers_repair_when_requested(monkeypatch) -> None:
    captured = _patch_stack(
        monkeypatch,
        verifier_results=[NOTES_VERIFIER, APPROVE_VERIFIER],
    )

    result = generate_chunked_verified_command_sequence(
        "draw P&ID",
        repair_on_approve_with_notes=True,
    )

    assert result["ok"] is True
    assert result["final_repair_attempts_used"] == 1
    assert captured["repair_calls"][0]["verifier_result"] == NOTES_VERIFIER


def test_repair_history_records_final_schema_validation_failure(monkeypatch) -> None:
    _patch_stack(
        monkeypatch,
        chunked_result=_chunked_result(INVALID_SEQUENCE),
    )

    result = generate_chunked_verified_command_sequence("draw P&ID")

    assert result["repair_history"][0]["reason"] == "final_schema_validation_failed"
    assert result["repair_history"][0]["errors"]
    assert result["repair_history"][0]["verdict"] is None


def test_repair_history_records_final_verifier_rejection(monkeypatch) -> None:
    _patch_stack(
        monkeypatch,
        verifier_results=[REJECT_VERIFIER, APPROVE_VERIFIER],
    )

    result = generate_chunked_verified_command_sequence("draw P&ID")

    assert result["repair_history"][0]["reason"] == "final_verifier_rejected"
    assert result["repair_history"][0]["verdict"] == "REJECT"
    assert result["repair_history"][0]["errors"] == ["[BLOCKER] Missing element."]


def test_verifier_failure_after_valid_schema_returns_fallback_success(monkeypatch) -> None:
    _patch_stack(monkeypatch, verifier_error=RuntimeError("invalid verifier JSON"))

    result = generate_chunked_verified_command_sequence("draw P&ID")

    assert result["ok"] is True
    assert result["command_sequence"] == VALID_SEQUENCE
    assert result["verifier_verdict"] == "APPROVE_WITH_NOTES"
    assert result["verifier_result"]["issues"][0]["severity"] == "WARNING"
    assert "AI verifier failed: RuntimeError: invalid verifier JSON" in result["verifier_result"]["issues"][0]["description"]
    assert result["repair_history"][0]["reason"] == "verifier_failed_fallback"
    assert result["repair_history"][0]["verdict"] == "APPROVE_WITH_NOTES"


def test_schema_invalid_sequence_does_not_fallback_without_repair(monkeypatch) -> None:
    captured = _patch_stack(
        monkeypatch,
        chunked_result=_chunked_result(INVALID_SEQUENCE),
        verifier_error=RuntimeError("invalid verifier JSON"),
    )

    with pytest.raises(ChunkedCommandOrchestrationError, match="failed validation"):
        generate_chunked_verified_command_sequence("draw P&ID", final_repair_attempts=0)

    assert captured["verify_calls"] == []
    assert captured["repair_calls"] == []


def test_chunk_repair_attempts_are_passed_through(monkeypatch) -> None:
    captured = _patch_stack(
        monkeypatch,
        chunked_result=_chunked_result(VALID_SEQUENCE, total_repair_attempts=3),
    )

    result = generate_chunked_verified_command_sequence(
        "draw P&ID",
        max_chunks=4,
        max_repair_attempts_per_chunk=2,
    )

    assert captured["plan_calls"][0]["max_chunks"] == 4
    assert captured["chunked_calls"][0]["max_repair_attempts_per_chunk"] == 2
    assert result["chunk_repair_attempts_used"] == 3


def test_final_repair_attempts_count_is_correct(monkeypatch) -> None:
    _patch_stack(
        monkeypatch,
        chunked_result=_chunked_result(INVALID_SEQUENCE),
        verifier_results=[REJECT_VERIFIER, APPROVE_VERIFIER],
        repair_results=[VALID_SEQUENCE, VALID_SEQUENCE],
    )

    result = generate_chunked_verified_command_sequence(
        "draw P&ID",
        final_repair_attempts=2,
    )

    assert result["final_repair_attempts_used"] == 2
    assert [entry["reason"] for entry in result["repair_history"]] == [
        "final_schema_validation_failed",
        "final_verifier_rejected",
    ]


def test_orchestrator_does_not_call_executor_or_autocad() -> None:
    assert "execute_commands" not in vars(chunked_command_orchestrator)
    assert "execute_command_sequence" not in vars(chunked_command_orchestrator)
    assert "_get_acad" not in vars(chunked_command_orchestrator)
    assert "AutoCADNotRunningError" not in vars(chunked_command_orchestrator)


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_AI_TESTS") != "1",
    reason="Set RUN_LIVE_AI_TESTS=1 to run live AI chunked orchestration tests.",
)
def test_live_ai_generates_chunked_verified_pid_style_sequence() -> None:
    result = generate_chunked_verified_command_sequence(
        (
            "Draw a simple P&ID-style layout with one central vertical vessel, "
            "one top header, two branches, two gate valves, and two instrument bubbles."
        )
    )

    assert result["ok"] is True
    assert validate_command_sequence(result["command_sequence"]) == []
    assert result["chunk_count"] >= 2
    assert len(result["command_sequence"]["commands"]) > 0

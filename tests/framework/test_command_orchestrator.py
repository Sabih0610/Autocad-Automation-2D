from __future__ import annotations

from copy import deepcopy

import pytest

from src.ai import command_orchestrator
from src.ai.command_orchestrator import (
    CommandOrchestrationError,
    generate_verified_command_sequence,
)


VALID_SEQUENCE = {
    "schema_version": "1.0",
    "summary": "Valid drawing",
    "estimated_drawing_type": "test",
    "assumptions": [],
    "commands": [
        {"command": "LAYER", "layer_name": "TEST"},
        {"command": "LINE", "from": [0, 0], "to": [100, 0], "layer": "TEST"},
    ],
}


INVALID_SEQUENCE = {
    "schema_version": "1.0",
    "summary": "Invalid drawing",
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
    "issues": [{"severity": "BLOCKER", "description": "Missing side."}],
    "command_annotations": [],
}


def _patch_stack(
    monkeypatch,
    *,
    generated: dict | None = None,
    verifier_results: list[dict] | None = None,
    verifier_error: Exception | None = None,
    repair_results: list[dict] | None = None,
):
    captured = {
        "generate_calls": [],
        "verify_calls": [],
        "repair_calls": [],
    }
    generated = deepcopy(generated if generated is not None else VALID_SEQUENCE)
    verifier_results = [
        deepcopy(result)
        for result in (verifier_results if verifier_results is not None else [APPROVE_VERIFIER])
    ]
    repair_results = [
        deepcopy(result)
        for result in (repair_results if repair_results is not None else [VALID_SEQUENCE])
    ]

    def fake_generate(user_request):
        captured["generate_calls"].append(user_request)
        return deepcopy(generated)

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

    monkeypatch.setattr(command_orchestrator, "generate_commands", fake_generate)
    monkeypatch.setattr(command_orchestrator, "verify_commands", fake_verify)
    monkeypatch.setattr(command_orchestrator, "repair_command_sequence", fake_repair)

    return captured


def test_empty_user_request_raises_value_error() -> None:
    with pytest.raises(ValueError, match="user_request cannot be empty"):
        generate_verified_command_sequence("   ")


def test_negative_max_repair_attempts_raises_value_error() -> None:
    with pytest.raises(ValueError, match="max_repair_attempts must be >= 0"):
        generate_verified_command_sequence("draw a line", max_repair_attempts=-1)


def test_valid_generated_sequence_with_approve_returns_ok_result(monkeypatch) -> None:
    captured = _patch_stack(monkeypatch)

    result = generate_verified_command_sequence("draw a line")

    assert result["ok"] is True
    assert result["command_sequence"] == VALID_SEQUENCE
    assert result["verifier_verdict"] == "APPROVE"
    assert result["repair_attempts_used"] == 0
    assert captured["repair_calls"] == []


def test_result_includes_command_sequence_verifier_and_verdict(monkeypatch) -> None:
    _patch_stack(monkeypatch)

    result = generate_verified_command_sequence("draw a line")

    assert result["command_sequence"] == VALID_SEQUENCE
    assert result["verifier_result"] == APPROVE_VERIFIER
    assert result["verifier_verdict"] == "APPROVE"


def test_invalid_generated_sequence_triggers_repair(monkeypatch) -> None:
    captured = _patch_stack(monkeypatch, generated=INVALID_SEQUENCE)

    result = generate_verified_command_sequence("draw a repaired line")

    assert result["ok"] is True
    assert result["repair_attempts_used"] == 1
    assert len(captured["repair_calls"]) == 1
    assert captured["repair_calls"][0]["bad_output"] == INVALID_SEQUENCE
    assert captured["repair_calls"][0]["previous_command_sequence"] == INVALID_SEQUENCE
    assert captured["repair_calls"][0]["validation_errors"]


def test_invalid_generated_sequence_with_no_repair_attempts_raises(monkeypatch) -> None:
    _patch_stack(monkeypatch, generated=INVALID_SEQUENCE)

    with pytest.raises(CommandOrchestrationError, match="schema validation"):
        generate_verified_command_sequence("draw a repaired line", max_repair_attempts=0)


def test_verifier_reject_triggers_repair(monkeypatch) -> None:
    captured = _patch_stack(
        monkeypatch,
        verifier_results=[REJECT_VERIFIER, APPROVE_VERIFIER],
    )

    result = generate_verified_command_sequence("draw a line")

    assert result["ok"] is True
    assert result["repair_attempts_used"] == 1
    assert len(captured["repair_calls"]) == 1
    assert captured["repair_calls"][0]["verifier_result"] == REJECT_VERIFIER
    assert captured["repair_calls"][0]["previous_command_sequence"] == VALID_SEQUENCE


def test_verifier_reject_with_no_repair_attempts_raises(monkeypatch) -> None:
    _patch_stack(monkeypatch, verifier_results=[REJECT_VERIFIER])

    with pytest.raises(CommandOrchestrationError, match="not accepted by verifier"):
        generate_verified_command_sequence("draw a line", max_repair_attempts=0)


def test_approve_with_notes_returns_success_by_default_without_repair(monkeypatch) -> None:
    captured = _patch_stack(monkeypatch, verifier_results=[NOTES_VERIFIER])

    result = generate_verified_command_sequence("draw a line")

    assert result["ok"] is True
    assert result["verifier_verdict"] == "APPROVE_WITH_NOTES"
    assert result["repair_attempts_used"] == 0
    assert captured["repair_calls"] == []


def test_approve_with_notes_triggers_repair_when_requested(monkeypatch) -> None:
    captured = _patch_stack(
        monkeypatch,
        verifier_results=[NOTES_VERIFIER, APPROVE_VERIFIER],
    )

    result = generate_verified_command_sequence(
        "draw a line",
        repair_on_approve_with_notes=True,
    )

    assert result["ok"] is True
    assert result["repair_attempts_used"] == 1
    assert len(captured["repair_calls"]) == 1
    assert captured["repair_calls"][0]["verifier_result"] == NOTES_VERIFIER


def test_repair_history_records_schema_validation_failures(monkeypatch) -> None:
    _patch_stack(monkeypatch, generated=INVALID_SEQUENCE)

    result = generate_verified_command_sequence("draw a repaired line")

    assert result["repair_history"][0]["reason"] == "schema_validation_failed"
    assert result["repair_history"][0]["errors"]
    assert result["repair_history"][0]["verdict"] is None


def test_repair_history_records_verifier_rejection(monkeypatch) -> None:
    _patch_stack(
        monkeypatch,
        verifier_results=[REJECT_VERIFIER, APPROVE_VERIFIER],
    )

    result = generate_verified_command_sequence("draw a line")

    assert result["repair_history"][0]["reason"] == "verifier_rejected"
    assert result["repair_history"][0]["verdict"] == "REJECT"
    assert result["repair_history"][0]["errors"] == ["[BLOCKER] Missing side."]


def test_verifier_failure_after_valid_schema_returns_fallback_success(monkeypatch) -> None:
    _patch_stack(monkeypatch, verifier_error=RuntimeError("invalid verifier JSON"))

    result = generate_verified_command_sequence("draw a line")

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
        generated=INVALID_SEQUENCE,
        verifier_error=RuntimeError("invalid verifier JSON"),
    )

    with pytest.raises(CommandOrchestrationError, match="schema validation"):
        generate_verified_command_sequence("draw a line", max_repair_attempts=0)

    assert captured["verify_calls"] == []
    assert captured["repair_calls"] == []


def test_repair_attempts_count_is_correct(monkeypatch) -> None:
    _patch_stack(
        monkeypatch,
        generated=INVALID_SEQUENCE,
        verifier_results=[REJECT_VERIFIER, APPROVE_VERIFIER],
        repair_results=[VALID_SEQUENCE, VALID_SEQUENCE],
    )

    result = generate_verified_command_sequence("draw a line", max_repair_attempts=2)

    assert result["repair_attempts_used"] == 2
    assert [entry["reason"] for entry in result["repair_history"]] == [
        "schema_validation_failed",
        "verifier_rejected",
    ]


def test_invalid_repair_repeatedly_eventually_raises(monkeypatch) -> None:
    _patch_stack(
        monkeypatch,
        generated=INVALID_SEQUENCE,
        repair_results=[INVALID_SEQUENCE, INVALID_SEQUENCE],
    )

    with pytest.raises(CommandOrchestrationError, match="no repair attempts remain"):
        generate_verified_command_sequence("draw a line", max_repair_attempts=2)


def test_orchestrator_does_not_import_executor_or_autocad() -> None:
    assert "execute_commands" not in vars(command_orchestrator)
    assert "execute_command_sequence" not in vars(command_orchestrator)
    assert "_get_acad" not in vars(command_orchestrator)
    assert "AutoCADNotRunningError" not in vars(command_orchestrator)

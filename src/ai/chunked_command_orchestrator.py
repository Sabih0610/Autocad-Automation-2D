"""Chunked orchestration for complex Mode 2 command generation.

This module coordinates task planning, chunked command generation, final schema
validation, verifier review, and final repair attempts. It does not execute
AutoCAD commands, render previews, expose API routes, or touch AutoCAD COM.
"""

from __future__ import annotations

from typing import Any

from src.ai.chunked_command_generator import generate_chunked_command_sequence
from src.ai.command_repairer import repair_command_sequence
from src.ai.command_verifier import verify_commands
from src.ai.drawing_task_planner import plan_drawing_tasks
from src.framework.commands.schema import validate_command_sequence


class ChunkedCommandOrchestrationError(Exception):
    """Raised when chunked generation cannot produce an acceptable result."""


def _history_entry(
    reason: str,
    errors: list[str] | None = None,
    verdict: str | None = None,
) -> dict[str, Any]:
    return {
        "reason": reason,
        "errors": errors or [],
        "verdict": verdict,
    }


def _fallback_verifier_result(reason: str) -> dict:
    return {
        "schema_version": "1.0",
        "verdict": "APPROVE_WITH_NOTES",
        "summary": (
            "The command sequence passed deterministic schema validation, but "
            "AI verification failed. Review the drawing after execution."
        ),
        "issues": [
            {
                "severity": "WARNING",
                "description": f"AI verifier failed: {reason}",
                "suggested_fix": (
                    "Inspect the generated drawing visually in AutoCAD before "
                    "using it as a final drawing."
                ),
            }
        ],
        "command_annotations": [],
    }


def _verifier_issue_messages(verifier_result: dict | None) -> list[str]:
    if not isinstance(verifier_result, dict):
        return []

    issues = verifier_result.get("issues", [])
    if not isinstance(issues, list):
        return []

    messages = []
    for issue in issues:
        if isinstance(issue, dict):
            severity = issue.get("severity", "INFO")
            description = issue.get("description", "")
            messages.append(f"[{severity}] {description}".strip())
        else:
            messages.append(str(issue))

    return messages


def _repair_for_schema_errors(
    user_request: str,
    command_sequence: dict,
    validation_errors: list[str],
) -> dict:
    return repair_command_sequence(
        user_request,
        bad_output=command_sequence,
        validation_errors=validation_errors,
        previous_command_sequence=command_sequence,
    )


def _repair_for_verifier(
    user_request: str,
    command_sequence: dict,
    verifier_result: dict,
) -> dict:
    return repair_command_sequence(
        user_request,
        verifier_result=verifier_result,
        previous_command_sequence=command_sequence,
    )


def generate_chunked_verified_command_sequence(
    user_request: str,
    max_chunks: int = 6,
    max_repair_attempts_per_chunk: int = 1,
    final_repair_attempts: int = 1,
    repair_on_approve_with_notes: bool = False,
) -> dict:
    """Generate, verify, and final-repair a chunked command sequence."""
    clean_request = user_request.strip()

    if not clean_request:
        raise ValueError("user_request cannot be empty")

    if max_chunks < 1 or max_chunks > 12:
        raise ValueError("max_chunks must be between 1 and 12")

    if max_repair_attempts_per_chunk < 0:
        raise ValueError("max_repair_attempts_per_chunk must be >= 0")

    if final_repair_attempts < 0:
        raise ValueError("final_repair_attempts must be >= 0")

    try:
        task_plan = plan_drawing_tasks(clean_request, max_chunks=max_chunks)
        chunked_result = generate_chunked_command_sequence(
            clean_request,
            task_plan,
            max_repair_attempts_per_chunk=max_repair_attempts_per_chunk,
        )
    except Exception as exc:
        raise ChunkedCommandOrchestrationError(
            f"Chunked generation failed: {type(exc).__name__}: {exc}"
        ) from exc

    command_sequence = chunked_result["command_sequence"]
    final_repair_attempts_used = 0
    repair_history: list[dict[str, Any]] = []
    verifier_result: dict | None = None

    while True:
        validation_errors = validate_command_sequence(command_sequence)
        if validation_errors:
            repair_history.append(
                _history_entry(
                    reason="final_schema_validation_failed",
                    errors=validation_errors,
                )
            )

            if final_repair_attempts_used >= final_repair_attempts:
                joined_errors = "\n".join(f"- {error}" for error in validation_errors)
                raise ChunkedCommandOrchestrationError(
                    "Final merged command sequence failed validation and no "
                    f"final repair attempts remain:\n{joined_errors}"
                )

            final_repair_attempts_used += 1
            try:
                command_sequence = _repair_for_schema_errors(
                    clean_request,
                    command_sequence,
                    validation_errors,
                )
            except Exception as exc:
                raise ChunkedCommandOrchestrationError(
                    f"Final command repair failed: {type(exc).__name__}: {exc}"
                ) from exc
            continue

        try:
            verifier_result = verify_commands(clean_request, command_sequence)
        except Exception as exc:
            error_message = f"{type(exc).__name__}: {exc}"
            verifier_result = _fallback_verifier_result(error_message)
            repair_history.append(
                _history_entry(
                    reason="verifier_failed_fallback",
                    errors=[error_message],
                    verdict="APPROVE_WITH_NOTES",
                )
            )
            break

        verdict = verifier_result.get("verdict")

        if verdict == "APPROVE":
            break

        if verdict == "APPROVE_WITH_NOTES" and not repair_on_approve_with_notes:
            break

        if verdict == "REJECT":
            reason = "final_verifier_rejected"
        elif verdict == "APPROVE_WITH_NOTES":
            reason = "approve_with_notes_repair"
        else:
            reason = "final_verifier_rejected"

        repair_history.append(
            _history_entry(
                reason=reason,
                errors=_verifier_issue_messages(verifier_result),
                verdict=verdict,
            )
        )

        if final_repair_attempts_used >= final_repair_attempts:
            raise ChunkedCommandOrchestrationError(
                "Final command sequence was not accepted by verifier and no "
                f"final repair attempts remain. Verdict: {verdict}."
            )

        final_repair_attempts_used += 1
        try:
            command_sequence = _repair_for_verifier(
                clean_request,
                command_sequence,
                verifier_result,
            )
        except Exception as exc:
            raise ChunkedCommandOrchestrationError(
                f"Final command repair failed: {type(exc).__name__}: {exc}"
            ) from exc

    return {
        "ok": True,
        "task_plan": task_plan,
        "command_sequence": command_sequence,
        "verifier_result": verifier_result,
        "verifier_verdict": (
            verifier_result.get("verdict")
            if isinstance(verifier_result, dict)
            else None
        ),
        "chunk_count": chunked_result["chunk_count"],
        "chunk_results": chunked_result["chunk_results"],
        "chunk_repair_attempts_used": chunked_result["total_repair_attempts_used"],
        "final_repair_attempts_used": final_repair_attempts_used,
        "repair_history": repair_history,
    }

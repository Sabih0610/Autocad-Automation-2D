"""Multi-agent orchestration for robust Mode 2 command generation.

This module coordinates command generation, schema validation, verifier review,
and repair attempts. It does not execute AutoCAD commands, render previews,
expose API routes, or touch AutoCAD COM.
"""

from __future__ import annotations

from typing import Any

from src.ai.command_generator import generate_commands
from src.ai.command_repairer import repair_command_sequence
from src.ai.command_verifier import verify_commands
from src.framework.commands.schema import validate_command_sequence


class CommandOrchestrationError(Exception):
    """Raised when a valid acceptable command sequence cannot be produced."""


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


def generate_verified_command_sequence(
    user_request: str,
    max_repair_attempts: int = 2,
    repair_on_approve_with_notes: bool = False,
) -> dict:
    """Generate, validate, verify, and repair a command sequence when needed."""
    clean_request = user_request.strip()

    if not clean_request:
        raise ValueError("user_request cannot be empty")

    if max_repair_attempts < 0:
        raise ValueError("max_repair_attempts must be >= 0")

    repair_attempts_used = 0
    repair_history: list[dict[str, Any]] = []
    verifier_result: dict | None = None

    try:
        command_sequence = generate_commands(clean_request)
    except Exception as exc:
        error_message = f"Command generation failed: {type(exc).__name__}: {exc}"
        repair_history.append(
            _history_entry(
                reason="schema_validation_failed",
                errors=[error_message],
            )
        )

        if repair_attempts_used >= max_repair_attempts:
            raise CommandOrchestrationError(error_message) from exc

        repair_attempts_used += 1
        try:
            command_sequence = repair_command_sequence(
                clean_request,
                bad_output=str(exc),
                validation_errors=[error_message],
            )
        except Exception as repair_exc:
            raise CommandOrchestrationError(
                f"Command repair failed: {type(repair_exc).__name__}: {repair_exc}"
            ) from repair_exc

    while True:
        validation_errors = validate_command_sequence(command_sequence)
        if validation_errors:
            repair_history.append(
                _history_entry(
                    reason="schema_validation_failed",
                    errors=validation_errors,
                )
            )

            if repair_attempts_used >= max_repair_attempts:
                joined_errors = "\n".join(f"- {error}" for error in validation_errors)
                raise CommandOrchestrationError(
                    "Command sequence failed schema validation and no repair "
                    f"attempts remain:\n{joined_errors}"
                )

            repair_attempts_used += 1
            try:
                command_sequence = _repair_for_schema_errors(
                    clean_request,
                    command_sequence,
                    validation_errors,
                )
            except Exception as exc:
                raise CommandOrchestrationError(
                    f"Command repair failed: {type(exc).__name__}: {exc}"
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
            reason = "verifier_rejected"
        elif verdict == "APPROVE_WITH_NOTES":
            reason = "approve_with_notes_repair"
        else:
            reason = "verifier_rejected"

        repair_history.append(
            _history_entry(
                reason=reason,
                errors=_verifier_issue_messages(verifier_result),
                verdict=verdict,
            )
        )

        if repair_attempts_used >= max_repair_attempts:
            raise CommandOrchestrationError(
                "Command sequence was not accepted by verifier and no repair "
                f"attempts remain. Verdict: {verdict}."
            )

        repair_attempts_used += 1
        try:
            command_sequence = _repair_for_verifier(
                clean_request,
                command_sequence,
                verifier_result,
            )
        except Exception as exc:
            raise CommandOrchestrationError(
                f"Command repair failed: {type(exc).__name__}: {exc}"
            ) from exc

    return {
        "ok": True,
        "command_sequence": command_sequence,
        "verifier_result": verifier_result,
        "verifier_verdict": (
            verifier_result.get("verdict")
            if isinstance(verifier_result, dict)
            else None
        ),
        "repair_attempts_used": repair_attempts_used,
        "repair_history": repair_history,
    }

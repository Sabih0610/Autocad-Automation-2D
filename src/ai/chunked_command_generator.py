"""Chunked command generation and merge helpers for complex drawings.

This module generates AutoCAD command sequences per planned drawing chunk, then
merges them into one validated command sequence. It does not execute AutoCAD
commands, expose API routes, or render previews.
"""

from __future__ import annotations

import json
from typing import Any

from src.ai.command_generator import generate_commands
from src.ai.command_repairer import repair_command_sequence
from src.framework.commands.schema import (
    COMMAND_SCHEMA_VERSION,
    validate_command_sequence,
)


class ChunkedCommandGenerationError(Exception):
    """Raised when chunked command generation cannot produce valid commands."""


def _require_non_empty_text(value: str, field_name: str) -> str:
    clean_value = value.strip()
    if not clean_value:
        raise ValueError(f"{field_name} cannot be empty")
    return clean_value


def _require_chunk_fields(chunk: dict) -> None:
    missing = [
        field
        for field in ["chunk_id", "goal", "expected_elements"]
        if field not in chunk
    ]
    if missing:
        raise ValueError("chunk missing required fields: " + ", ".join(missing))


def _previous_chunks_summary(previous_chunks: list[dict] | None) -> str:
    if not previous_chunks:
        return "No previous chunks have been generated yet."

    summaries = []
    for result in previous_chunks:
        sequence = result.get("command_sequence", {}) if isinstance(result, dict) else {}
        commands = sequence.get("commands", []) if isinstance(sequence, dict) else []
        summaries.append(
            {
                "chunk_id": result.get("chunk_id"),
                "title": result.get("title"),
                "summary": sequence.get("summary") if isinstance(sequence, dict) else None,
                "command_count": len(commands),
            }
        )

    return json.dumps(summaries, indent=2, sort_keys=True)


def _build_chunk_prompt(
    original_user_request: str,
    task_plan: dict,
    chunk: dict,
    previous_chunks: list[dict] | None,
) -> str:
    expected_elements = chunk.get("expected_elements", [])

    sections = [
        "Original user drawing request:",
        original_user_request,
        "",
        "Overall drawing summary:",
        str(task_plan.get("summary", "")),
        "",
        "Drawing type:",
        str(task_plan.get("drawing_type", "generic CAD sketch")),
        "",
        "Layout strategy:",
        str(task_plan.get("layout_strategy", "No explicit layout strategy provided.")),
        "",
        "Current chunk:",
        json.dumps(
            {
                "chunk_id": chunk.get("chunk_id"),
                "title": chunk.get("title"),
                "goal": chunk.get("goal"),
                "expected_elements": expected_elements,
                "layout_hint": chunk.get("layout_hint"),
            },
            indent=2,
            sort_keys=True,
        ),
        "",
        "Previous chunks already generated:",
        _previous_chunks_summary(previous_chunks),
        "",
        "Chunk generation instructions:",
        "- Generate only this chunk.",
        "- Keep coordinates consistent with previous chunks.",
        "- Use existing layers if appropriate.",
        "- Do not redraw previous chunks unless necessary for this chunk to connect clearly.",
        "- Output a complete valid command sequence for this chunk only.",
        "- Keep command count reasonable.",
    ]

    return "\n".join(sections)


def generate_commands_for_chunk(
    original_user_request: str,
    task_plan: dict,
    chunk: dict,
    previous_chunks: list[dict] | None = None,
    max_repair_attempts: int = 1,
) -> dict:
    """Generate and validate a command sequence for a single drawing chunk."""
    clean_request = _require_non_empty_text(
        original_user_request,
        "original_user_request",
    )

    if not isinstance(task_plan, dict):
        raise ValueError("task_plan must be a dict")

    if not isinstance(chunk, dict):
        raise ValueError("chunk must be a dict")

    if max_repair_attempts < 0:
        raise ValueError("max_repair_attempts must be >= 0")

    _require_chunk_fields(chunk)

    chunk_prompt = _build_chunk_prompt(
        clean_request,
        task_plan,
        chunk,
        previous_chunks,
    )

    try:
        command_sequence = generate_commands(chunk_prompt)
    except Exception as exc:
        raise ChunkedCommandGenerationError(
            f"Chunk {chunk.get('chunk_id')} generation failed: {type(exc).__name__}: {exc}"
        ) from exc

    repair_attempts_used = 0

    while True:
        validation_errors = validate_command_sequence(command_sequence)
        if not validation_errors:
            return {
                "chunk_id": chunk["chunk_id"],
                "title": chunk.get("title"),
                "command_sequence": command_sequence,
                "repair_attempts_used": repair_attempts_used,
                "errors": [],
            }

        if repair_attempts_used >= max_repair_attempts:
            joined_errors = "\n".join(f"- {error}" for error in validation_errors)
            raise ChunkedCommandGenerationError(
                f"Chunk {chunk.get('chunk_id')} failed validation and no repair "
                f"attempts remain:\n{joined_errors}"
            )

        repair_attempts_used += 1
        try:
            command_sequence = repair_command_sequence(
                chunk_prompt,
                bad_output=command_sequence,
                validation_errors=validation_errors,
                previous_command_sequence=command_sequence,
            )
        except Exception as exc:
            raise ChunkedCommandGenerationError(
                f"Chunk {chunk.get('chunk_id')} repair failed: {type(exc).__name__}: {exc}"
            ) from exc


def _dedupe_assumptions(values: list[str]) -> list[str]:
    seen = set()
    result = []

    for value in values:
        if not isinstance(value, str):
            continue
        if value in seen:
            continue
        seen.add(value)
        result.append(value)

    return result


def merge_chunk_command_sequences(
    original_user_request: str,
    task_plan: dict,
    chunk_results: list[dict],
) -> dict:
    """Merge validated chunk command sequences into one command sequence."""
    _require_non_empty_text(original_user_request, "original_user_request")

    if not isinstance(task_plan, dict):
        raise ValueError("task_plan must be a dict")

    if not isinstance(chunk_results, list) or not chunk_results:
        raise ChunkedCommandGenerationError("chunk_results must be a non-empty list")

    merged_commands = []
    seen_layers = set()
    assumptions = list(task_plan.get("assumptions", []))

    for result in chunk_results:
        sequence = result.get("command_sequence") if isinstance(result, dict) else None
        if not isinstance(sequence, dict):
            raise ChunkedCommandGenerationError("Each chunk result must include command_sequence")

        sequence_errors = validate_command_sequence(sequence)
        if sequence_errors:
            joined_errors = "\n".join(f"- {error}" for error in sequence_errors)
            raise ChunkedCommandGenerationError(
                f"Chunk {result.get('chunk_id')} command sequence is invalid:\n{joined_errors}"
            )

        assumptions.extend(sequence.get("assumptions", []))

        for command in sequence.get("commands", []):
            if command.get("command") == "LAYER":
                layer_name = command.get("layer_name")
                if layer_name in seen_layers:
                    continue
                seen_layers.add(layer_name)
            merged_commands.append(command)

    assumptions.append(
        "Layout was generated as a draft-quality schematic from chunked generation."
    )

    merged_sequence = {
        "schema_version": COMMAND_SCHEMA_VERSION,
        "summary": (
            "Merged command sequence from chunked generation for: "
            f"{task_plan.get('summary', original_user_request)}"
        ),
        "estimated_drawing_type": task_plan.get("drawing_type"),
        "assumptions": _dedupe_assumptions(assumptions),
        "commands": merged_commands,
    }

    validation_errors = validate_command_sequence(merged_sequence)
    if validation_errors:
        joined_errors = "\n".join(f"- {error}" for error in validation_errors)
        raise ChunkedCommandGenerationError(
            f"Merged command sequence failed validation:\n{joined_errors}"
        )

    return merged_sequence


def generate_chunked_command_sequence(
    user_request: str,
    task_plan: dict,
    max_repair_attempts_per_chunk: int = 1,
) -> dict:
    """Generate commands for all task-plan chunks and merge them."""
    clean_request = _require_non_empty_text(user_request, "user_request")

    if not isinstance(task_plan, dict):
        raise ValueError("task_plan must be a dict")

    if max_repair_attempts_per_chunk < 0:
        raise ValueError("max_repair_attempts_per_chunk must be >= 0")

    chunks = task_plan.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        raise ChunkedCommandGenerationError("task_plan must include non-empty chunks")

    sorted_chunks = sorted(chunks, key=lambda item: item.get("priority", 999999))
    chunk_results: list[dict[str, Any]] = []

    for chunk in sorted_chunks:
        chunk_result = generate_commands_for_chunk(
            clean_request,
            task_plan,
            chunk,
            previous_chunks=chunk_results,
            max_repair_attempts=max_repair_attempts_per_chunk,
        )
        chunk_results.append(chunk_result)

    merged_sequence = merge_chunk_command_sequences(
        clean_request,
        task_plan,
        chunk_results,
    )

    return {
        "ok": True,
        "command_sequence": merged_sequence,
        "chunk_results": chunk_results,
        "chunk_count": len(chunk_results),
        "total_repair_attempts_used": sum(
            int(result.get("repair_attempts_used", 0))
            for result in chunk_results
        ),
    }

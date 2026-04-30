"""AI repair agent for Mode 2 AutoCAD command sequences.

This module repairs bad or partial command JSON into a validated command
sequence. It does not execute AutoCAD commands, expose API routes, modify the
generator/verifier, or render previews.
"""

from __future__ import annotations

import json
from typing import Any

from src.ai.client import ask_ai
from src.framework.commands.schema import (
    COMMAND_SCHEMA,
    COMMAND_SCHEMA_VERSION,
    validate_command_sequence,
)


COMMAND_REPAIR_SYSTEM_PROMPT = f"""
You repair AutoCAD command JSON.

You receive:
- the original user drawing request
- bad or partial command output
- schema validation errors
- verifier feedback
- optionally a previous command sequence

Your job:
- Return one complete corrected JSON object matching the provided schema.
- Output JSON only.
- Do not output markdown.
- Do not output code fences.
- Do not output explanations outside JSON.
- Do not return raw AutoCAD script.
- Do not invent unsupported command types.
- Use only these command types:
  - LAYER
  - LINE
  - CIRCLE
  - ARC
  - ELLIPSE
  - POLYLINE
  - TEXT
  - INSERT
  - DIM_LINEAR
- Always include schema_version "{COMMAND_SCHEMA_VERSION}".
- Always include summary.
- Always include assumptions.
- Always include commands.
- Preserve the original user intent as much as possible.
- For complex drawings, simplify safely instead of failing.
- If the original request is too complex, produce a simpler but coherent
  draft-quality drawing and mention simplifications in assumptions.
- Keep command count under 1000.
- Use millimeters.
- Create layers before drawing on them.
- Avoid long unclosed strings.
- Avoid trailing comments.
- Avoid JSON syntax mistakes.
- If verifier says a component is missing, add commands for it.
- If verifier says geometry overlaps or is disconnected, adjust coordinates or
  add connecting lines.
- If schema validation errors mention a field path, fix that field.

For complex P&ID-style requests:
- Prefer a clean schematic layout.
- Use simple linework, circles, text, and placeholder valve symbols.
- Do not attempt fabrication-grade detail.
- Use approximations and document them in assumptions.
""".strip()


def _format_context(value: Any) -> str:
    if value is None:
        return "None provided."

    if isinstance(value, str):
        return value

    try:
        return json.dumps(value, indent=2, sort_keys=True)
    except Exception:
        return str(value)


def _build_repair_prompt(
    user_request: str,
    bad_output: str | dict | None = None,
    validation_errors: list[str] | None = None,
    verifier_result: dict | None = None,
    previous_command_sequence: dict | None = None,
) -> str:
    sections = [
        "Original user drawing request:",
        user_request,
        "",
        "Bad or partial command output:",
        _format_context(bad_output),
        "",
        "Schema validation errors:",
        _format_context(validation_errors or []),
        "",
        "Verifier result and issues:",
        _format_context(verifier_result),
        "",
        "Previous command sequence, if any:",
        _format_context(previous_command_sequence),
        "",
        "Repair instructions:",
        (
            "Return one complete corrected command sequence JSON object. "
            "It must satisfy the provided schema and preserve the user's "
            "drawing intent as much as possible."
        ),
    ]

    return "\n".join(sections)


def repair_command_sequence(
    user_request: str,
    bad_output: str | dict | None = None,
    validation_errors: list[str] | None = None,
    verifier_result: dict | None = None,
    previous_command_sequence: dict | None = None,
) -> dict:
    """Repair a bad command output and return a validated command sequence."""
    clean_request = user_request.strip()

    if not clean_request:
        raise ValueError("user_request cannot be empty")

    repair_prompt = _build_repair_prompt(
        user_request=clean_request,
        bad_output=bad_output,
        validation_errors=validation_errors,
        verifier_result=verifier_result,
        previous_command_sequence=previous_command_sequence,
    )

    result = ask_ai(
        prompt=repair_prompt,
        schema=COMMAND_SCHEMA,
        system_prompt=COMMAND_REPAIR_SYSTEM_PROMPT,
        max_retries=2,
    )

    if not isinstance(result, dict):
        raise ValueError("Repaired command sequence must be a dict")

    result.setdefault("schema_version", COMMAND_SCHEMA_VERSION)

    remaining_errors = validate_command_sequence(result)
    if remaining_errors:
        joined_errors = "\n".join(f"- {error}" for error in remaining_errors)
        raise ValueError(f"Repaired command sequence failed validation:\n{joined_errors}")

    return result

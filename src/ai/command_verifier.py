"""AI verifier for Mode 2 AutoCAD command sequences.

This module reviews generated command JSON and returns structured verifier JSON.
It does not execute AutoCAD commands, call COM, expose API routes, or render
previews.
"""

from __future__ import annotations

import json
from typing import Any

from src.ai.client import ask_ai
from src.framework.commands.verification_schema import (
    VERIFICATION_SCHEMA,
    VERIFICATION_SCHEMA_VERSION,
    validate_verification_result,
)


COMMAND_VERIFIER_SYSTEM_PROMPT = f"""
You are reviewing an AutoCAD command sequence produced by another AI.

Check only mechanical and internal drafting issues, such as:
- unknown-looking or inconsistent layer usage
- missing closing side of a rectangle or polyline when obvious
- negative or zero dimensions or radii if somehow present
- zero-length lines
- zero-length arcs
- text with unclear placement
- dimension commands that appear disconnected from the geometry
- coordinate jumps that look accidental
- duplicate geometry that appears accidental
- commands that do not appear to satisfy the user request
- obvious overlap warnings

Do not claim to verify engineering correctness:
- no ASME validation
- no ANSI/API validation
- no pressure design
- no pipe schedule verification
- no guarantee of fabrication readiness

Verdict rules:
- APPROVE: command sequence appears internally consistent and executable.
- APPROVE_WITH_NOTES: sequence can likely execute, but there are warnings or
  concerns the engineer should review.
- REJECT: blocker issue exists; commands should not execute without correction.

Output JSON only and match the provided schema exactly.
Do not output markdown.
Do not output prose outside JSON.

The output must include:
- schema_version: "{VERIFICATION_SCHEMA_VERSION}"
- verdict
- summary
- issues
- command_annotations
""".strip()


def _require_generator_fields(generator_output: dict[str, Any]) -> None:
    required_fields = [
        "summary",
        "assumptions",
        "commands",
    ]
    missing = [
        field
        for field in required_fields
        if field not in generator_output
    ]

    if missing:
        raise ValueError(
            "generator_output missing required fields: " + ", ".join(missing)
        )


def _build_verifier_prompt(user_request: str, generator_output: dict[str, Any]) -> str:
    estimated_drawing_type = generator_output.get("estimated_drawing_type")
    assumptions = generator_output.get("assumptions", [])
    commands = generator_output.get("commands", [])
    command_json = json.dumps(generator_output, indent=2, sort_keys=True)

    sections = [
        "Original user request:",
        user_request,
        "",
        "Generator summary:",
        str(generator_output.get("summary", "")),
        "",
        "Generator estimated drawing type:",
        str(estimated_drawing_type) if estimated_drawing_type else "unspecified",
        "",
        "Generator assumptions:",
        json.dumps(assumptions, indent=2),
        "",
        "Command count:",
        str(len(commands)),
        "",
        "Full command sequence JSON:",
        command_json,
    ]

    return "\n".join(sections)


def verify_commands(
    user_request: str,
    generator_output: dict,
) -> dict:
    """Verify a generated command sequence and return structured verifier JSON."""
    clean_request = user_request.strip()

    if not clean_request:
        raise ValueError("user_request cannot be empty")

    if not isinstance(generator_output, dict):
        raise ValueError("generator_output must be a dict")

    _require_generator_fields(generator_output)

    full_prompt = _build_verifier_prompt(clean_request, generator_output)

    result = ask_ai(
        prompt=full_prompt,
        schema=VERIFICATION_SCHEMA,
        system_prompt=COMMAND_VERIFIER_SYSTEM_PROMPT,
        max_retries=2,
    )

    result.setdefault("schema_version", VERIFICATION_SCHEMA_VERSION)

    validation_errors = validate_verification_result(result)
    if validation_errors:
        joined_errors = "\n".join(f"- {error}" for error in validation_errors)
        raise ValueError(f"Verifier result failed validation:\n{joined_errors}")

    return result

"""AI command-sequence generator for Mode 2 draft drawings.

This module only converts natural language into validated command JSON. It does
not execute AutoCAD commands, call COM, expose API routes, or render previews.
"""

from __future__ import annotations

from src.ai.client import ask_ai
from src.framework.commands.schema import (
    COMMAND_SCHEMA,
    COMMAND_SCHEMA_VERSION,
    validate_command_sequence,
)


COMMAND_GENERATOR_SYSTEM_PROMPT = f"""
You are an AutoCAD command generator for draft and concept drawings.

Your job is to convert the user's natural-language drawing request into valid
JSON only. The JSON must match the provided schema exactly.

Output this top-level structure:
{{
  "schema_version": "{COMMAND_SCHEMA_VERSION}",
  "summary": "...",
  "estimated_drawing_type": "...",
  "assumptions": ["..."],
  "commands": []
}}

Rules:
- Output JSON only.
- Do not output markdown.
- Do not output code fences.
- Do not output raw AutoCAD script.
- Do not invent unsupported command types.
- Always include schema_version "{COMMAND_SCHEMA_VERSION}".
- Always include assumptions, even if empty.
- Do not output more than 1000 commands.
- All coordinates are in millimeters.
- Origin (0,0) is bottom-left unless the user specifies otherwise.
- X positive is right, Y positive is up.
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
- Create layers before drawing on them.
- Use simple, readable layer names like:
  - BORDER
  - SHELL
  - NOZZLE
  - CENTERLINE
  - DIMENSION
  - TEXT
  - EQUIPMENT
  - PIPING
- Keep drawings simple and draft-quality.
- This is not fabrication-grade output.
- If the user asks for engineering precision, add an assumption that dimensions
  must be engineer-verified.

Good example for "draw a rectangle 1000 by 500":
- Create a layer such as BORDER.
- Draw four LINE commands from [0,0] to [1000,0] to [1000,500] to [0,500] to
  [0,0].
- Add a short TEXT label if helpful.

Good example for "draw a simple vessel sketch":
- Use LINE, ELLIPSE, CIRCLE, and TEXT commands.
- Do not try to calculate ASME or fabrication details.
- Add assumptions explaining the sketch is approximate and must be
  engineer-verified for real use.
""".strip()


def generate_commands(user_request: str) -> dict:
    """Generate and validate a strict AutoCAD command sequence."""
    clean_request = user_request.strip()

    if not clean_request:
        raise ValueError("user_request cannot be empty")

    result = ask_ai(
        prompt=clean_request,
        schema=COMMAND_SCHEMA,
        system_prompt=COMMAND_GENERATOR_SYSTEM_PROMPT,
        max_retries=2,
    )

    result.setdefault("schema_version", COMMAND_SCHEMA_VERSION)

    validation_errors = validate_command_sequence(result)
    if validation_errors:
        joined_errors = "\n".join(f"- {error}" for error in validation_errors)
        raise ValueError(f"Generated command sequence failed validation:\n{joined_errors}")

    return result

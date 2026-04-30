"""AI drawing task planner for chunked Mode 2 generation.

This module decomposes a drawing request into validated logical chunks. It does
not generate AutoCAD commands, execute AutoCAD operations, expose API routes, or
render previews.
"""

from __future__ import annotations

from src.ai.client import ask_ai
from src.framework.commands.planning_schema import (
    DRAWING_TASK_PLAN_SCHEMA,
    PLANNING_SCHEMA_VERSION,
    validate_drawing_task_plan,
)


DRAWING_TASK_PLANNER_SYSTEM_PROMPT = f"""
You are a drawing decomposition agent.

Your job:
- Read a user drawing request.
- Break it into small chunks that can each be converted into AutoCAD commands
  later.
- Do not output AutoCAD command objects.
- Do not output raw AutoCAD script.
- Output JSON only.
- Do not output markdown or code fences.
- Each chunk should be small and coherent.
- Chunks should be ordered by priority.
- For complex drawings, prefer 4 to 8 chunks.
- For simple drawings, 1 to 3 chunks are enough.
- Keep chunks generic enough to support:
  - P&ID-style sketches
  - plot plans
  - equipment layouts
  - single-line diagrams
  - generic CAD sketches
- Include assumptions when layout or details are not specified.
- Always include schema_version "{PLANNING_SCHEMA_VERSION}".

For P&ID-style prompts, suggested chunking:
- equipment
- main piping/header
- branches
- valves
- instruments
- labels/annotations

For layout prompts:
- boundary/grid
- major equipment
- connecting paths
- labels/annotations

For SLD prompts:
- source/transformer
- busbar
- feeders
- loads
- labels/protection
""".strip()


def _build_planner_prompt(user_request: str, max_chunks: int) -> str:
    return "\n".join(
        [
            "Original user drawing request:",
            user_request,
            "",
            "Planning constraint:",
            f"Break this drawing into at most {max_chunks} logical chunks.",
            "",
            "Output one JSON object matching the provided planning schema.",
        ]
    )


def plan_drawing_tasks(user_request: str, max_chunks: int = 6) -> dict:
    """Plan a drawing request into validated generation chunks."""
    clean_request = user_request.strip()

    if not clean_request:
        raise ValueError("user_request cannot be empty")

    if max_chunks < 1 or max_chunks > 12:
        raise ValueError("max_chunks must be between 1 and 12")

    planner_prompt = _build_planner_prompt(clean_request, max_chunks)

    result = ask_ai(
        prompt=planner_prompt,
        schema=DRAWING_TASK_PLAN_SCHEMA,
        system_prompt=DRAWING_TASK_PLANNER_SYSTEM_PROMPT,
        max_retries=2,
    )

    if not isinstance(result, dict):
        raise ValueError("Drawing task plan must be a dict")

    result.setdefault("schema_version", PLANNING_SCHEMA_VERSION)

    validation_errors = validate_drawing_task_plan(result)
    if validation_errors:
        joined_errors = "\n".join(f"- {error}" for error in validation_errors)
        raise ValueError(f"Drawing task plan failed validation:\n{joined_errors}")

    if len(result.get("chunks", [])) > max_chunks:
        raise ValueError(
            f"Drawing task plan exceeded max_chunks: "
            f"{len(result.get('chunks', []))} > {max_chunks}"
        )

    return result

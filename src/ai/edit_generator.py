"""AI live edit-plan generator for active AutoCAD drawings.

This module converts a user edit request plus a read-only drawing inspection
into a validated edit plan. It does not execute edits, call AutoCAD COM, expose
API routes, or modify drawings.
"""

from __future__ import annotations

import json
from typing import Any

from src.ai.client import ask_ai
from src.framework.commands.edit_schema import (
    EDIT_PLAN_SCHEMA,
    EDIT_SCHEMA_VERSION,
    validate_edit_plan,
)


MAX_PROMPT_ENTITIES = 100


EDIT_GENERATOR_SYSTEM_PROMPT = f"""
You are an AutoCAD live edit planner.

You receive:
- a user edit request
- a list of current drawing entities with AutoCAD handles

Your job:
- Produce an edit plan matching the provided schema exactly.
- Identify existing entities to delete using delete_handles.
- Add new geometry using commands.
- Represent movement or replacement as delete old entity plus add new entity.
- Never directly modify AutoCAD.
- Never output raw AutoCAD script.
- Never invent handles that are not in the provided entity list.
- If unsure which entity the user means, choose the most likely one and
  document the assumption.
- If the request is impossible or too ambiguous, do not guess broad destructive
  edits. A plan with no deletes and no commands is invalid, so only produce a
  safe minimal plan when the target is genuinely clear.
- Always include assumptions, even if empty.
- Always include schema_version "{EDIT_SCHEMA_VERSION}".
- Output JSON only.
- Do not output markdown or code fences.

Rules:
- For "delete" or "remove X", put the matching entity handle in
  delete_handles.
- For "move X", use delete old handle plus add a replacement command with
  adjusted coordinates.
- For "change text", delete old text handle plus add a new TEXT command.
- For "add X", leave delete_handles empty and add commands.
- For "make circle larger", delete old circle handle plus add a new CIRCLE
  with a larger radius.
- Keep edits small and local.
- Do not delete multiple entities unless the user clearly asks or the target
  object is made of multiple parts.
- Use the existing entity's layer when replacing it unless the user specifies
  otherwise.

Example:
If the inspection contains:
{{"handle": "26C", "object_name": "AcDbCircle", "layer": "CENTERLINE", "center": [500, 250, 0], "radius": 100}}

And user says:
Delete the center circle

Return:
{{
  "schema_version": "{EDIT_SCHEMA_VERSION}",
  "edit_intent": "Delete the center circle.",
  "summary": "Delete one circle entity from the active drawing.",
  "target_description": "Circle on layer CENTERLINE at center [500, 250, 0].",
  "assumptions": ["Interpreted 'center circle' as handle 26C because it is the only circle in the drawing."],
  "delete_handles": ["26C"],
  "commands": []
}}
""".strip()


_ENTITY_PROMPT_FIELDS = [
    "handle",
    "object_name",
    "entity_type",
    "layer",
    "center",
    "radius",
    "start_point",
    "end_point",
    "position",
    "text",
    "bbox",
]


def _require_inspection_fields(drawing_inspection: dict[str, Any]) -> None:
    required_fields = [
        "document_name",
        "entities",
    ]
    missing = [
        field
        for field in required_fields
        if field not in drawing_inspection
    ]

    if missing:
        raise ValueError(
            "drawing_inspection missing required fields: " + ", ".join(missing)
        )

    if not isinstance(drawing_inspection.get("entities"), list):
        raise ValueError("drawing_inspection entities must be a list")


def _compact_entities(drawing_inspection: dict[str, Any]) -> list[dict[str, Any]]:
    entities = drawing_inspection.get("entities", [])[:MAX_PROMPT_ENTITIES]
    compact_entities = []

    for entity in entities:
        if not isinstance(entity, dict):
            continue

        compact_entities.append(
            {
                field: entity.get(field)
                for field in _ENTITY_PROMPT_FIELDS
                if field in entity
            }
        )

    return compact_entities


def _build_edit_prompt(user_request: str, drawing_inspection: dict[str, Any]) -> str:
    entities = drawing_inspection.get("entities", [])
    compact_entities = _compact_entities(drawing_inspection)

    sections = [
        "User edit request:",
        user_request,
        "",
        "Document name:",
        str(drawing_inspection.get("document_name", "")),
        "",
        "Entity count returned:",
        str(drawing_inspection.get("entity_count_returned", len(entities))),
        "",
        f"Current drawing entities (first {len(compact_entities)} of {len(entities)} returned):",
        json.dumps(compact_entities, indent=2, sort_keys=True),
    ]

    return "\n".join(sections)


def generate_edit_plan(
    user_request: str,
    drawing_inspection: dict,
) -> dict:
    """Generate and validate a live edit plan for the inspected drawing."""
    clean_request = user_request.strip()

    if not clean_request:
        raise ValueError("user_request cannot be empty")

    if not isinstance(drawing_inspection, dict):
        raise ValueError("drawing_inspection must be a dict")

    _require_inspection_fields(drawing_inspection)

    full_prompt = _build_edit_prompt(clean_request, drawing_inspection)

    result = ask_ai(
        prompt=full_prompt,
        schema=EDIT_PLAN_SCHEMA,
        system_prompt=EDIT_GENERATOR_SYSTEM_PROMPT,
        max_retries=2,
    )

    if not isinstance(result, dict):
        raise ValueError("Generated edit plan must be a dict")

    result.setdefault("schema_version", EDIT_SCHEMA_VERSION)

    validation_errors = validate_edit_plan(result)
    if validation_errors:
        joined_errors = "\n".join(f"- {error}" for error in validation_errors)
        raise ValueError(f"Generated edit plan failed validation:\n{joined_errors}")

    return result

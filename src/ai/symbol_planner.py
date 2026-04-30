"""
Symbol planner for AutoCAD automation.

This module converts natural language drafting instructions into
strict JSON for symbol placement.

Important:
- This file does NOT touch AutoCAD.
- This file only plans the operation.
- Phase 5 will pass this JSON into the AutoCAD executor.
"""

from __future__ import annotations

from typing import Any, Dict

from src.ai.client import ask_ai


NON_EMPTY_STRING = {
    "type": "string",
    "minLength": 1,
}


SYMBOL_PLACEMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "task_type": {
            "type": "string",
            "enum": ["place_symbol"],
        },
        "block_name": {
            "type": "string",
            "enum": [
                "GATE_VALVE",
                "CHECK_VALVE",
                "CONTROL_VALVE",
                "PUMP",
                "VESSEL",
                "INSTRUMENT_BUBBLE",
            ],
        },
        "insertion_point": {
            "type": "object",
            "properties": {
                "x": {"type": "number"},
                "y": {"type": "number"},
                "z": {"type": "number"},
            },
            "required": ["x", "y", "z"],
            "additionalProperties": False,
        },
        "rotation_degrees": {"type": "number"},
        "scale": {"type": "number"},
        "layer": NON_EMPTY_STRING,
        "attributes": {
            "type": "object",
            "properties": {
                "TAG": NON_EMPTY_STRING,
                "SIZE": NON_EMPTY_STRING,
                "SERVICE": NON_EMPTY_STRING,
            },
            "required": ["TAG", "SIZE", "SERVICE"],
            "additionalProperties": False,
        },
    },
    "required": [
        "task_type",
        "block_name",
        "insertion_point",
        "rotation_degrees",
        "scale",
        "layer",
        "attributes",
    ],
    "additionalProperties": False,
}


SYMBOL_PLANNER_SYSTEM_PROMPT = """
You are converting drafting instructions into AutoCAD symbol placement JSON.

Use these exact block mappings:
- gate valve = GATE_VALVE
- check valve = CHECK_VALVE
- control valve = CONTROL_VALVE
- pump = PUMP
- vessel = VESSEL
- instrument bubble = INSTRUMENT_BUBBLE

Rules:
- task_type must always be place_symbol.
- z must always be 0 unless the user gives a z coordinate.
- rotation_degrees must be 0 unless the user gives a rotation.
- scale must be 1 unless the user gives a scale.
- Preserve layer names exactly as written by the user.
- Put tag, size, and service inside attributes.
- If size is not mentioned, use "UNKNOWN".
- If service is not mentioned, use "UNKNOWN".
- Never return empty strings.
- Never add fields that are not in the schema.
- Do not invent coordinates. If coordinates are missing, return x=0 and y=0 only if the user clearly asks for a default location.
"""


def plan_symbol_placement(user_request: str) -> Dict[str, Any]:
    """
    Convert a natural language drafting instruction into symbol placement JSON.

    Args:
        user_request:
            Example:
            "Place a 6 inch gate valve at 100, 200 on layer P-VALVES with tag V-2045."

    Returns:
        Dictionary matching SYMBOL_PLACEMENT_SCHEMA.
    """
    clean_request = user_request.strip()

    if not clean_request:
        raise ValueError("user_request cannot be empty")

    return ask_ai(
        prompt=clean_request,
        schema=SYMBOL_PLACEMENT_SCHEMA,
        system_prompt=SYMBOL_PLANNER_SYSTEM_PROMPT,
    )
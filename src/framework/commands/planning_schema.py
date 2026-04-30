"""Strict JSON schema for chunked drawing task plans.

Phase 28.4A defines only a planning schema and validation helpers. It does not
generate AutoCAD commands, execute commands, expose API routes, or render
previews.
"""

from __future__ import annotations

from typing import Any

from jsonschema import Draft7Validator


PLANNING_SCHEMA_VERSION = "1.0"


DRAWING_TASK_PLAN_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "AutoCAD AI Drawing Task Plan",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "drawing_type",
        "summary",
        "assumptions",
        "chunks",
    ],
    "properties": {
        "schema_version": {
            "const": PLANNING_SCHEMA_VERSION,
        },
        "drawing_type": {
            "type": "string",
            "minLength": 1,
        },
        "summary": {
            "type": "string",
            "minLength": 1,
        },
        "assumptions": {
            "type": "array",
            "items": {
                "type": "string",
            },
        },
        "layout_strategy": {
            "type": "string",
            "minLength": 1,
        },
        "chunks": {
            "type": "array",
            "minItems": 1,
            "maxItems": 12,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "chunk_id",
                    "title",
                    "goal",
                    "priority",
                    "expected_elements",
                ],
                "properties": {
                    "chunk_id": {
                        "type": "string",
                        "minLength": 1,
                        "pattern": "^[A-Za-z0-9_-]+$",
                    },
                    "title": {
                        "type": "string",
                        "minLength": 1,
                    },
                    "goal": {
                        "type": "string",
                        "minLength": 1,
                    },
                    "priority": {
                        "type": "integer",
                        "minimum": 1,
                    },
                    "expected_elements": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "minLength": 1,
                        },
                    },
                    "layout_hint": {
                        "type": "string",
                        "minLength": 1,
                    },
                },
            },
        },
    },
}


_VALIDATOR = Draft7Validator(DRAWING_TASK_PLAN_SCHEMA)


def _format_path(path_parts: Any) -> str:
    path = "root"

    for part in path_parts:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}"

    return path


def _format_error(error: Any) -> str:
    path = _format_path(error.absolute_path)
    return f"{path}: {error.message}"


def validate_drawing_task_plan(data: dict) -> list[str]:
    """Return readable validation errors for a drawing task plan."""
    errors = sorted(
        _VALIDATOR.iter_errors(data),
        key=lambda error: (
            [str(part) for part in error.absolute_path],
            error.message,
        ),
    )

    return [_format_error(error) for error in errors]


def is_valid_drawing_task_plan(data: dict) -> bool:
    """Return True when the drawing task plan satisfies the planning schema."""
    return not validate_drawing_task_plan(data)

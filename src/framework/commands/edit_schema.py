"""Strict JSON schema for live edit plans.

Phase 27.3 defines only the schema and validation helpers for future live edit
plans. It does not execute edits, call AI, expose API routes, or modify AutoCAD.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from jsonschema import Draft7Validator

from src.framework.commands.schema import COMMAND_SCHEMA, COMMAND_SCHEMA_VERSION


EDIT_SCHEMA_VERSION = COMMAND_SCHEMA_VERSION


_COMMAND_TYPES = COMMAND_SCHEMA["properties"]["commands"]["items"]["properties"]["command"]["enum"]


def _edit_commands_schema() -> dict[str, Any]:
    commands_schema = deepcopy(COMMAND_SCHEMA["properties"]["commands"])
    commands_schema["minItems"] = 0
    return commands_schema


EDIT_PLAN_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "AutoCAD AI Live Edit Plan",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "edit_intent",
        "summary",
        "assumptions",
        "delete_handles",
        "commands",
    ],
    "properties": {
        "schema_version": {
            "const": EDIT_SCHEMA_VERSION,
        },
        "edit_intent": {
            "type": "string",
            "minLength": 1,
        },
        "summary": {
            "type": "string",
            "minLength": 1,
        },
        "target_description": {
            "type": "string",
            "minLength": 1,
        },
        "assumptions": {
            "type": "array",
            "items": {
                "type": "string",
            },
        },
        "delete_handles": {
            "type": "array",
            "items": {
                "type": "string",
                "minLength": 1,
            },
        },
        "commands": _edit_commands_schema(),
    },
    "definitions": deepcopy(COMMAND_SCHEMA["definitions"]),
}


_VALIDATOR = Draft7Validator(EDIT_PLAN_SCHEMA)


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

    if error.validator == "enum" and list(error.absolute_path)[-1:] == ["command"]:
        return (
            f"{path}: unknown command type {error.instance!r}. "
            f"Allowed command types: {', '.join(_COMMAND_TYPES)}."
        )

    return f"{path}: {error.message}"


def _has_edit_action(data: dict) -> bool:
    delete_handles = data.get("delete_handles")
    commands = data.get("commands")

    return (
        isinstance(delete_handles, list)
        and len(delete_handles) > 0
    ) or (
        isinstance(commands, list)
        and len(commands) > 0
    )


def validate_edit_plan(data: dict) -> list[str]:
    """Return readable validation errors for a live edit plan."""
    errors = sorted(
        _VALIDATOR.iter_errors(data),
        key=lambda error: (
            [str(part) for part in error.absolute_path],
            error.message,
        ),
    )

    messages = [_format_error(error) for error in errors]

    if isinstance(data, dict) and not _has_edit_action(data):
        messages.append(
            "root: at least one of delete_handles or commands must be non-empty."
        )

    return messages


def is_valid_edit_plan(data: dict) -> bool:
    """Return True when the edit plan satisfies EDIT_PLAN_SCHEMA."""
    return not validate_edit_plan(data)

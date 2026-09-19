"""Strict JSON schema for deterministic AutoCAD command sequences.

Phase 23.1 only defines the schema and validation helpers. It does not call AI,
AutoCAD, API routes, or rendering code.
"""

from __future__ import annotations

from typing import Any

from jsonschema import Draft7Validator


COMMAND_SCHEMA_VERSION = "1.0"


_COMMAND_TYPES = [
    "LAYER",
    "LINE",
    "CIRCLE",
    "ARC",
    "ELLIPSE",
    "POLYLINE",
    "TEXT",
    "INSERT",
    "DIM_LINEAR",
]


_COORDINATE_SCHEMA = {
    "type": "array",
    "items": {"type": "number"},
    "minItems": 2,
    "maxItems": 2,
}


_LAYER_PROPERTY = {
    "type": "string",
    "minLength": 1,
}


_COMMENT_PROPERTY = {
    "type": "string",
}


COMMAND_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "AutoCAD AI Command Sequence",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "summary",
        "assumptions",
        "commands",
    ],
    "properties": {
        "schema_version": {
            "const": COMMAND_SCHEMA_VERSION,
        },
        "summary": {
            "type": "string",
            "minLength": 1,
        },
        "estimated_drawing_type": {
            "type": "string",
            "minLength": 1,
        },
        "assumptions": {
            "type": "array",
            "items": {
                "type": "string",
            },
        },
        "commands": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["command"],
                "properties": {
                    "command": {
                        "enum": _COMMAND_TYPES,
                    },
                },
                "allOf": [
                    {
                        "if": {
                            "required": ["command"],
                            "properties": {"command": {"const": "LAYER"}},
                        },
                        "then": {"$ref": "#/definitions/layer_command"},
                    },
                    {
                        "if": {
                            "required": ["command"],
                            "properties": {"command": {"const": "LINE"}},
                        },
                        "then": {"$ref": "#/definitions/line_command"},
                    },
                    {
                        "if": {
                            "required": ["command"],
                            "properties": {"command": {"const": "CIRCLE"}},
                        },
                        "then": {"$ref": "#/definitions/circle_command"},
                    },
                    {
                        "if": {
                            "required": ["command"],
                            "properties": {"command": {"const": "ARC"}},
                        },
                        "then": {"$ref": "#/definitions/arc_command"},
                    },
                    {
                        "if": {
                            "required": ["command"],
                            "properties": {"command": {"const": "ELLIPSE"}},
                        },
                        "then": {"$ref": "#/definitions/ellipse_command"},
                    },
                    {
                        "if": {
                            "required": ["command"],
                            "properties": {"command": {"const": "POLYLINE"}},
                        },
                        "then": {"$ref": "#/definitions/polyline_command"},
                    },
                    {
                        "if": {
                            "required": ["command"],
                            "properties": {"command": {"const": "TEXT"}},
                        },
                        "then": {"$ref": "#/definitions/text_command"},
                    },
                    {
                        "if": {
                            "required": ["command"],
                            "properties": {"command": {"const": "INSERT"}},
                        },
                        "then": {"$ref": "#/definitions/insert_command"},
                    },
                    {
                        "if": {
                            "required": ["command"],
                            "properties": {"command": {"const": "DIM_LINEAR"}},
                        },
                        "then": {"$ref": "#/definitions/dim_linear_command"},
                    },
                ],
            },
        },
    },
    "definitions": {
        "coordinate": _COORDINATE_SCHEMA,
        "common_optional": {
            "layer": _LAYER_PROPERTY,
            "comment": _COMMENT_PROPERTY,
        },
        "layer_command": {
            "type": "object",
            "additionalProperties": False,
            "required": ["command", "layer_name"],
            "properties": {
                "command": {"const": "LAYER"},
                "layer_name": _LAYER_PROPERTY,
                "color": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 255,
                },
                "linetype": {
                    "type": "string",
                    "minLength": 1,
                },
            },
        },
        "line_command": {
            "type": "object",
            "additionalProperties": False,
            "required": ["command", "from", "to"],
            "properties": {
                "command": {"const": "LINE"},
                "from": {"$ref": "#/definitions/coordinate"},
                "to": {"$ref": "#/definitions/coordinate"},
                "layer": _LAYER_PROPERTY,
                "comment": _COMMENT_PROPERTY,
            },
        },
        "circle_command": {
            "type": "object",
            "additionalProperties": False,
            "required": ["command", "center", "radius"],
            "properties": {
                "command": {"const": "CIRCLE"},
                "center": {"$ref": "#/definitions/coordinate"},
                "radius": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                },
                "layer": _LAYER_PROPERTY,
                "comment": _COMMENT_PROPERTY,
            },
        },
        "arc_command": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "command",
                "center",
                "radius",
                "start_angle_degrees",
                "end_angle_degrees",
            ],
            "properties": {
                "command": {"const": "ARC"},
                "center": {"$ref": "#/definitions/coordinate"},
                "radius": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                },
                "start_angle_degrees": {"type": "number"},
                "end_angle_degrees": {"type": "number"},
                "layer": _LAYER_PROPERTY,
                "comment": _COMMENT_PROPERTY,
            },
        },
        "ellipse_command": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "command",
                "center",
                "major_axis_endpoint",
                "ratio",
            ],
            "properties": {
                "command": {"const": "ELLIPSE"},
                "center": {"$ref": "#/definitions/coordinate"},
                "major_axis_endpoint": {"$ref": "#/definitions/coordinate"},
                "ratio": {
                    "type": "number",
                    "minimum": 0.01,
                    "maximum": 1.0,
                },
                "start_angle_degrees": {"type": "number"},
                "end_angle_degrees": {"type": "number"},
                "layer": _LAYER_PROPERTY,
                "comment": _COMMENT_PROPERTY,
            },
        },
        "polyline_command": {
            "type": "object",
            "additionalProperties": False,
            "required": ["command", "points"],
            "properties": {
                "command": {"const": "POLYLINE"},
                "points": {
                    "type": "array",
                    "items": {"$ref": "#/definitions/coordinate"},
                    "minItems": 2,
                },
                "closed": {"type": "boolean"},
                "layer": _LAYER_PROPERTY,
                "comment": _COMMENT_PROPERTY,
            },
        },
        "text_command": {
            "type": "object",
            "additionalProperties": False,
            "required": ["command", "text", "position"],
            "properties": {
                "command": {"const": "TEXT"},
                "text": {
                    "type": "string",
                    "minLength": 1,
                },
                "position": {"$ref": "#/definitions/coordinate"},
                "height": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                },
                "rotation_degrees": {"type": "number"},
                "layer": _LAYER_PROPERTY,
                "comment": _COMMENT_PROPERTY,
            },
        },
        "insert_command": {
            "type": "object",
            "additionalProperties": False,
            "required": ["command", "block_name", "position"],
            "properties": {
                "command": {"const": "INSERT"},
                "block_name": {
                    "type": "string",
                    "minLength": 1,
                },
                "position": {"$ref": "#/definitions/coordinate"},
                "scale": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                },
                "rotation_degrees": {"type": "number"},
                "layer": _LAYER_PROPERTY,
                "comment": _COMMENT_PROPERTY,
            },
        },
        "dim_linear_command": {
            "type": "object",
            "additionalProperties": False,
            "required": ["command", "from", "to", "dim_line_position"],
            "properties": {
                "command": {"const": "DIM_LINEAR"},
                "from": {"$ref": "#/definitions/coordinate"},
                "to": {"$ref": "#/definitions/coordinate"},
                "dim_line_position": {"$ref": "#/definitions/coordinate"},
                "text_override": {"type": "string"},
                "layer": _LAYER_PROPERTY,
                "comment": _COMMENT_PROPERTY,
            },
        },
    },
}


from .operation_schema import OPERATION_SCHEMA, OPERATION_VARIANTS, validate_operation

# Existing creation schemas remain unchanged. Structured modifications carry their
# own explicit path and are dispatched through modification_executor.
for _variant in OPERATION_VARIANTS:
    _name = _variant["properties"]["command"]["const"]
    _COMMAND_TYPES.append(_name)
    COMMAND_SCHEMA["properties"]["commands"]["items"]["allOf"].append({
        "if": {"properties": {"command": {"const": _name}}, "required": ["command"]},
        "then": _variant,
    })

_VALIDATOR = Draft7Validator(COMMAND_SCHEMA)


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


def validate_command_sequence(data: dict) -> list[str]:
    """Return readable validation errors for a command sequence."""
    errors = sorted(
        _VALIDATOR.iter_errors(data),
        key=lambda error: (
            [str(part) for part in error.absolute_path],
            error.message,
        ),
    )

    return [_format_error(error) for error in errors]


def is_valid_command_sequence(data: dict) -> bool:
    """Return True when the command sequence satisfies COMMAND_SCHEMA."""
    return not validate_command_sequence(data)

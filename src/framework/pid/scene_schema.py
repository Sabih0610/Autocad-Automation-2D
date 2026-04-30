"""Strict JSON schema for deterministic P&ID scenes."""

from __future__ import annotations

from typing import Any

from jsonschema import Draft7Validator


PID_SCENE_SCHEMA_VERSION = "1.0"


_POINT_SCHEMA = {
    "type": "array",
    "items": {"type": "number"},
    "minItems": 2,
    "maxItems": 2,
}


_POINTS_SCHEMA = {
    "type": "array",
    "items": _POINT_SCHEMA,
    "minItems": 2,
}


PID_SCENE_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "Deterministic P&ID Scene",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "title",
        "drawing_type",
        "assumptions",
        "equipment",
        "pipes",
        "valves",
        "instruments",
        "labels",
        "flow_arrows",
        "signal_lines",
    ],
    "properties": {
        "schema_version": {"const": PID_SCENE_SCHEMA_VERSION},
        "title": {"type": "string", "minLength": 1},
        "drawing_type": {"type": "string", "minLength": 1},
        "assumptions": {
            "type": "array",
            "items": {"type": "string"},
        },
        "equipment": {
            "type": "array",
            "items": {"$ref": "#/definitions/equipment"},
        },
        "pipes": {
            "type": "array",
            "items": {"$ref": "#/definitions/pipe"},
        },
        "valves": {
            "type": "array",
            "items": {"$ref": "#/definitions/valve"},
        },
        "instruments": {
            "type": "array",
            "items": {"$ref": "#/definitions/instrument"},
        },
        "labels": {
            "type": "array",
            "items": {"$ref": "#/definitions/label"},
        },
        "flow_arrows": {
            "type": "array",
            "items": {"$ref": "#/definitions/flow_arrow"},
        },
        "signal_lines": {
            "type": "array",
            "items": {"$ref": "#/definitions/signal_line"},
        },
    },
    "definitions": {
        "equipment": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "type", "tag", "center", "diameter"],
            "properties": {
                "id": {"type": "string", "minLength": 1},
                "type": {
                    "type": "string",
                    "enum": ["horizontal_vessel", "vertical_vessel"],
                },
                "tag": {"type": "string", "minLength": 1},
                "center": _POINT_SCHEMA,
                "length": {"type": "number", "exclusiveMinimum": 0},
                "diameter": {"type": "number", "exclusiveMinimum": 0},
                "height": {"type": "number", "exclusiveMinimum": 0},
            },
            "allOf": [
                {
                    "if": {"properties": {"type": {"const": "horizontal_vessel"}}},
                    "then": {"required": ["length"]},
                },
                {
                    "if": {"properties": {"type": {"const": "vertical_vessel"}}},
                    "then": {"required": ["height"]},
                },
            ],
        },
        "pipe": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "points"],
            "properties": {
                "id": {"type": "string", "minLength": 1},
                "points": _POINTS_SCHEMA,
                "label": {"type": "string", "minLength": 1},
            },
        },
        "valve": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "type", "center", "orientation"],
            "properties": {
                "id": {"type": "string", "minLength": 1},
                "type": {
                    "type": "string",
                    "enum": ["gate_valve", "control_valve"],
                },
                "center": _POINT_SCHEMA,
                "orientation": {"type": "string", "enum": ["H", "V"]},
                "size": {"type": "number", "exclusiveMinimum": 0},
            },
        },
        "instrument": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "tag", "center"],
            "properties": {
                "id": {"type": "string", "minLength": 1},
                "tag": {"type": "string", "minLength": 1},
                "center": _POINT_SCHEMA,
                "radius": {"type": "number", "exclusiveMinimum": 0},
                "signal_to": _POINTS_SCHEMA,
            },
        },
        "label": {
            "type": "object",
            "additionalProperties": False,
            "required": ["text", "position"],
            "properties": {
                "text": {"type": "string", "minLength": 1},
                "position": _POINT_SCHEMA,
                "height": {"type": "number", "exclusiveMinimum": 0},
            },
        },
        "flow_arrow": {
            "type": "object",
            "additionalProperties": False,
            "required": ["position", "direction"],
            "properties": {
                "position": _POINT_SCHEMA,
                "direction": {
                    "type": "string",
                    "enum": ["RIGHT", "LEFT", "UP", "DOWN"],
                },
                "size": {"type": "number", "exclusiveMinimum": 0},
            },
        },
        "signal_line": {
            "type": "object",
            "additionalProperties": False,
            "required": ["points"],
            "properties": {
                "points": _POINTS_SCHEMA,
            },
        },
    },
}


_VALIDATOR = Draft7Validator(PID_SCENE_SCHEMA)


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


def validate_pid_scene(data: dict) -> list[str]:
    """Return readable validation errors for a P&ID scene."""
    errors = sorted(
        _VALIDATOR.iter_errors(data),
        key=lambda error: (
            [str(part) for part in error.absolute_path],
            error.message,
        ),
    )

    return [_format_error(error) for error in errors]


def is_valid_pid_scene(data: dict) -> bool:
    """Return True when the P&ID scene satisfies PID_SCENE_SCHEMA."""
    return not validate_pid_scene(data)

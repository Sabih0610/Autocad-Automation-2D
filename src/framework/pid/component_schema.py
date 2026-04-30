"""JSON schema for component-based P&ID scenes."""

from __future__ import annotations

from typing import Any

from jsonschema import Draft7Validator


PID_COMPONENT_SCHEMA_VERSION = "1.0"


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


_STRING_SCHEMA = {
    "type": "string",
    "minLength": 1,
}


_POSITIVE_NUMBER_SCHEMA = {
    "type": "number",
    "exclusiveMinimum": 0,
}


_FLOW_DIRECTION_SCHEMA = {
    "enum": ["RIGHT", "LEFT", "UP", "DOWN"],
}


_ORIENTATION_SCHEMA = {
    "enum": ["H", "V"],
}


def _base_properties(component_type: str) -> dict[str, Any]:
    return {
        "component_type": {"const": component_type},
        "id": _STRING_SCHEMA,
        "tag": _STRING_SCHEMA,
        "center": _POINT_SCHEMA,
        "metadata": {"type": "object"},
    }


def _component_schema(
    component_type: str,
    required: list[str],
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged_properties = _base_properties(component_type)
    if properties:
        merged_properties.update(properties)

    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["component_type", "id", *required],
        "properties": merged_properties,
    }


PID_COMPONENT_SCENE_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "P&ID Component Scene",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "title",
        "drawing_type",
        "assumptions",
        "components",
    ],
    "properties": {
        "schema_version": {"const": PID_COMPONENT_SCHEMA_VERSION},
        "title": _STRING_SCHEMA,
        "drawing_type": _STRING_SCHEMA,
        "assumptions": {
            "type": "array",
            "items": {"type": "string"},
        },
        "metadata": {"type": "object"},
        "components": {
            "type": "array",
            "minItems": 1,
            "items": {
                "oneOf": [
                    _component_schema(
                        "horizontal_vessel",
                        required=["tag", "center", "length", "diameter"],
                        properties={
                            "length": _POSITIVE_NUMBER_SCHEMA,
                            "diameter": _POSITIVE_NUMBER_SCHEMA,
                        },
                    ),
                    _component_schema(
                        "vertical_vessel",
                        required=["tag", "center", "height", "diameter"],
                        properties={
                            "height": _POSITIVE_NUMBER_SCHEMA,
                            "diameter": _POSITIVE_NUMBER_SCHEMA,
                        },
                    ),
                    _component_schema(
                        "pipe_run",
                        required=["points"],
                        properties={
                            "points": _POINTS_SCHEMA,
                            "label": _STRING_SCHEMA,
                            "label_position": _POINT_SCHEMA,
                            "flow_direction": _FLOW_DIRECTION_SCHEMA,
                            "flow_arrow_position": _POINT_SCHEMA,
                        },
                    ),
                    _component_schema(
                        "signal_line",
                        required=["points"],
                        properties={
                            "points": _POINTS_SCHEMA,
                        },
                    ),
                    _component_schema(
                        "gate_valve",
                        required=["center", "orientation"],
                        properties={
                            "orientation": _ORIENTATION_SCHEMA,
                            "size": _POSITIVE_NUMBER_SCHEMA,
                        },
                    ),
                    _component_schema(
                        "control_valve",
                        required=["center", "orientation"],
                        properties={
                            "orientation": _ORIENTATION_SCHEMA,
                            "size": _POSITIVE_NUMBER_SCHEMA,
                        },
                    ),
                    _component_schema(
                        "instrument_bubble",
                        required=["tag", "center"],
                        properties={
                            "radius": _POSITIVE_NUMBER_SCHEMA,
                        },
                    ),
                    _component_schema(
                        "controller_loop",
                        required=[
                            "instrument_tag",
                            "controller_tag",
                            "instrument_center",
                            "controller_center",
                        ],
                        properties={
                            "instrument_tag": _STRING_SCHEMA,
                            "controller_tag": _STRING_SCHEMA,
                            "instrument_center": _POINT_SCHEMA,
                            "controller_center": _POINT_SCHEMA,
                            "signal_points": _POINTS_SCHEMA,
                            "radius": _POSITIVE_NUMBER_SCHEMA,
                        },
                    ),
                    _component_schema(
                        "label",
                        required=["text", "center"],
                        properties={
                            "text": _STRING_SCHEMA,
                            "height": _POSITIVE_NUMBER_SCHEMA,
                        },
                    ),
                    _component_schema(
                        "flow_arrow",
                        required=["center", "direction"],
                        properties={
                            "direction": _FLOW_DIRECTION_SCHEMA,
                            "size": _POSITIVE_NUMBER_SCHEMA,
                        },
                    ),
                    _component_schema(
                        "leader_line",
                        required=["points"],
                        properties={
                            "points": _POINTS_SCHEMA,
                            "text": _STRING_SCHEMA,
                            "text_position": _POINT_SCHEMA,
                        },
                    ),
                ],
            },
        },
    },
}


_VALIDATOR = Draft7Validator(PID_COMPONENT_SCENE_SCHEMA)


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


def validate_pid_component_scene_data(data: dict) -> list[str]:
    """Return readable validation errors for component-scene JSON."""
    errors = sorted(
        _VALIDATOR.iter_errors(data),
        key=lambda error: (
            [str(part) for part in error.absolute_path],
            error.message,
        ),
    )

    return [_format_error(error) for error in errors]


def is_valid_pid_component_scene_data(data: dict) -> bool:
    """Return True when component-scene JSON satisfies the schema."""
    return not validate_pid_component_scene_data(data)

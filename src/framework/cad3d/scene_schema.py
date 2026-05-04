"""JSON schema for deterministic 3D CAD scenes."""

from __future__ import annotations

from typing import Any

from jsonschema import Draft7Validator


CAD3D_SCENE_SCHEMA_VERSION = "1.0"


_STRING_SCHEMA = {
    "type": "string",
    "minLength": 1,
}


_POSITIVE_NUMBER_SCHEMA = {
    "type": "number",
    "exclusiveMinimum": 0,
}


_POINT3_SCHEMA = {
    "type": "array",
    "items": {"type": "number"},
    "minItems": 3,
    "maxItems": 3,
}


_POINTS3_SCHEMA = {
    "type": "array",
    "items": _POINT3_SCHEMA,
    "minItems": 2,
}


_AXIS_ORDER_SCHEMA = {
    "type": "array",
    "items": {"enum": ["X", "Y", "Z"]},
    "minItems": 1,
    "maxItems": 3,
}


def _base_properties(component_type: str) -> dict[str, Any]:
    return {
        "component_type": {"const": component_type},
        "id": _STRING_SCHEMA,
        "tag": _STRING_SCHEMA,
        "center": _POINT3_SCHEMA,
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


CAD3D_SCENE_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "CAD3D Scene",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "title",
        "units",
        "assumptions",
        "components",
    ],
    "properties": {
        "schema_version": {"const": CAD3D_SCENE_SCHEMA_VERSION},
        "title": _STRING_SCHEMA,
        "units": {"enum": ["mm"]},
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
                        "vertical_tank_3d",
                        required=["tag", "center", "diameter", "height"],
                        properties={
                            "diameter": _POSITIVE_NUMBER_SCHEMA,
                            "height": _POSITIVE_NUMBER_SCHEMA,
                            "color": {"type": "integer"},
                        },
                    ),
                    _component_schema(
                        "horizontal_vessel_3d",
                        required=["tag", "center", "diameter", "length", "orientation"],
                        properties={
                            "diameter": _POSITIVE_NUMBER_SCHEMA,
                            "length": _POSITIVE_NUMBER_SCHEMA,
                            "orientation": {"enum": ["X", "Y"]},
                        },
                    ),
                    _component_schema(
                        "heat_exchanger_3d",
                        required=["tag", "center", "length", "diameter", "orientation"],
                        properties={
                            "length": _POSITIVE_NUMBER_SCHEMA,
                            "diameter": _POSITIVE_NUMBER_SCHEMA,
                            "orientation": {"enum": ["X", "Y"]},
                        },
                    ),
                    _component_schema(
                        "pump_placeholder_3d",
                        required=["tag", "center", "length", "width", "height"],
                        properties={
                            "length": _POSITIVE_NUMBER_SCHEMA,
                            "width": _POSITIVE_NUMBER_SCHEMA,
                            "height": _POSITIVE_NUMBER_SCHEMA,
                        },
                    ),
                    _component_schema(
                        "valve_placeholder_3d",
                        required=["center", "length", "width", "height", "orientation"],
                        properties={
                            "length": _POSITIVE_NUMBER_SCHEMA,
                            "width": _POSITIVE_NUMBER_SCHEMA,
                            "height": _POSITIVE_NUMBER_SCHEMA,
                            "orientation": {"enum": ["X", "Y", "Z"]},
                            "valve_type": _STRING_SCHEMA,
                        },
                    ),
                    _component_schema(
                        "nozzle_3d",
                        required=["center", "diameter", "length", "orientation"],
                        properties={
                            "diameter": _POSITIVE_NUMBER_SCHEMA,
                            "length": _POSITIVE_NUMBER_SCHEMA,
                            "orientation": {"enum": ["X", "Y", "Z"]},
                        },
                    ),
                    _component_schema(
                        "flange_3d",
                        required=["center", "diameter", "thickness", "orientation"],
                        properties={
                            "diameter": _POSITIVE_NUMBER_SCHEMA,
                            "thickness": _POSITIVE_NUMBER_SCHEMA,
                            "orientation": {"enum": ["X", "Y", "Z"]},
                        },
                    ),
                    _component_schema(
                        "support_leg_3d",
                        required=["center", "diameter", "height"],
                        properties={
                            "diameter": _POSITIVE_NUMBER_SCHEMA,
                            "height": _POSITIVE_NUMBER_SCHEMA,
                        },
                    ),
                    _component_schema(
                        "saddle_support_3d",
                        required=["center", "length", "width", "height"],
                        properties={
                            "length": _POSITIVE_NUMBER_SCHEMA,
                            "width": _POSITIVE_NUMBER_SCHEMA,
                            "height": _POSITIVE_NUMBER_SCHEMA,
                        },
                    ),
                    _component_schema(
                        "pipe_support_3d",
                        required=["center", "height", "width", "depth"],
                        properties={
                            "height": _POSITIVE_NUMBER_SCHEMA,
                            "width": _POSITIVE_NUMBER_SCHEMA,
                            "depth": _POSITIVE_NUMBER_SCHEMA,
                        },
                    ),
                    _component_schema(
                        "pipe_run_3d",
                        required=["points", "diameter"],
                        properties={
                            "points": _POINTS3_SCHEMA,
                            "diameter": _POSITIVE_NUMBER_SCHEMA,
                            "visual_style": {"enum": ["centerline", "solid", "solid_with_centerline"]},
                            "draw_centerline": {"type": "boolean"},
                        },
                    ),
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "component_type",
                            "id",
                            "from_port",
                            "to_port",
                            "diameter",
                        ],
                        "properties": {
                            "component_type": {"const": "pipe_connection_3d"},
                            "id": _STRING_SCHEMA,
                            "from_port": _STRING_SCHEMA,
                            "to_port": _STRING_SCHEMA,
                            "diameter": _POSITIVE_NUMBER_SCHEMA,
                            "tag": _STRING_SCHEMA,
                            "routing_style": {"enum": ["direct", "orthogonal"]},
                            "clearance": _POSITIVE_NUMBER_SCHEMA,
                            "axis_order": _AXIS_ORDER_SCHEMA,
                            "metadata": {"type": "object"},
                        },
                    },
                    _component_schema(
                        "skid_base_3d",
                        required=["center", "length", "width", "height"],
                        properties={
                            "length": _POSITIVE_NUMBER_SCHEMA,
                            "width": _POSITIVE_NUMBER_SCHEMA,
                            "height": _POSITIVE_NUMBER_SCHEMA,
                        },
                    ),
                    _component_schema(
                        "box_3d",
                        required=["center", "length", "width", "height"],
                        properties={
                            "length": _POSITIVE_NUMBER_SCHEMA,
                            "width": _POSITIVE_NUMBER_SCHEMA,
                            "height": _POSITIVE_NUMBER_SCHEMA,
                        },
                    ),
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["component_type", "id", "text", "position", "height"],
                        "properties": {
                            "component_type": {"const": "label_3d"},
                            "id": _STRING_SCHEMA,
                            "text": _STRING_SCHEMA,
                            "position": _POINT3_SCHEMA,
                            "height": _POSITIVE_NUMBER_SCHEMA,
                            "metadata": {"type": "object"},
                        },
                    },
                ],
            },
        },
    },
}


_VALIDATOR = Draft7Validator(CAD3D_SCENE_SCHEMA)


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


def validate_cad3d_scene(data: dict) -> list[str]:
    """Return readable validation errors for a CAD3D scene."""
    errors = sorted(
        _VALIDATOR.iter_errors(data),
        key=lambda error: (
            [str(part) for part in error.absolute_path],
            error.message,
        ),
    )

    return [_format_error(error) for error in errors]


def is_valid_cad3d_scene(data: dict) -> bool:
    """Return True when a CAD3D scene satisfies the schema."""
    return not validate_cad3d_scene(data)

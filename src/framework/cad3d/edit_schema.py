"""Validation and normalization for CAD3D scene edit plans."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


CAD3D_EDIT_SCHEMA_VERSION = "1.0"


class CAD3DEditValidationError(Exception):
    """Raised when a CAD3D edit plan is invalid."""


_ALLOWED_UPDATE_FIELDS = {
    "center",
    "length",
    "width",
    "height",
    "diameter",
    "orientation",
    "tag",
    "metadata",
    "visual_style",
    "draw_centerline",
    "valve_type",
    "thickness",
    "points",
    "from_port",
    "to_port",
    "routing_style",
    "clearance",
    "axis_order",
}

_FORBIDDEN_UPDATE_FIELDS = {"id", "component_type"}


def is_valid_coord3(value) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return False
    try:
        [float(value[0]), float(value[1]), float(value[2])]
    except (TypeError, ValueError):
        return False
    return True


def _coord3(value: Any, field_name: str) -> list[float]:
    if not is_valid_coord3(value):
        raise CAD3DEditValidationError(f"{field_name} must be a 3-number coordinate")
    return [float(value[0]), float(value[1]), float(value[2])]


def _clean_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CAD3DEditValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _normalize_update_value(field_name: str, value: Any) -> Any:
    if field_name == "center":
        return _coord3(value, "updates.center")
    if field_name == "points":
        if not isinstance(value, list) or len(value) < 2:
            raise CAD3DEditValidationError("updates.points must contain at least two 3D points")
        return [_coord3(point, "updates.points[]") for point in value]
    if field_name in {"length", "width", "height", "diameter", "thickness", "clearance"}:
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise CAD3DEditValidationError(f"updates.{field_name} must be numeric") from exc
    if field_name == "axis_order":
        if not isinstance(value, list) or not value:
            raise CAD3DEditValidationError("updates.axis_order must be a non-empty list")
        return [str(axis).strip().upper() for axis in value]
    if field_name == "metadata":
        if not isinstance(value, dict):
            raise CAD3DEditValidationError("updates.metadata must be a dict")
        return deepcopy(value)
    return deepcopy(value)


def normalize_cad3d_edit_plan(plan: dict) -> dict:
    if not isinstance(plan, dict):
        raise CAD3DEditValidationError("CAD3D edit plan must be an object")

    normalized = deepcopy(plan)
    normalized["schema_version"] = str(normalized.get("schema_version", CAD3D_EDIT_SCHEMA_VERSION)).strip()
    normalized["edit_intent"] = _clean_string(normalized.get("edit_intent"), "edit_intent")
    normalized["summary"] = _clean_string(normalized.get("summary", normalized["edit_intent"]), "summary")

    metadata = normalized.get("metadata", {})
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise CAD3DEditValidationError("metadata must be a dict")
    normalized["metadata"] = metadata

    operations = normalized.get("operations")
    if not isinstance(operations, list) or not operations:
        raise CAD3DEditValidationError("operations must be a non-empty list")

    normalized_operations = []
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            raise CAD3DEditValidationError(f"operations[{index}] must be an object")

        clean_operation = deepcopy(operation)
        operation_type = _clean_string(clean_operation.get("operation_type"), f"operations[{index}].operation_type")
        clean_operation["operation_type"] = operation_type

        if "metadata" in clean_operation:
            if clean_operation["metadata"] is None:
                clean_operation["metadata"] = {}
            if not isinstance(clean_operation["metadata"], dict):
                raise CAD3DEditValidationError(f"operations[{index}].metadata must be a dict")

        if operation_type == "move_component":
            clean_operation["component_id"] = _clean_string(
                clean_operation.get("component_id"),
                f"operations[{index}].component_id",
            )
            has_delta = "delta" in clean_operation and clean_operation.get("delta") is not None
            has_new_center = "new_center" in clean_operation and clean_operation.get("new_center") is not None
            if not has_delta and not has_new_center:
                raise CAD3DEditValidationError(
                    f"operations[{index}] move_component requires delta or new_center"
                )
            if has_delta:
                clean_operation["delta"] = _coord3(clean_operation["delta"], f"operations[{index}].delta")
            if has_new_center:
                clean_operation["new_center"] = _coord3(
                    clean_operation["new_center"],
                    f"operations[{index}].new_center",
                )

        elif operation_type == "update_component":
            clean_operation["component_id"] = _clean_string(
                clean_operation.get("component_id"),
                f"operations[{index}].component_id",
            )
            updates = clean_operation.get("updates")
            if not isinstance(updates, dict) or not updates:
                raise CAD3DEditValidationError(f"operations[{index}].updates must be a non-empty dict")
            forbidden = sorted(_FORBIDDEN_UPDATE_FIELDS.intersection(updates))
            if forbidden:
                raise CAD3DEditValidationError(
                    f"operations[{index}].updates cannot modify: {', '.join(forbidden)}"
                )
            unknown = sorted(set(updates) - _ALLOWED_UPDATE_FIELDS)
            if unknown:
                raise CAD3DEditValidationError(
                    f"operations[{index}].updates contains unsupported fields: {', '.join(unknown)}"
                )
            clean_operation["updates"] = {
                field_name: _normalize_update_value(field_name, value)
                for field_name, value in updates.items()
            }

        elif operation_type == "add_component":
            component = clean_operation.get("component")
            if not isinstance(component, dict):
                raise CAD3DEditValidationError(f"operations[{index}].component must be a dict")
            clean_operation["component"] = deepcopy(component)

        elif operation_type == "delete_component":
            clean_operation["component_id"] = _clean_string(
                clean_operation.get("component_id"),
                f"operations[{index}].component_id",
            )

        else:
            raise CAD3DEditValidationError(f"Unsupported operation_type: {operation_type}")

        normalized_operations.append(clean_operation)

    normalized["operations"] = normalized_operations
    return normalized


def validate_cad3d_edit_plan(plan: dict) -> dict:
    normalized = normalize_cad3d_edit_plan(plan)
    if normalized["schema_version"] != CAD3D_EDIT_SCHEMA_VERSION:
        raise CAD3DEditValidationError(
            f"schema_version must be {CAD3D_EDIT_SCHEMA_VERSION!r}"
        )
    return normalized

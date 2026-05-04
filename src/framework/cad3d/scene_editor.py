"""Apply validated component-level edit plans to CAD3D scene JSON."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from src.framework.cad3d.edit_schema import (
    CAD3DEditValidationError,
    validate_cad3d_edit_plan,
)
from src.framework.cad3d.routing import CAD3DRoutingError, expand_pipe_connections
from src.framework.cad3d.scene_schema import validate_cad3d_scene


class CAD3DSceneEditError(Exception):
    """Raised when a CAD3D scene edit cannot be applied."""


class CAD3DComponentNotFoundError(CAD3DSceneEditError):
    """Raised when an edit references a missing CAD3D component id."""


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


def _validate_scene_or_raise(scene: dict, prefix: str = "Invalid CAD3D scene") -> None:
    errors = validate_cad3d_scene(scene)
    if errors:
        joined_errors = "\n".join(f"- {error}" for error in errors)
        raise CAD3DSceneEditError(f"{prefix}:\n{joined_errors}")


def _coord3(value: list[float], field_name: str = "coordinate") -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise CAD3DSceneEditError(f"{field_name} must be a 3-number coordinate")
    try:
        return [float(value[0]), float(value[1]), float(value[2])]
    except (TypeError, ValueError) as exc:
        raise CAD3DSceneEditError(f"{field_name} must contain numeric values") from exc


def _offset_point(point: list[float], delta: list[float]) -> list[float]:
    clean_point = _coord3(point, "point")
    clean_delta = _coord3(delta, "delta")
    return [clean_point[index] + clean_delta[index] for index in range(3)]


def find_component_index(scene: dict, component_id: str) -> int:
    for index, component in enumerate(scene.get("components", [])):
        if component.get("id") == component_id:
            return index
    raise CAD3DComponentNotFoundError(f"CAD3D component not found: {component_id}")


def get_component(scene: dict, component_id: str) -> dict:
    return scene["components"][find_component_index(scene, component_id)]


def list_component_ids(scene: dict) -> list[str]:
    return [
        component["id"]
        for component in scene.get("components", [])
        if component.get("id") is not None
    ]


def ensure_unique_component_ids(scene: dict) -> None:
    ids = list_component_ids(scene)
    duplicates = sorted({component_id for component_id in ids if ids.count(component_id) > 1})
    if duplicates:
        raise CAD3DSceneEditError(f"Duplicate CAD3D component id(s): {', '.join(duplicates)}")


def move_component(
    component: dict,
    delta: list[float] | None = None,
    new_center: list[float] | None = None,
) -> dict:
    edited = deepcopy(component)

    if new_center is not None:
        if "center" in edited:
            edited["center"] = _coord3(new_center, "new_center")
            return edited
        if "position" in edited:
            edited["position"] = _coord3(new_center, "new_center")
            return edited
        raise CAD3DSceneEditError(
            f"Component {edited.get('id')} has no center/position field for new_center"
        )

    if delta is None:
        raise CAD3DSceneEditError("move_component requires delta or new_center")

    clean_delta = _coord3(delta, "delta")
    if "center" in edited:
        edited["center"] = _offset_point(edited["center"], clean_delta)
        return edited
    if "position" in edited:
        edited["position"] = _offset_point(edited["position"], clean_delta)
        return edited
    if "points" in edited:
        edited["points"] = [_offset_point(point, clean_delta) for point in edited["points"]]
        return edited

    raise CAD3DSceneEditError(
        f"Component {edited.get('id')} has no center, position, or points to move"
    )


def update_component_fields(component: dict, updates: dict) -> dict:
    if not isinstance(updates, dict) or not updates:
        raise CAD3DSceneEditError("updates must be a non-empty dict")
    if "id" in updates or "component_type" in updates:
        raise CAD3DSceneEditError("updates cannot modify id or component_type")
    unsupported = sorted(set(updates) - _ALLOWED_UPDATE_FIELDS)
    if unsupported:
        raise CAD3DSceneEditError(f"Unsupported update field(s): {', '.join(unsupported)}")

    edited = deepcopy(component)
    for field_name, value in updates.items():
        edited[field_name] = deepcopy(value)
    return edited


def add_component_to_scene(scene: dict, component: dict) -> dict:
    if not isinstance(component, dict) or not component.get("id"):
        raise CAD3DSceneEditError("component must be a dict with a non-empty id")
    edited_scene = deepcopy(scene)
    if component["id"] in list_component_ids(edited_scene):
        raise CAD3DSceneEditError(f"Duplicate CAD3D component id: {component['id']}")
    edited_scene["components"].append(deepcopy(component))
    ensure_unique_component_ids(edited_scene)
    _validate_scene_or_raise(edited_scene, "Invalid CAD3D scene after add_component")
    return edited_scene


def _references_component(reference: Any, component_id: str) -> bool:
    return isinstance(reference, str) and reference.startswith(f"{component_id}.")


def delete_component_from_scene(
    scene: dict,
    component_id: str,
    remove_connected_pipes: bool = True,
) -> dict:
    edited_scene = deepcopy(scene)
    find_component_index(edited_scene, component_id)
    remaining_components = []

    for component in edited_scene.get("components", []):
        if component.get("id") == component_id:
            continue
        if remove_connected_pipes:
            if component.get("component_type") == "pipe_connection_3d" and (
                _references_component(component.get("from_port"), component_id)
                or _references_component(component.get("to_port"), component_id)
            ):
                continue
            if component.get("component_type") == "pipe_run_3d":
                metadata = component.get("metadata") or {}
                if (
                    _references_component(metadata.get("from_port"), component_id)
                    or _references_component(metadata.get("to_port"), component_id)
                ):
                    continue
        remaining_components.append(component)

    edited_scene["components"] = remaining_components
    return edited_scene


def apply_cad3d_edit_plan(scene: dict, edit_plan: dict) -> dict:
    source_scene = deepcopy(scene)
    _validate_scene_or_raise(source_scene)
    ensure_unique_component_ids(source_scene)

    try:
        plan = validate_cad3d_edit_plan(edit_plan)
    except CAD3DEditValidationError as exc:
        raise CAD3DSceneEditError(str(exc)) from exc

    edited_scene = deepcopy(source_scene)
    for operation in plan["operations"]:
        operation_type = operation["operation_type"]

        if operation_type == "move_component":
            index = find_component_index(edited_scene, operation["component_id"])
            edited_scene["components"][index] = move_component(
                edited_scene["components"][index],
                delta=operation.get("delta"),
                new_center=operation.get("new_center"),
            )

        elif operation_type == "update_component":
            index = find_component_index(edited_scene, operation["component_id"])
            edited_scene["components"][index] = update_component_fields(
                edited_scene["components"][index],
                operation["updates"],
            )

        elif operation_type == "add_component":
            edited_scene = add_component_to_scene(edited_scene, operation["component"])

        elif operation_type == "delete_component":
            edited_scene = delete_component_from_scene(edited_scene, operation["component_id"])

        else:
            raise CAD3DSceneEditError(f"Unsupported operation_type: {operation_type}")

    ensure_unique_component_ids(edited_scene)
    metadata = dict(edited_scene.get("metadata") or {})
    original_metadata = source_scene.get("metadata") or {}
    metadata["last_edit_intent"] = plan["edit_intent"]
    metadata["last_edit_summary"] = plan["summary"]
    metadata["last_edit_operation_count"] = len(plan["operations"])
    metadata["edited_from"] = (
        original_metadata.get("scene_token")
        or original_metadata.get("token")
        or original_metadata.get("template_name")
        or original_metadata.get("example_name")
        or deepcopy(original_metadata)
    )
    edited_scene["metadata"] = metadata

    _validate_scene_or_raise(edited_scene, "Invalid CAD3D scene after edit")
    try:
        expand_pipe_connections(edited_scene)
    except CAD3DRoutingError as exc:
        raise CAD3DSceneEditError(f"Edited CAD3D scene has invalid pipe routing: {exc}") from exc

    return edited_scene


def summarize_scene_edit(original_scene: dict, edited_scene: dict) -> dict:
    original_ids = set(list_component_ids(original_scene))
    edited_ids = set(list_component_ids(edited_scene))
    component_types = sorted(
        {
            component.get("component_type")
            for component in edited_scene.get("components", [])
            if component.get("component_type")
        }
    )
    return {
        "original_component_count": len(original_scene.get("components", [])),
        "edited_component_count": len(edited_scene.get("components", [])),
        "added_component_ids": sorted(edited_ids - original_ids),
        "removed_component_ids": sorted(original_ids - edited_ids),
        "unchanged_component_ids": sorted(original_ids & edited_ids),
        "component_types": component_types,
    }

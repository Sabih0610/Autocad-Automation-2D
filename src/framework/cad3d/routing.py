"""Deterministic port-based routing helpers for CAD3D pipe connections."""

from __future__ import annotations

from copy import deepcopy
from math import sqrt
from typing import Any

from src.framework.cad3d.scene_schema import validate_cad3d_scene


class CAD3DRoutingError(Exception):
    """Raised when a CAD3D logical routing operation fails."""


class CAD3DPortResolutionError(CAD3DRoutingError):
    """Raised when a CAD3D component port reference cannot be resolved."""


_AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}
_DEFAULT_AXIS_ORDER = ["X", "Y", "Z"]


def _point3(value: Any, field_name: str = "point") -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise CAD3DPortResolutionError(f"{field_name} must be a 3D point [x, y, z]")

    try:
        return [float(value[0]), float(value[1]), float(value[2])]
    except (TypeError, ValueError) as exc:
        raise CAD3DPortResolutionError(f"{field_name} must contain numeric values") from exc


def _vector3(value: Any, field_name: str = "direction") -> list[float]:
    vector = _point3(value, field_name)
    if vector == [0.0, 0.0, 0.0]:
        raise CAD3DPortResolutionError(f"{field_name} must not be a zero vector")
    return vector


def _unit_vector_between(start: list[float], end: list[float], fallback: list[float]) -> list[float]:
    vector = [end[index] - start[index] for index in range(3)]
    magnitude = sqrt(sum(value * value for value in vector))
    if magnitude <= 0:
        return fallback
    return [value / magnitude for value in vector]


def _field_float(component: dict, field_name: str) -> float:
    try:
        return float(component[field_name])
    except KeyError as exc:
        raise CAD3DPortResolutionError(
            f"{component.get('component_type', 'component')} {component.get('id', '<missing id>')} "
            f"is missing required field {field_name!r}"
        ) from exc
    except (TypeError, ValueError) as exc:
        raise CAD3DPortResolutionError(
            f"{component.get('component_type', 'component')} {component.get('id', '<missing id>')} "
            f"field {field_name!r} must be numeric"
        ) from exc


def _positive_float(value: Any, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise CAD3DRoutingError(f"{field_name} must be numeric") from exc

    if number <= 0:
        raise CAD3DRoutingError(f"{field_name} must be positive")
    return number


def _center(component: dict) -> list[float]:
    if "center" not in component:
        raise CAD3DPortResolutionError(
            f"{component.get('component_type', 'component')} {component.get('id', '<missing id>')} "
            "is missing required field 'center'"
        )
    return _point3(component["center"], "center")


def _orientation(component: dict, allowed: set[str]) -> str:
    orientation = str(component.get("orientation", "")).strip().upper()
    if orientation not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise CAD3DPortResolutionError(
            f"{component.get('component_type', 'component')} {component.get('id', '<missing id>')} "
            f"has unsupported orientation {orientation!r}; expected one of {allowed_text}"
        )
    return orientation


def _make_port(
    position: list[float],
    direction: list[float],
    diameter: float | None = None,
    port_type: str | None = None,
) -> dict[str, Any]:
    port: dict[str, Any] = {
        "position": _point3(position, "position"),
        "direction": _vector3(direction, "direction"),
    }
    if diameter is not None:
        port["diameter"] = _positive_float(diameter, "port diameter")
    if port_type is not None:
        port["type"] = str(port_type)
    return port


def _add_aliases(ports: dict[str, dict], aliases: dict[str, str]) -> dict[str, dict]:
    for alias, canonical in aliases.items():
        if canonical in ports:
            ports[alias] = dict(ports[canonical])
    return ports


def _axis_points(
    center: list[float],
    length: float,
    orientation: str,
) -> tuple[list[float], list[float], list[float], list[float]]:
    cx, cy, cz = center
    half_length = length / 2.0

    if orientation == "X":
        return (
            [cx - half_length, cy, cz],
            [cx + half_length, cy, cz],
            [-1, 0, 0],
            [1, 0, 0],
        )
    if orientation == "Y":
        return (
            [cx, cy - half_length, cz],
            [cx, cy + half_length, cz],
            [0, -1, 0],
            [0, 1, 0],
        )
    return (
        [cx, cy, cz - half_length],
        [cx, cy, cz + half_length],
        [0, 0, -1],
        [0, 0, 1],
    )


def normalize_port_reference(reference: str) -> tuple[str, str]:
    """Parse a COMPONENT_ID.PORT_NAME reference."""
    if not isinstance(reference, str):
        raise CAD3DPortResolutionError("Port reference must be a string")

    clean_reference = reference.strip()
    if not clean_reference or clean_reference.count(".") != 1:
        raise CAD3DPortResolutionError(
            f"Invalid port reference {reference!r}; expected COMPONENT_ID.PORT_NAME"
        )

    component_id, port_name = [part.strip() for part in clean_reference.split(".", 1)]
    if not component_id or not port_name:
        raise CAD3DPortResolutionError(
            f"Invalid port reference {reference!r}; component id and port name are required"
        )

    return component_id, port_name


def get_component_by_id(scene: dict, component_id: str) -> dict:
    """Return a scene component by id."""
    for component in scene.get("components", []):
        if component.get("id") == component_id:
            return component

    raise CAD3DPortResolutionError(f"Component {component_id!r} was not found in the CAD3D scene")


def component_ports(component: dict) -> dict[str, dict]:
    """Return calculated ports for a raw CAD3D scene component dictionary."""
    component_type = component.get("component_type")

    if component_type == "vertical_tank_3d":
        cx, cy, cz = _center(component)
        diameter = _field_float(component, "diameter")
        height = _field_float(component, "height")
        radius = diameter / 2.0
        ports = {
            "top": _make_port([cx, cy, cz + height / 2.0], [0, 0, 1], diameter * 0.15, "nozzle"),
            "bottom": _make_port([cx, cy, cz - height / 2.0], [0, 0, -1], diameter * 0.15, "nozzle"),
            "side_left": _make_port([cx - radius, cy, cz], [-1, 0, 0], diameter * 0.12, "nozzle"),
            "side_right": _make_port([cx + radius, cy, cz], [1, 0, 0], diameter * 0.12, "nozzle"),
            "side_front": _make_port([cx, cy - radius, cz], [0, -1, 0], diameter * 0.12, "nozzle"),
            "side_back": _make_port([cx, cy + radius, cz], [0, 1, 0], diameter * 0.12, "nozzle"),
        }
        return _add_aliases(
            ports,
            {
                "inlet": "side_left",
                "outlet": "side_right",
                "drain": "bottom",
                "vent": "top",
            },
        )

    if component_type == "horizontal_vessel_3d":
        cx, cy, cz = _center(component)
        diameter = _field_float(component, "diameter")
        length = _field_float(component, "length")
        orientation = _orientation(component, {"X", "Y"})
        end_a, end_b, dir_a, dir_b = _axis_points([cx, cy, cz], length, orientation)
        ports = {
            "end_a": _make_port(end_a, dir_a, diameter * 0.15, "nozzle"),
            "end_b": _make_port(end_b, dir_b, diameter * 0.15, "nozzle"),
            "top": _make_port([cx, cy, cz + diameter / 2.0], [0, 0, 1], diameter * 0.12, "nozzle"),
            "bottom": _make_port([cx, cy, cz - diameter / 2.0], [0, 0, -1], diameter * 0.12, "nozzle"),
        }
        return _add_aliases(
            ports,
            {
                "inlet": "end_a",
                "outlet": "end_b",
                "drain": "bottom",
                "vent": "top",
            },
        )

    if component_type == "heat_exchanger_3d":
        center = _center(component)
        diameter = _field_float(component, "diameter")
        length = _field_float(component, "length")
        orientation = _orientation(component, {"X", "Y"})
        inlet, outlet, inlet_direction, outlet_direction = _axis_points(center, length, orientation)
        ports = {
            "inlet": _make_port(inlet, inlet_direction, diameter * 0.25, "nozzle"),
            "outlet": _make_port(outlet, outlet_direction, diameter * 0.25, "nozzle"),
        }
        return _add_aliases(ports, {"end_a": "inlet", "end_b": "outlet"})

    if component_type == "pump_placeholder_3d":
        cx, cy, cz = _center(component)
        length = _field_float(component, "length")
        width = _field_float(component, "width")
        ports = {
            "suction": _make_port([cx - length / 2.0, cy, cz], [-1, 0, 0], width * 0.25, "nozzle"),
            "discharge": _make_port([cx + length / 2.0, cy, cz], [1, 0, 0], width * 0.25, "nozzle"),
        }
        return _add_aliases(ports, {"inlet": "suction", "outlet": "discharge"})

    if component_type == "valve_placeholder_3d":
        center = _center(component)
        length = _field_float(component, "length")
        width = _field_float(component, "width")
        height = _field_float(component, "height")
        orientation = _orientation(component, {"X", "Y", "Z"})
        inlet, outlet, inlet_direction, outlet_direction = _axis_points(center, length, orientation)
        port_diameter = min(width, height) * 0.5
        return {
            "inlet": _make_port(inlet, inlet_direction, port_diameter, "valve_end"),
            "outlet": _make_port(outlet, outlet_direction, port_diameter, "valve_end"),
        }

    if component_type == "nozzle_3d":
        center = _center(component)
        diameter = _field_float(component, "diameter")
        length = _field_float(component, "length")
        orientation = _orientation(component, {"X", "Y", "Z"})
        base, tip, base_direction, tip_direction = _axis_points(center, length, orientation)
        ports = {
            "base": _make_port(base, base_direction, diameter, "nozzle_base"),
            "tip": _make_port(tip, tip_direction, diameter, "nozzle_tip"),
        }
        return _add_aliases(ports, {"inlet": "base", "outlet": "tip"})

    if component_type == "flange_3d":
        center = _center(component)
        diameter = _field_float(component, "diameter")
        thickness = _field_float(component, "thickness")
        orientation = _orientation(component, {"X", "Y", "Z"})
        face_a, face_b, dir_a, dir_b = _axis_points(center, thickness, orientation)
        ports = {
            "face_a": _make_port(face_a, dir_a, diameter, "flange_face"),
            "face_b": _make_port(face_b, dir_b, diameter, "flange_face"),
        }
        return _add_aliases(ports, {"inlet": "face_a", "outlet": "face_b"})

    if component_type == "pipe_run_3d":
        points = [_point3(point, "pipe_run_3d point") for point in component.get("points", [])]
        if len(points) < 2:
            raise CAD3DPortResolutionError(
                f"pipe_run_3d {component.get('id', '<missing id>')} requires at least two points"
            )
        diameter = _field_float(component, "diameter")
        return {
            "start": _make_port(
                points[0],
                _unit_vector_between(points[1], points[0], [-1, 0, 0]),
                diameter,
                "pipe_end",
            ),
            "end": _make_port(
                points[-1],
                _unit_vector_between(points[-2], points[-1], [1, 0, 0]),
                diameter,
                "pipe_end",
            ),
        }

    if component_type == "support_leg_3d":
        cx, cy, cz = _center(component)
        diameter = _field_float(component, "diameter")
        height = _field_float(component, "height")
        return {
            "top": _make_port([cx, cy, cz + height / 2.0], [0, 0, 1], diameter, "support_top"),
            "bottom": _make_port([cx, cy, cz - height / 2.0], [0, 0, -1], diameter, "support_bottom"),
        }

    if component_type == "pipe_support_3d":
        cx, cy, cz = _center(component)
        height = _field_float(component, "height")
        width = _field_float(component, "width")
        return {
            "top": _make_port([cx, cy, cz + height / 2.0], [0, 0, 1], width, "pipe_support_top"),
        }

    return {}


def build_port_index(scene: dict) -> dict[str, dict]:
    """Build a flat COMPONENT_ID.PORT_NAME index for a CAD3D scene."""
    ports: dict[str, dict] = {}
    for component in scene.get("components", []):
        component_id = component.get("id")
        if not component_id:
            continue
        for port_name, port in component_ports(component).items():
            ports[f"{component_id}.{port_name}"] = port
    return ports


def resolve_port_reference(scene: dict, reference: str) -> dict:
    """Resolve a COMPONENT_ID.PORT_NAME reference to its calculated port."""
    component_id, port_name = normalize_port_reference(reference)
    component = get_component_by_id(scene, component_id)
    ports = component_ports(component)

    try:
        return ports[port_name]
    except KeyError as exc:
        available = ", ".join(sorted(ports)) or "none"
        raise CAD3DPortResolutionError(
            f"Component {component_id!r} does not expose port {port_name!r}. "
            f"Available ports: {available}"
        ) from exc


def dedupe_consecutive_points(points: list[list[float]]) -> list[list[float]]:
    """Remove consecutive duplicate 3D points after numeric normalization."""
    deduped: list[list[float]] = []
    for point in points:
        normalized = _point3(point)
        if not deduped or normalized != deduped[-1]:
            deduped.append(normalized)
    return deduped


def _normalize_axis_order(axis_order: list[str] | None) -> list[str]:
    if axis_order is None:
        return list(_DEFAULT_AXIS_ORDER)

    if not isinstance(axis_order, list) or not axis_order:
        raise CAD3DRoutingError("axis_order must contain 1 to 3 axis strings when provided")

    normalized: list[str] = []
    for axis in axis_order:
        clean_axis = str(axis).strip().upper()
        if clean_axis not in _AXIS_INDEX:
            raise CAD3DRoutingError(f"Unsupported routing axis {axis!r}; expected X, Y, or Z")
        if clean_axis not in normalized:
            normalized.append(clean_axis)

    if len(normalized) > 3:
        raise CAD3DRoutingError("axis_order cannot contain more than 3 axes")

    for axis in _DEFAULT_AXIS_ORDER:
        if axis not in normalized:
            normalized.append(axis)

    return normalized


def orthogonal_pipe_route_3d(
    from_port: dict,
    to_port: dict,
    clearance: float = 500.0,
    axis_order: list[str] | None = None,
) -> list[list[float]]:
    """Build a deterministic orthogonal pipe centerline route between two ports."""
    clean_clearance = _positive_float(clearance, "clearance")
    start = _point3(from_port.get("position"), "from_port position")
    end = _point3(to_port.get("position"), "to_port position")
    from_direction = _vector3(from_port.get("direction"), "from_port direction")
    to_direction = _vector3(to_port.get("direction"), "to_port direction")

    first_offset = [
        start[index] + from_direction[index] * clean_clearance
        for index in range(3)
    ]
    last_offset = [
        end[index] + to_direction[index] * clean_clearance
        for index in range(3)
    ]

    points = [start, first_offset]
    current = list(first_offset)
    for axis in _normalize_axis_order(axis_order):
        axis_index = _AXIS_INDEX[axis]
        current = list(current)
        current[axis_index] = last_offset[axis_index]
        points.append(current)

    points.extend([last_offset, end])
    deduped = dedupe_consecutive_points(points)
    if len(deduped) < 2:
        return [start, end]
    return deduped


def direct_pipe_route_3d(from_port: dict, to_port: dict) -> list[list[float]]:
    """Build a direct two-point pipe centerline route between two ports."""
    return [
        _point3(from_port.get("position"), "from_port position"),
        _point3(to_port.get("position"), "to_port position"),
    ]


def build_pipe_run_from_connection(connection: dict, scene: dict) -> dict:
    """Expand a logical pipe_connection_3d component into a pipe_run_3d component."""
    if connection.get("component_type") != "pipe_connection_3d":
        raise CAD3DRoutingError("build_pipe_run_from_connection requires pipe_connection_3d")

    from_reference = connection.get("from_port")
    to_reference = connection.get("to_port")
    from_port = resolve_port_reference(scene, from_reference)
    to_port = resolve_port_reference(scene, to_reference)
    diameter = _positive_float(connection.get("diameter"), "diameter")
    routing_style = str(connection.get("routing_style") or "orthogonal").strip().lower()
    clearance = _positive_float(connection.get("clearance", 500.0), "clearance")
    axis_order = connection.get("axis_order")

    if routing_style == "direct":
        points = direct_pipe_route_3d(from_port, to_port)
    elif routing_style == "orthogonal":
        points = orthogonal_pipe_route_3d(
            from_port,
            to_port,
            clearance=clearance,
            axis_order=axis_order,
        )
    else:
        raise CAD3DRoutingError(f"Unsupported pipe routing_style: {routing_style}")

    metadata = dict(connection.get("metadata") or {})
    metadata.update(
        {
            "generated_from": "pipe_connection_3d",
            "from_port": from_reference,
            "to_port": to_reference,
            "routing_style": routing_style,
            "clearance": clearance,
        }
    )

    pipe_run = {
        "component_type": "pipe_run_3d",
        "id": connection["id"],
        "points": points,
        "diameter": diameter,
        "metadata": metadata,
    }
    if connection.get("tag") is not None:
        pipe_run["tag"] = connection["tag"]
    return pipe_run


def count_pipe_connections(scene: dict) -> int:
    """Count logical pipe connection components in a CAD3D scene."""
    return sum(
        1
        for component in scene.get("components", [])
        if component.get("component_type") == "pipe_connection_3d"
    )


def expand_pipe_connections(scene: dict) -> dict:
    """Replace logical pipe_connection_3d components with executable pipe_run_3d components."""
    input_errors = validate_cad3d_scene(scene)
    if input_errors:
        joined_errors = "\n".join(f"- {error}" for error in input_errors)
        raise CAD3DRoutingError(f"Invalid CAD3D scene before pipe routing:\n{joined_errors}")

    source_scene = deepcopy(scene)
    expanded_scene = deepcopy(scene)
    expanded_components: list[dict] = []
    expanded_count = 0

    for component in source_scene.get("components", []):
        if component.get("component_type") == "pipe_connection_3d":
            expanded_components.append(build_pipe_run_from_connection(component, source_scene))
            expanded_count += 1
        else:
            expanded_components.append(deepcopy(component))

    expanded_scene["components"] = expanded_components
    metadata = dict(expanded_scene.get("metadata") or {})
    metadata["pipe_connections_expanded"] = expanded_count
    metadata["routing_engine"] = "cad3d_port_router_v1"
    expanded_scene["metadata"] = metadata

    validation_errors = validate_cad3d_scene(expanded_scene)
    if validation_errors:
        joined_errors = "\n".join(f"- {error}" for error in validation_errors)
        raise CAD3DRoutingError(f"Expanded CAD3D scene failed validation:\n{joined_errors}")

    return expanded_scene

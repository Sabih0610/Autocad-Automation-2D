"""Base model for reusable 3D CAD components."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


Point3D = list[float]
Port3D = dict[str, Any]
PortMap3D = dict[str, Port3D]


def normalize_point3(point: list[float] | tuple[float, ...]) -> Point3D:
    """Normalize a 2D/3D point to a three-number coordinate."""
    if not isinstance(point, (list, tuple)) or len(point) not in {2, 3}:
        raise ValueError("point must be a 2D or 3D coordinate")

    try:
        x = float(point[0])
        y = float(point[1])
        z = float(point[2]) if len(point) == 3 else 0.0
    except (TypeError, ValueError) as exc:
        raise ValueError("point coordinates must be numeric") from exc

    return [x, y, z]


def normalize_vector3(vector: list[float] | tuple[float, ...]) -> Point3D:
    """Normalize a non-zero three-number vector."""
    if not isinstance(vector, (list, tuple)) or len(vector) != 3:
        raise ValueError("vector must be a 3D coordinate")

    try:
        normalized = [float(vector[0]), float(vector[1]), float(vector[2])]
    except (TypeError, ValueError) as exc:
        raise ValueError("vector coordinates must be numeric") from exc

    if normalized == [0.0, 0.0, 0.0]:
        raise ValueError("vector must not be zero")

    return normalized


def offset_point3(point: Point3D, dx: float = 0, dy: float = 0, dz: float = 0) -> Point3D:
    x, y, z = normalize_point3(point)
    return [x + float(dx), y + float(dy), z + float(dz)]


def make_port3(
    position: Point3D,
    direction: Point3D,
    diameter: float | None = None,
    port_type: str | None = None,
) -> Port3D:
    port: Port3D = {
        "position": normalize_point3(position),
        "direction": normalize_vector3(direction),
    }

    if diameter is not None:
        if float(diameter) <= 0:
            raise ValueError("port diameter must be positive")
        port["diameter"] = float(diameter)

    if port_type is not None:
        if not isinstance(port_type, str) or not port_type.strip():
            raise ValueError("port_type must be non-empty when provided")
        port["type"] = port_type.strip()

    return port


class CAD3DComponent(Protocol):
    id: str
    tag: str | None

    def ports(self) -> PortMap3D:
        ...

    def to_scene_component(self) -> dict:
        ...

    def summary(self) -> str:
        ...


@dataclass
class BaseCAD3DComponent:
    id: str
    tag: str | None = None
    center: Point3D = field(default_factory=lambda: [0.0, 0.0, 0.0])
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("component id must be non-empty")
        self.id = self.id.strip()

        if self.tag is not None:
            if not isinstance(self.tag, str) or not self.tag.strip():
                raise ValueError("component tag must be non-empty when provided")
            self.tag = self.tag.strip()

        self.center = normalize_point3(self.center)

        if not isinstance(self.metadata, dict):
            raise ValueError("metadata must be a dict")

    def ports(self) -> PortMap3D:
        return {}

    def to_scene_component(self) -> dict:
        raise NotImplementedError

    def summary(self) -> str:
        return f"{self.__class__.__name__}(id={self.id}, tag={self.tag})"


@dataclass
class RenderedCAD3DComponent:
    component_id: str
    component_type: str
    scene_component: dict
    ports: PortMap3D
    summary: str


def render_cad3d_component(component: CAD3DComponent) -> RenderedCAD3DComponent:
    scene_component = component.to_scene_component()
    ports = component.ports()

    return RenderedCAD3DComponent(
        component_id=component.id,
        component_type=scene_component.get("component_type", component.__class__.__name__),
        scene_component=scene_component,
        ports=ports,
        summary=component.summary(),
    )

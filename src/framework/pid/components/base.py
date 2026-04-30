"""Base model for reusable P&ID components."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


Point = list[float]
PortMap = dict[str, Point]


def normalize_point(point: list[float] | tuple[float, ...]) -> Point:
    """Normalize a 2D/3D point to a two-number coordinate."""
    if not isinstance(point, (list, tuple)) or len(point) not in {2, 3}:
        raise ValueError("point must be a 2D or 3D coordinate")

    try:
        return [float(point[0]), float(point[1])]
    except (TypeError, ValueError) as exc:
        raise ValueError("point coordinates must be numeric") from exc


def offset_point(point: Point, dx: float = 0, dy: float = 0) -> Point:
    x, y = normalize_point(point)
    return [x + float(dx), y + float(dy)]


def component_text_id(prefix: str, index: int) -> str:
    if not isinstance(prefix, str) or not prefix.strip():
        raise ValueError("prefix must be non-empty")
    if int(index) < 1:
        raise ValueError("index must be at least 1")
    return f"{prefix.strip()}-{int(index):03d}"


class PIDComponent(Protocol):
    id: str
    tag: str | None

    def ports(self) -> PortMap:
        ...

    def render(self) -> list[dict]:
        ...

    def summary(self) -> str:
        ...


@dataclass
class BasePIDComponent:
    id: str
    tag: str | None = None
    center: Point = field(default_factory=lambda: [0.0, 0.0])
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("component id must be non-empty")
        self.id = self.id.strip()

        if self.tag is not None:
            if not isinstance(self.tag, str) or not self.tag.strip():
                raise ValueError("component tag must be non-empty when provided")
            self.tag = self.tag.strip()

        self.center = normalize_point(self.center)

        if not isinstance(self.metadata, dict):
            raise ValueError("metadata must be a dict")

    def ports(self) -> PortMap:
        return {}

    def render(self) -> list[dict]:
        raise NotImplementedError

    def summary(self) -> str:
        return f"{self.__class__.__name__}(id={self.id}, tag={self.tag})"


@dataclass
class RenderedComponent:
    component_id: str
    component_type: str
    commands: list[dict]
    ports: PortMap
    summary: str


def render_component(component: PIDComponent) -> RenderedComponent:
    commands = component.render()
    ports = {
        name: normalize_point(point)
        for name, point in component.ports().items()
    }

    return RenderedComponent(
        component_id=component.id,
        component_type=component.__class__.__name__,
        commands=commands,
        ports=ports,
        summary=component.summary(),
    )

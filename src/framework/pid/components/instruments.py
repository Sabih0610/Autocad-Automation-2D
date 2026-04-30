"""Reusable P&ID instrument components."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.framework.pid.components.base import BasePIDComponent, Point, PortMap, normalize_point
from src.framework.pid.symbols import PID_INSTRUMENT_RADIUS, instrument_bubble_commands, signal_line_commands


def _validate_positive(value: float, name: str) -> None:
    if float(value) <= 0:
        raise ValueError(f"{name} must be positive")


def _validate_tag(tag: str, name: str) -> str:
    if not isinstance(tag, str) or not tag.strip():
        raise ValueError(f"{name} must be non-empty")
    return tag.strip()


@dataclass
class InstrumentBubbleComponent(BasePIDComponent):
    radius: float = PID_INSTRUMENT_RADIUS

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.tag is None:
            raise ValueError("tag must be non-empty")
        _validate_positive(self.radius, "radius")
        self.radius = float(self.radius)

    def ports(self) -> PortMap:
        cx, cy = self.center
        return {
            "center": [cx, cy],
            "bottom": [cx, cy - self.radius],
            "top": [cx, cy + self.radius],
            "left": [cx - self.radius, cy],
            "right": [cx + self.radius, cy],
        }

    def render(self) -> list[dict]:
        return instrument_bubble_commands(
            center=self.center,
            tag=self.tag or "",
            radius=self.radius,
        )


@dataclass
class ControllerLoopComponent(BasePIDComponent):
    instrument_tag: str = ""
    controller_tag: str = ""
    instrument_center: Point = field(default_factory=lambda: [0.0, 0.0])
    controller_center: Point = field(default_factory=lambda: [250.0, 0.0])
    signal_points: list[Point] | None = None
    radius: float = PID_INSTRUMENT_RADIUS

    def __post_init__(self) -> None:
        super().__post_init__()
        self.instrument_tag = _validate_tag(self.instrument_tag, "instrument_tag")
        self.controller_tag = _validate_tag(self.controller_tag, "controller_tag")
        self.instrument_center = normalize_point(self.instrument_center)
        self.controller_center = normalize_point(self.controller_center)
        _validate_positive(self.radius, "radius")
        self.radius = float(self.radius)

        if self.signal_points is not None:
            if not isinstance(self.signal_points, list) or len(self.signal_points) < 2:
                raise ValueError("signal_points must contain at least two points")
            self.signal_points = [normalize_point(point) for point in self.signal_points]

    def ports(self) -> PortMap:
        return {
            "instrument": list(self.instrument_center),
            "controller": list(self.controller_center),
        }

    def render(self) -> list[dict]:
        signal_points = self.signal_points or [self.instrument_center, self.controller_center]
        commands = []
        commands += instrument_bubble_commands(
            center=self.instrument_center,
            tag=self.instrument_tag,
            radius=self.radius,
        )
        commands += instrument_bubble_commands(
            center=self.controller_center,
            tag=self.controller_tag,
            radius=self.radius,
        )
        commands += signal_line_commands(signal_points)
        return commands

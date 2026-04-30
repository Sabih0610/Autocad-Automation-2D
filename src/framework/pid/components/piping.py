"""Reusable P&ID piping components."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.framework.pid.components.base import BasePIDComponent, Point, PortMap, normalize_point
from src.framework.pid.symbols import (
    PID_PIPE_LABEL_OFFSET,
    PID_TEXT_HEIGHT_NORMAL,
    flow_arrow_commands,
    pipe_line_commands,
    signal_line_commands,
    text_label_commands,
)


_FLOW_DIRECTIONS = {"RIGHT", "LEFT", "UP", "DOWN"}


def _normalize_direction(direction: str) -> str:
    normalized = direction.upper()
    if normalized not in _FLOW_DIRECTIONS:
        raise ValueError("flow_direction must be RIGHT, LEFT, UP, or DOWN")
    return normalized


def polyline_midpoint(points: list[Point]) -> Point:
    if len(points) < 2:
        raise ValueError("points must contain at least two points")

    segment_index = (len(points) - 2) // 2
    start = points[segment_index]
    end = points[segment_index + 1]
    return [
        (float(start[0]) + float(end[0])) / 2.0,
        (float(start[1]) + float(end[1])) / 2.0,
    ]


@dataclass
class PipeRunComponent(BasePIDComponent):
    points: list[Point] = field(default_factory=list)
    label: str | None = None
    label_position: Point | None = None
    flow_direction: str | None = None
    flow_arrow_position: Point | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.points, list) or len(self.points) < 2:
            raise ValueError("points must contain at least two points")
        self.points = [normalize_point(point) for point in self.points]

        if self.label is not None:
            if not isinstance(self.label, str) or not self.label.strip():
                raise ValueError("label must be non-empty when provided")
            self.label = self.label.strip()

        if self.label_position is not None:
            self.label_position = normalize_point(self.label_position)

        if self.flow_arrow_position is not None:
            self.flow_arrow_position = normalize_point(self.flow_arrow_position)

        if self.flow_direction is not None:
            self.flow_direction = _normalize_direction(self.flow_direction)

    def ports(self) -> PortMap:
        return {
            "start": list(self.points[0]),
            "end": list(self.points[-1]),
        }

    def render(self) -> list[dict]:
        commands = pipe_line_commands(self.points)

        if self.label:
            label_position = self.label_position
            if label_position is None:
                midpoint = polyline_midpoint(self.points)
                label_position = [midpoint[0] - PID_PIPE_LABEL_OFFSET * 0.8, midpoint[1] + PID_PIPE_LABEL_OFFSET]
            commands += text_label_commands(
                self.label,
                label_position,
                height=PID_TEXT_HEIGHT_NORMAL,
            )

        if self.flow_direction:
            arrow_position = self.flow_arrow_position or polyline_midpoint(self.points)
            commands += flow_arrow_commands(arrow_position, direction=self.flow_direction)

        return commands


@dataclass
class SignalLineComponent(BasePIDComponent):
    points: list[Point] = field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.points, list) or len(self.points) < 2:
            raise ValueError("points must contain at least two points")
        self.points = [normalize_point(point) for point in self.points]

    def ports(self) -> PortMap:
        return {
            "start": list(self.points[0]),
            "end": list(self.points[-1]),
        }

    def render(self) -> list[dict]:
        return signal_line_commands(self.points)

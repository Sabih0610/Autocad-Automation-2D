"""Reusable P&ID annotation components."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.framework.pid.components.base import BasePIDComponent, Point, normalize_point
from src.framework.pid.symbols import (
    PID_TEXT_HEIGHT_NORMAL,
    flow_arrow_commands,
    signal_line_commands,
    text_label_commands,
)


_FLOW_DIRECTIONS = {"RIGHT", "LEFT", "UP", "DOWN"}


def _validate_positive(value: float, name: str) -> None:
    if float(value) <= 0:
        raise ValueError(f"{name} must be positive")


def _normalize_direction(direction: str) -> str:
    normalized = direction.upper()
    if normalized not in _FLOW_DIRECTIONS:
        raise ValueError("direction must be RIGHT, LEFT, UP, or DOWN")
    return normalized


@dataclass
class LabelComponent(BasePIDComponent):
    text: str = ""
    height: float = PID_TEXT_HEIGHT_NORMAL

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("text must be non-empty")
        self.text = self.text.strip()
        _validate_positive(self.height, "height")
        self.height = float(self.height)

    def render(self) -> list[dict]:
        return text_label_commands(self.text, self.center, height=self.height)


@dataclass
class FlowArrowComponent(BasePIDComponent):
    direction: str = "RIGHT"
    size: float = 100.0

    def __post_init__(self) -> None:
        super().__post_init__()
        self.direction = _normalize_direction(self.direction)
        _validate_positive(self.size, "size")
        self.size = float(self.size)

    def render(self) -> list[dict]:
        return flow_arrow_commands(
            position=self.center,
            direction=self.direction,
            size=self.size,
        )


@dataclass
class LeaderLineComponent(BasePIDComponent):
    points: list[Point] = field(default_factory=list)
    text: str | None = None
    text_position: Point | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.points, list) or len(self.points) < 2:
            raise ValueError("points must contain at least two points")
        self.points = [normalize_point(point) for point in self.points]

        if self.text is not None:
            if not isinstance(self.text, str) or not self.text.strip():
                raise ValueError("text must be non-empty when provided")
            self.text = self.text.strip()

        if self.text_position is not None:
            self.text_position = normalize_point(self.text_position)

    def render(self) -> list[dict]:
        commands = signal_line_commands(self.points)
        if self.text:
            commands += text_label_commands(
                self.text,
                self.text_position or self.points[-1],
                height=PID_TEXT_HEIGHT_NORMAL,
            )
        return commands

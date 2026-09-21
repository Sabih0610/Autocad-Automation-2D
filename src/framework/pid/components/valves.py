"""Reusable P&ID valve components."""

from __future__ import annotations

from dataclasses import dataclass

from src.framework.pid.components.base import BasePIDComponent, PortMap
from src.framework.pid.symbols import PID_VALVE_SIZE, control_valve_commands, gate_valve_commands


def _validate_positive(value: float, name: str) -> None:
    if float(value) <= 0:
        raise ValueError(f"{name} must be positive")


def _normalize_orientation(orientation: str) -> str:
    normalized = orientation.upper()
    if normalized not in {"H", "V"}:
        raise ValueError("orientation must be 'H' or 'V'")
    return normalized


def _valve_ports(center: list[float], size: float, orientation: str) -> PortMap:
    cx, cy = center
    half = size / 2.0
    if orientation == "H":
        return {
            "left": [cx - half, cy],
            "right": [cx + half, cy],
        }

    return {
        "bottom": [cx, cy - half],
        "top": [cx, cy + half],
    }


@dataclass
class GateValveComponent(BasePIDComponent):
    orientation: str = "H"
    size: float = PID_VALVE_SIZE

    def __post_init__(self) -> None:
        super().__post_init__()
        self.orientation = _normalize_orientation(self.orientation)
        _validate_positive(self.size, "size")
        self.size = float(self.size)

    def ports(self) -> PortMap:
        return _valve_ports(self.center, self.size, self.orientation)

    def render(self) -> list[dict]:
        return gate_valve_commands(
            center=self.center,
            size=self.size,
            orientation=self.orientation,
            tag=self.tag,
        )


@dataclass
class ControlValveComponent(BasePIDComponent):
    orientation: str = "H"
    size: float = PID_VALVE_SIZE

    def __post_init__(self) -> None:
        super().__post_init__()
        self.orientation = _normalize_orientation(self.orientation)
        _validate_positive(self.size, "size")
        self.size = float(self.size)

    def ports(self) -> PortMap:
        return _valve_ports(self.center, self.size, self.orientation)

    def render(self) -> list[dict]:
        return control_valve_commands(
            center=self.center,
            size=self.size,
            orientation=self.orientation,
            tag=self.tag or self.id,
        )
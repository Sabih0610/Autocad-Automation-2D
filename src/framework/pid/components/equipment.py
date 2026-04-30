"""Reusable P&ID equipment components."""

from __future__ import annotations

from dataclasses import dataclass

from src.framework.pid.components.base import BasePIDComponent, PortMap
from src.framework.pid.symbols import horizontal_vessel_commands, vertical_vessel_commands


def _validate_positive(value: float, name: str) -> None:
    if float(value) <= 0:
        raise ValueError(f"{name} must be positive")


@dataclass
class HorizontalVesselComponent(BasePIDComponent):
    length: float = 2600.0
    diameter: float = 700.0

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_positive(self.length, "length")
        _validate_positive(self.diameter, "diameter")
        self.length = float(self.length)
        self.diameter = float(self.diameter)

    def ports(self) -> PortMap:
        cx, cy = self.center
        radius = self.diameter / 2.0
        return {
            "inlet_left": [cx - self.length / 2.0, cy],
            "outlet_right": [cx + self.length / 2.0, cy],
            "vapor_top": [cx + self.length * 0.30, cy + radius],
            "top_center": [cx, cy + radius],
            "bottom_center": [cx, cy - radius],
            "water_bottom_left": [cx - self.length * 0.30, cy - radius],
            "oil_bottom_right": [cx + self.length * 0.30, cy - radius],
        }

    def render(self) -> list[dict]:
        return horizontal_vessel_commands(
            center=self.center,
            length=self.length,
            diameter=self.diameter,
            tag=self.tag or self.id,
        )


@dataclass
class VerticalVesselComponent(BasePIDComponent):
    height: float = 1800.0
    diameter: float = 700.0

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_positive(self.height, "height")
        _validate_positive(self.diameter, "diameter")
        self.height = float(self.height)
        self.diameter = float(self.diameter)

    def ports(self) -> PortMap:
        cx, cy = self.center
        radius = self.diameter / 2.0
        return {
            "top": [cx, cy + self.height / 2.0],
            "bottom": [cx, cy - self.height / 2.0],
            "left": [cx - radius, cy],
            "right": [cx + radius, cy],
        }

    def render(self) -> list[dict]:
        return vertical_vessel_commands(
            center=self.center,
            height=self.height,
            diameter=self.diameter,
            tag=self.tag or self.id,
        )

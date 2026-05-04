"""Reusable 3D valve placeholder components."""

from __future__ import annotations

from dataclasses import dataclass

from src.framework.cad3d.components.base import BaseCAD3DComponent, PortMap3D, make_port3
from src.framework.cad3d.components.equipment import _validate_positive
from src.framework.cad3d.components.fittings import _axis_points, _validate_orientation_xyz


@dataclass
class ValvePlaceholder3DComponent(BaseCAD3DComponent):
    length: float = 400.0
    width: float = 300.0
    height: float = 300.0
    orientation: str = "X"
    valve_type: str = "gate"

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_positive(self.length, "length")
        _validate_positive(self.width, "width")
        _validate_positive(self.height, "height")
        if not isinstance(self.valve_type, str) or not self.valve_type.strip():
            raise ValueError("valve_type must be non-empty")
        self.length = float(self.length)
        self.width = float(self.width)
        self.height = float(self.height)
        self.orientation = _validate_orientation_xyz(self.orientation)
        self.valve_type = self.valve_type.strip()

    def ports(self) -> PortMap3D:
        inlet, outlet, inlet_direction, outlet_direction = _axis_points(
            self.center,
            self.length,
            self.orientation,
        )
        nozzle_diameter = min(self.width, self.height) * 0.5
        return {
            "inlet": make_port3(inlet, inlet_direction, nozzle_diameter, "valve_end"),
            "outlet": make_port3(outlet, outlet_direction, nozzle_diameter, "valve_end"),
        }

    def to_scene_component(self) -> dict:
        component = {
            "component_type": "valve_placeholder_3d",
            "id": self.id,
            "center": self.center,
            "length": self.length,
            "width": self.width,
            "height": self.height,
            "orientation": self.orientation,
            "valve_type": self.valve_type,
            "metadata": self.metadata,
        }
        if self.tag is not None:
            component["tag"] = self.tag
        return component

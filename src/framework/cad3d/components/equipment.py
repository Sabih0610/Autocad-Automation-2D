"""Reusable 3D equipment components."""

from __future__ import annotations

from dataclasses import dataclass

from src.framework.cad3d.components.base import BaseCAD3DComponent, PortMap3D, make_port3


def _validate_positive(value: float, name: str) -> None:
    if float(value) <= 0:
        raise ValueError(f"{name} must be positive")


@dataclass
class VerticalTank3DComponent(BaseCAD3DComponent):
    diameter: float = 2000.0
    height: float = 5000.0

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_positive(self.diameter, "diameter")
        _validate_positive(self.height, "height")
        self.diameter = float(self.diameter)
        self.height = float(self.height)

    def ports(self) -> PortMap3D:
        cx, cy, cz = self.center
        radius = self.diameter / 2.0
        top_z = cz + self.height / 2.0
        bottom_z = cz - self.height / 2.0
        return {
            "top": make_port3([cx, cy, top_z], [0, 0, 1], self.diameter * 0.15, "nozzle"),
            "bottom": make_port3([cx, cy, bottom_z], [0, 0, -1], self.diameter * 0.15, "nozzle"),
            "side_left": make_port3([cx - radius, cy, cz], [-1, 0, 0], self.diameter * 0.12, "nozzle"),
            "side_right": make_port3([cx + radius, cy, cz], [1, 0, 0], self.diameter * 0.12, "nozzle"),
        }

    def to_scene_component(self) -> dict:
        return {
            "component_type": "vertical_tank_3d",
            "id": self.id,
            "tag": self.tag,
            "center": self.center,
            "diameter": self.diameter,
            "height": self.height,
            "metadata": self.metadata,
        }


@dataclass
class HorizontalVessel3DComponent(BaseCAD3DComponent):
    diameter: float = 1400.0
    length: float = 4000.0
    orientation: str = "X"

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_positive(self.diameter, "diameter")
        _validate_positive(self.length, "length")
        self.diameter = float(self.diameter)
        self.length = float(self.length)
        self.orientation = self.orientation.upper()
        if self.orientation not in {"X", "Y"}:
            raise ValueError("orientation must be X or Y")

    def ports(self) -> PortMap3D:
        cx, cy, cz = self.center
        radius = self.diameter / 2.0
        half_length = self.length / 2.0

        if self.orientation == "X":
            end_a = [cx - half_length, cy, cz]
            end_b = [cx + half_length, cy, cz]
            dir_a = [-1, 0, 0]
            dir_b = [1, 0, 0]
        else:
            end_a = [cx, cy - half_length, cz]
            end_b = [cx, cy + half_length, cz]
            dir_a = [0, -1, 0]
            dir_b = [0, 1, 0]

        return {
            "end_a": make_port3(end_a, dir_a, self.diameter * 0.15, "nozzle"),
            "end_b": make_port3(end_b, dir_b, self.diameter * 0.15, "nozzle"),
            "top": make_port3([cx, cy, cz + radius], [0, 0, 1], self.diameter * 0.12, "nozzle"),
            "bottom": make_port3([cx, cy, cz - radius], [0, 0, -1], self.diameter * 0.12, "nozzle"),
        }

    def to_scene_component(self) -> dict:
        return {
            "component_type": "horizontal_vessel_3d",
            "id": self.id,
            "tag": self.tag,
            "center": self.center,
            "diameter": self.diameter,
            "length": self.length,
            "orientation": self.orientation,
            "metadata": self.metadata,
        }


@dataclass
class HeatExchanger3DComponent(BaseCAD3DComponent):
    length: float = 2500.0
    diameter: float = 600.0
    orientation: str = "X"

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_positive(self.length, "length")
        _validate_positive(self.diameter, "diameter")
        self.length = float(self.length)
        self.diameter = float(self.diameter)
        self.orientation = self.orientation.upper()
        if self.orientation not in {"X", "Y"}:
            raise ValueError("orientation must be X or Y")

    def ports(self) -> PortMap3D:
        cx, cy, cz = self.center
        half_length = self.length / 2.0
        nozzle_diameter = self.diameter * 0.25

        if self.orientation == "X":
            return {
                "inlet": make_port3([cx - half_length, cy, cz], [-1, 0, 0], nozzle_diameter, "nozzle"),
                "outlet": make_port3([cx + half_length, cy, cz], [1, 0, 0], nozzle_diameter, "nozzle"),
            }

        return {
            "inlet": make_port3([cx, cy - half_length, cz], [0, -1, 0], nozzle_diameter, "nozzle"),
            "outlet": make_port3([cx, cy + half_length, cz], [0, 1, 0], nozzle_diameter, "nozzle"),
        }

    def to_scene_component(self) -> dict:
        return {
            "component_type": "heat_exchanger_3d",
            "id": self.id,
            "tag": self.tag,
            "center": self.center,
            "length": self.length,
            "diameter": self.diameter,
            "orientation": self.orientation,
            "metadata": self.metadata,
        }


@dataclass
class PumpPlaceholder3DComponent(BaseCAD3DComponent):
    length: float = 900.0
    width: float = 600.0
    height: float = 500.0

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_positive(self.length, "length")
        _validate_positive(self.width, "width")
        _validate_positive(self.height, "height")
        self.length = float(self.length)
        self.width = float(self.width)
        self.height = float(self.height)

    def ports(self) -> PortMap3D:
        cx, cy, cz = self.center
        return {
            "suction": make_port3([cx - self.length / 2.0, cy, cz], [-1, 0, 0], self.width * 0.25, "nozzle"),
            "discharge": make_port3([cx + self.length / 2.0, cy, cz], [1, 0, 0], self.width * 0.25, "nozzle"),
        }

    def to_scene_component(self) -> dict:
        return {
            "component_type": "pump_placeholder_3d",
            "id": self.id,
            "tag": self.tag,
            "center": self.center,
            "length": self.length,
            "width": self.width,
            "height": self.height,
            "metadata": self.metadata,
        }


@dataclass
class SkidBase3DComponent(BaseCAD3DComponent):
    length: float = 8000.0
    width: float = 3500.0
    height: float = 250.0

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_positive(self.length, "length")
        _validate_positive(self.width, "width")
        _validate_positive(self.height, "height")
        self.length = float(self.length)
        self.width = float(self.width)
        self.height = float(self.height)

    def to_scene_component(self) -> dict:
        return {
            "component_type": "skid_base_3d",
            "id": self.id,
            "center": self.center,
            "length": self.length,
            "width": self.width,
            "height": self.height,
            "metadata": self.metadata,
        }


@dataclass
class Box3DComponent(BaseCAD3DComponent):
    length: float = 1000.0
    width: float = 1000.0
    height: float = 1000.0

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_positive(self.length, "length")
        _validate_positive(self.width, "width")
        _validate_positive(self.height, "height")
        self.length = float(self.length)
        self.width = float(self.width)
        self.height = float(self.height)

    def to_scene_component(self) -> dict:
        component = {
            "component_type": "box_3d",
            "id": self.id,
            "center": self.center,
            "length": self.length,
            "width": self.width,
            "height": self.height,
            "metadata": self.metadata,
        }
        if self.tag is not None:
            component["tag"] = self.tag
        return component

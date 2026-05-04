"""Reusable 3D fitting components."""

from __future__ import annotations

from dataclasses import dataclass

from src.framework.cad3d.components.base import BaseCAD3DComponent, PortMap3D, make_port3
from src.framework.cad3d.components.equipment import _validate_positive


def _validate_orientation_xyz(orientation: str) -> str:
    normalized = str(orientation).upper()
    if normalized not in {"X", "Y", "Z"}:
        raise ValueError("orientation must be X, Y, or Z")
    return normalized


def _axis_points(center: list[float], length: float, orientation: str) -> tuple[list[float], list[float], list[float], list[float]]:
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


@dataclass
class Nozzle3DComponent(BaseCAD3DComponent):
    diameter: float = 150.0
    length: float = 400.0
    orientation: str = "X"

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_positive(self.diameter, "diameter")
        _validate_positive(self.length, "length")
        self.diameter = float(self.diameter)
        self.length = float(self.length)
        self.orientation = _validate_orientation_xyz(self.orientation)

    def ports(self) -> PortMap3D:
        base, tip, base_direction, tip_direction = _axis_points(self.center, self.length, self.orientation)
        return {
            "base": make_port3(base, base_direction, self.diameter, "nozzle_base"),
            "tip": make_port3(tip, tip_direction, self.diameter, "nozzle_tip"),
        }

    def to_scene_component(self) -> dict:
        component = {
            "component_type": "nozzle_3d",
            "id": self.id,
            "center": self.center,
            "diameter": self.diameter,
            "length": self.length,
            "orientation": self.orientation,
            "metadata": self.metadata,
        }
        if self.tag is not None:
            component["tag"] = self.tag
        return component


@dataclass
class Flange3DComponent(BaseCAD3DComponent):
    diameter: float = 250.0
    thickness: float = 80.0
    orientation: str = "X"

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_positive(self.diameter, "diameter")
        _validate_positive(self.thickness, "thickness")
        self.diameter = float(self.diameter)
        self.thickness = float(self.thickness)
        self.orientation = _validate_orientation_xyz(self.orientation)

    def ports(self) -> PortMap3D:
        face_a, face_b, dir_a, dir_b = _axis_points(self.center, self.thickness, self.orientation)
        return {
            "face_a": make_port3(face_a, dir_a, self.diameter, "flange_face"),
            "face_b": make_port3(face_b, dir_b, self.diameter, "flange_face"),
        }

    def to_scene_component(self) -> dict:
        component = {
            "component_type": "flange_3d",
            "id": self.id,
            "center": self.center,
            "diameter": self.diameter,
            "thickness": self.thickness,
            "orientation": self.orientation,
            "metadata": self.metadata,
        }
        if self.tag is not None:
            component["tag"] = self.tag
        return component

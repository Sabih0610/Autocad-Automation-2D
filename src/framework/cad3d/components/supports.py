"""Reusable 3D support components."""

from __future__ import annotations

from dataclasses import dataclass

from src.framework.cad3d.components.base import BaseCAD3DComponent, PortMap3D, make_port3
from src.framework.cad3d.components.equipment import _validate_positive


@dataclass
class SupportLeg3DComponent(BaseCAD3DComponent):
    diameter: float = 120.0
    height: float = 1000.0

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_positive(self.diameter, "diameter")
        _validate_positive(self.height, "height")
        self.diameter = float(self.diameter)
        self.height = float(self.height)

    def ports(self) -> PortMap3D:
        cx, cy, cz = self.center
        return {
            "top": make_port3([cx, cy, cz + self.height / 2.0], [0, 0, 1], self.diameter, "support_top"),
            "bottom": make_port3([cx, cy, cz - self.height / 2.0], [0, 0, -1], self.diameter, "support_bottom"),
        }

    def to_scene_component(self) -> dict:
        component = {
            "component_type": "support_leg_3d",
            "id": self.id,
            "center": self.center,
            "diameter": self.diameter,
            "height": self.height,
            "metadata": self.metadata,
        }
        if self.tag is not None:
            component["tag"] = self.tag
        return component


@dataclass
class SaddleSupport3DComponent(BaseCAD3DComponent):
    length: float = 700.0
    width: float = 350.0
    height: float = 500.0

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
            "component_type": "saddle_support_3d",
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


@dataclass
class PipeSupport3DComponent(BaseCAD3DComponent):
    height: float = 800.0
    width: float = 300.0
    depth: float = 300.0

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_positive(self.height, "height")
        _validate_positive(self.width, "width")
        _validate_positive(self.depth, "depth")
        self.height = float(self.height)
        self.width = float(self.width)
        self.depth = float(self.depth)

    def ports(self) -> PortMap3D:
        cx, cy, cz = self.center
        return {
            "top": make_port3([cx, cy, cz + self.height / 2.0], [0, 0, 1], self.width, "pipe_support_top"),
        }

    def to_scene_component(self) -> dict:
        component = {
            "component_type": "pipe_support_3d",
            "id": self.id,
            "center": self.center,
            "height": self.height,
            "width": self.width,
            "depth": self.depth,
            "metadata": self.metadata,
        }
        if self.tag is not None:
            component["tag"] = self.tag
        return component

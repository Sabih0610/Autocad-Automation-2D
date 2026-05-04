"""Reusable 3D piping components."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.framework.cad3d.components.base import (
    BaseCAD3DComponent,
    Point3D,
    PortMap3D,
    make_port3,
    normalize_point3,
    normalize_vector3,
)


def vector_between_points(a: Point3D, b: Point3D) -> Point3D:
    start = normalize_point3(a)
    end = normalize_point3(b)
    return normalize_vector3([
        end[0] - start[0],
        end[1] - start[1],
        end[2] - start[2],
    ])


@dataclass
class PipeRun3DComponent(BaseCAD3DComponent):
    points: list[Point3D] = field(default_factory=list)
    diameter: float = 100.0

    def __post_init__(self) -> None:
        super().__post_init__()
        if len(self.points) < 2:
            raise ValueError("pipe run requires at least two points")
        self.points = [normalize_point3(point) for point in self.points]
        if float(self.diameter) <= 0:
            raise ValueError("diameter must be positive")
        self.diameter = float(self.diameter)

    def ports(self) -> PortMap3D:
        return {
            "start": make_port3(
                self.points[0],
                vector_between_points(self.points[1], self.points[0]),
                self.diameter,
                "pipe_end",
            ),
            "end": make_port3(
                self.points[-1],
                vector_between_points(self.points[-2], self.points[-1]),
                self.diameter,
                "pipe_end",
            ),
        }

    def to_scene_component(self) -> dict:
        component = {
            "component_type": "pipe_run_3d",
            "id": self.id,
            "points": self.points,
            "diameter": self.diameter,
            "metadata": self.metadata,
        }
        if self.tag is not None:
            component["tag"] = self.tag
        return component

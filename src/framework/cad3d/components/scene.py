"""Composable scene model for reusable 3D CAD components."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.framework.cad3d.components.base import CAD3DComponent, Port3D, render_cad3d_component
from src.framework.cad3d.scene_schema import CAD3D_SCENE_SCHEMA_VERSION, validate_cad3d_scene


@dataclass
class CAD3DComponentScene:
    title: str
    components: list[CAD3DComponent] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    units: str = "mm"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("title must be non-empty")
        self.title = self.title.strip()

        if self.units != "mm":
            raise ValueError("units must be 'mm'")

        if not isinstance(self.assumptions, list) or not all(
            isinstance(assumption, str) for assumption in self.assumptions
        ):
            raise ValueError("assumptions must be a list of strings")

        if not isinstance(self.metadata, dict):
            raise ValueError("metadata must be a dict")

        initial_components = list(self.components)
        self.components = []
        for component in initial_components:
            self.add(component)

    def add(self, component: CAD3DComponent) -> None:
        if any(existing.id == component.id for existing in self.components):
            raise ValueError(f"duplicate component id: {component.id}")
        self.components.append(component)

    def get(self, component_id: str) -> CAD3DComponent:
        for component in self.components:
            if component.id == component_id:
                return component
        raise KeyError(component_id)

    def all_ports(self) -> dict[str, Port3D]:
        ports: dict[str, Port3D] = {}
        for component in self.components:
            rendered = render_cad3d_component(component)
            for port_name, port in rendered.ports.items():
                ports[f"{component.id}.{port_name}"] = port
        return ports

    def to_scene_data(self) -> dict:
        scene = {
            "schema_version": CAD3D_SCENE_SCHEMA_VERSION,
            "title": self.title,
            "units": self.units,
            "assumptions": [
                *self.assumptions,
                "Generated from reusable 3D CAD components.",
            ],
            "metadata": self.metadata,
            "components": [
                component.to_scene_component()
                for component in self.components
            ],
        }

        errors = validate_cad3d_scene(scene)
        if errors:
            joined_errors = "\n".join(f"- {error}" for error in errors)
            raise ValueError(f"Rendered 3D component scene failed validation:\n{joined_errors}")

        return scene

    def summary(self) -> str:
        component_ids = ", ".join(component.id for component in self.components) or "none"
        return (
            f"{self.title}: {len(self.components)} component(s). "
            f"Components: {component_ids}."
        )


def make_cad3d_component_scene(title: str, components: list[CAD3DComponent]) -> CAD3DComponentScene:
    scene = CAD3DComponentScene(title=title)
    for component in components:
        scene.add(component)
    return scene

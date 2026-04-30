"""Composable scene model for reusable P&ID components."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.framework.commands.schema import validate_command_sequence
from src.framework.pid.components.base import PIDComponent, Point, render_component
from src.framework.pid.symbols import pid_standard_layers, wrap_commands_as_sequence


@dataclass
class PIDComponentScene:
    title: str
    components: list[PIDComponent] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("title must be non-empty")
        self.title = self.title.strip()

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

    def add(self, component: PIDComponent) -> None:
        if any(existing.id == component.id for existing in self.components):
            raise ValueError(f"duplicate component id: {component.id}")
        self.components.append(component)

    def get(self, component_id: str) -> PIDComponent:
        for component in self.components:
            if component.id == component_id:
                return component
        raise KeyError(component_id)

    def all_ports(self) -> dict[str, Point]:
        ports: dict[str, Point] = {}
        for component in self.components:
            rendered = render_component(component)
            for port_name, point in rendered.ports.items():
                ports[f"{component.id}.{port_name}"] = point
        return ports

    def render_commands(self, include_standard_layers: bool = True) -> list[dict]:
        commands = pid_standard_layers() if include_standard_layers else []

        for component in self.components:
            rendered = render_component(component)
            commands.extend(rendered.commands)

        return commands

    def to_command_sequence(self) -> dict:
        sequence = wrap_commands_as_sequence(
            self.render_commands(),
            summary=f"P&ID component scene: {self.title}",
        )
        sequence["assumptions"].extend(self.assumptions)
        sequence["assumptions"].append("Generated from reusable P&ID components.")

        errors = validate_command_sequence(sequence)
        if errors:
            joined_errors = "\n".join(f"- {error}" for error in errors)
            raise ValueError(f"Rendered P&ID component scene failed validation:\n{joined_errors}")

        return sequence

    def summary(self) -> str:
        component_ids = ", ".join(component.id for component in self.components) or "none"
        return (
            f"{self.title}: {len(self.components)} component(s). "
            f"Components: {component_ids}."
        )


def make_component_scene(title: str, components: list[PIDComponent]) -> PIDComponentScene:
    scene = PIDComponentScene(title=title)
    for component in components:
        scene.add(component)
    return scene

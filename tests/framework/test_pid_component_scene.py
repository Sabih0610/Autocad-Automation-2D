from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.framework.commands.schema import validate_command_sequence
from src.framework.pid.components.base import BasePIDComponent
from src.framework.pid.components.scene import PIDComponentScene, make_component_scene


@dataclass
class FakeComponent(BasePIDComponent):
    def ports(self) -> dict[str, list[float]]:
        return {"out": [100.0, 0.0]}

    def render(self) -> list[dict]:
        return [
            {
                "command": "LINE",
                "from": [0, 0],
                "to": [100, 0],
                "layer": "PID_PIPING",
            }
        ]


@dataclass
class InvalidComponent(BasePIDComponent):
    def render(self) -> list[dict]:
        return [
            {
                "command": "LINE",
                "from": [0, 0],
                "layer": "PID_PIPING",
            }
        ]


def test_scene_requires_non_empty_title() -> None:
    with pytest.raises(ValueError, match="title must be"):
        PIDComponentScene(title="")


def test_can_add_component() -> None:
    scene = PIDComponentScene(title="Test Scene")
    component = FakeComponent(id="FC1")

    scene.add(component)

    assert scene.components == [component]


def test_duplicate_component_id_raises_value_error() -> None:
    scene = PIDComponentScene(title="Test Scene")
    scene.add(FakeComponent(id="FC1"))

    with pytest.raises(ValueError, match="duplicate component id"):
        scene.add(FakeComponent(id="FC1"))


def test_get_existing_component_works() -> None:
    scene = PIDComponentScene(title="Test Scene")
    component = FakeComponent(id="FC1")
    scene.add(component)

    assert scene.get("FC1") is component


def test_get_missing_component_raises_key_error() -> None:
    scene = PIDComponentScene(title="Test Scene")

    with pytest.raises(KeyError):
        scene.get("MISSING")


def test_all_ports_returns_component_prefixed_port_keys() -> None:
    scene = PIDComponentScene(title="Test Scene")
    scene.add(FakeComponent(id="FC1"))

    assert scene.all_ports() == {"FC1.out": [100.0, 0.0]}


def test_render_commands_includes_standard_layers_by_default() -> None:
    scene = PIDComponentScene(title="Test Scene")
    scene.add(FakeComponent(id="FC1"))

    commands = scene.render_commands()

    assert commands[0]["command"] == "LAYER"
    assert any(command["command"] == "LINE" for command in commands)


def test_render_commands_can_omit_standard_layers() -> None:
    scene = PIDComponentScene(title="Test Scene")
    scene.add(FakeComponent(id="FC1"))

    commands = scene.render_commands(include_standard_layers=False)

    assert commands[0]["command"] == "LINE"


def test_to_command_sequence_validates_with_fake_component() -> None:
    scene = PIDComponentScene(
        title="Test Scene",
        assumptions=["Scene-level assumption."],
    )
    scene.add(FakeComponent(id="FC1"))

    sequence = scene.to_command_sequence()

    assert validate_command_sequence(sequence) == []
    assert sequence["summary"] == "P&ID component scene: Test Scene"
    assert "Scene-level assumption." in sequence["assumptions"]
    assert "Generated from reusable P&ID components." in sequence["assumptions"]


def test_summary_includes_title_and_component_count() -> None:
    scene = PIDComponentScene(title="Test Scene")
    scene.add(FakeComponent(id="FC1"))

    summary = scene.summary()

    assert "Test Scene" in summary
    assert "1 component" in summary
    assert "FC1" in summary


def test_make_component_scene_creates_scene_and_adds_components() -> None:
    component = FakeComponent(id="FC1")

    scene = make_component_scene("Factory Scene", [component])

    assert scene.title == "Factory Scene"
    assert scene.components == [component]


def test_invalid_rendered_commands_raise_value_error_in_to_command_sequence() -> None:
    scene = PIDComponentScene(title="Broken Scene")
    scene.add(InvalidComponent(id="BAD1"))

    with pytest.raises(ValueError, match="failed validation"):
        scene.to_command_sequence()

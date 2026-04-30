from __future__ import annotations

import pytest

from src.framework.commands.schema import validate_command_sequence
from src.framework.pid.components.scene import PIDComponentScene
from src.framework.pid.components.valves import ControlValveComponent, GateValveComponent


def _assert_component_scene_valid(component) -> None:
    scene = PIDComponentScene(title="Valve Test", components=[component])
    assert validate_command_sequence(scene.to_command_sequence()) == []


def test_gate_valve_horizontal_ports_left_and_right() -> None:
    component = GateValveComponent(id="XV1", center=[0, 0], orientation="H", size=120)

    assert component.ports() == {
        "left": [-60.0, 0.0],
        "right": [60.0, 0.0],
    }


def test_gate_valve_vertical_ports_top_and_bottom() -> None:
    component = GateValveComponent(id="XV1", center=[0, 0], orientation="V", size=120)

    assert component.ports() == {
        "bottom": [0.0, -60.0],
        "top": [0.0, 60.0],
    }


def test_gate_valve_render_validates_in_scene() -> None:
    _assert_component_scene_valid(GateValveComponent(id="XV1", center=[0, 0]))


def test_control_valve_render_validates_in_scene() -> None:
    _assert_component_scene_valid(ControlValveComponent(id="LV1", center=[0, 0]))


def test_invalid_valve_orientation_raises_value_error() -> None:
    with pytest.raises(ValueError, match="orientation must be"):
        GateValveComponent(id="XV1", orientation="DIAGONAL")

    with pytest.raises(ValueError, match="orientation must be"):
        ControlValveComponent(id="LV1", orientation="DIAGONAL")


def test_invalid_valve_size_raises_value_error() -> None:
    with pytest.raises(ValueError, match="size must be positive"):
        GateValveComponent(id="XV1", size=0)

    with pytest.raises(ValueError, match="size must be positive"):
        ControlValveComponent(id="LV1", size=-1)

from __future__ import annotations

import pytest

from src.framework.commands.schema import validate_command_sequence
from src.framework.pid.components.equipment import (
    HorizontalVesselComponent,
    VerticalVesselComponent,
)
from src.framework.pid.components.scene import PIDComponentScene


def _assert_component_scene_valid(component) -> None:
    scene = PIDComponentScene(title="Equipment Test", components=[component])
    assert validate_command_sequence(scene.to_command_sequence()) == []


def test_horizontal_vessel_ports_contain_expected_keys() -> None:
    component = HorizontalVesselComponent(id="V101", tag="V-101", center=[0, 0])

    assert set(component.ports()) == {
        "inlet_left",
        "outlet_right",
        "vapor_top",
        "top_center",
        "bottom_center",
        "water_bottom_left",
        "oil_bottom_right",
    }
    assert component.ports()["inlet_left"] == [-1300.0, 0.0]


def test_horizontal_vessel_render_validates_in_scene() -> None:
    _assert_component_scene_valid(
        HorizontalVesselComponent(id="V101", tag="V-101", center=[0, 0])
    )


def test_vertical_vessel_ports_contain_expected_keys() -> None:
    component = VerticalVesselComponent(id="V201", tag="V-201", center=[0, 0])

    assert set(component.ports()) == {"top", "bottom", "left", "right"}
    assert component.ports()["top"] == [0.0, 900.0]


def test_vertical_vessel_render_validates_in_scene() -> None:
    _assert_component_scene_valid(
        VerticalVesselComponent(id="V201", tag="V-201", center=[0, 0])
    )


def test_invalid_equipment_dimensions_raise_value_error() -> None:
    with pytest.raises(ValueError, match="length must be positive"):
        HorizontalVesselComponent(id="V101", length=0)

    with pytest.raises(ValueError, match="diameter must be positive"):
        HorizontalVesselComponent(id="V101", diameter=-1)

    with pytest.raises(ValueError, match="height must be positive"):
        VerticalVesselComponent(id="V201", height=0)

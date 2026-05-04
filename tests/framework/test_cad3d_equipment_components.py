from __future__ import annotations

import pytest

from src.framework.cad3d.components.equipment import (
    Box3DComponent,
    HeatExchanger3DComponent,
    HorizontalVessel3DComponent,
    PumpPlaceholder3DComponent,
    SkidBase3DComponent,
    VerticalTank3DComponent,
)
from src.framework.cad3d.components.scene import CAD3DComponentScene
from src.framework.cad3d.scene_schema import validate_cad3d_scene


def _assert_component_validates(component) -> None:
    scene = CAD3DComponentScene(title="Equipment Test")
    scene.add(component)
    assert validate_cad3d_scene(scene.to_scene_data()) == []


def test_vertical_tank_ports_include_expected_keys() -> None:
    ports = VerticalTank3DComponent(id="T101", tag="T-101").ports()

    assert {"top", "bottom", "side_left", "side_right"}.issubset(ports)


def test_vertical_tank_scene_component_validates_in_scene() -> None:
    _assert_component_validates(VerticalTank3DComponent(id="T101", tag="T-101"))


def test_horizontal_vessel_x_ports_include_expected_keys() -> None:
    ports = HorizontalVessel3DComponent(id="V201", tag="V-201", orientation="X").ports()

    assert {"end_a", "end_b", "top", "bottom"}.issubset(ports)
    assert ports["end_a"]["direction"] == [-1.0, 0.0, 0.0]


def test_horizontal_vessel_y_works() -> None:
    component = HorizontalVessel3DComponent(id="V201", tag="V-201", orientation="Y")

    assert component.ports()["end_b"]["direction"] == [0.0, 1.0, 0.0]
    _assert_component_validates(component)


def test_pump_ports_include_suction_discharge() -> None:
    ports = PumpPlaceholder3DComponent(id="P101", tag="P-101").ports()

    assert {"suction", "discharge"}.issubset(ports)


def test_heat_exchanger_ports_include_inlet_outlet() -> None:
    ports = HeatExchanger3DComponent(id="E101", tag="E-101", orientation="X").ports()

    assert {"inlet", "outlet"}.issubset(ports)
    assert ports["inlet"]["direction"] == [-1.0, 0.0, 0.0]


def test_heat_exchanger_validates() -> None:
    _assert_component_validates(HeatExchanger3DComponent(id="E101", tag="E-101"))


def test_skid_base_validates() -> None:
    _assert_component_validates(SkidBase3DComponent(id="SKID101"))


def test_box_validates() -> None:
    _assert_component_validates(Box3DComponent(id="B1"))


def test_invalid_dimensions_raise_value_error() -> None:
    with pytest.raises(ValueError):
        VerticalTank3DComponent(id="T101", tag="T-101", diameter=-1)

    with pytest.raises(ValueError):
        PumpPlaceholder3DComponent(id="P101", tag="P-101", height=0)

    with pytest.raises(ValueError):
        HeatExchanger3DComponent(id="E101", tag="E-101", length=0)


def test_invalid_vessel_orientation_raises_value_error() -> None:
    with pytest.raises(ValueError):
        HorizontalVessel3DComponent(id="V201", tag="V-201", orientation="Z")

    with pytest.raises(ValueError):
        HeatExchanger3DComponent(id="E101", tag="E-101", orientation="Z")

from __future__ import annotations

import pytest

from src.framework.cad3d.components.scene import CAD3DComponentScene
from src.framework.cad3d.components.valves import ValvePlaceholder3DComponent
from src.framework.cad3d.scene_schema import validate_cad3d_scene


def _assert_component_validates(component) -> None:
    scene = CAD3DComponentScene(title="Valve Test")
    scene.add(component)
    assert validate_cad3d_scene(scene.to_scene_data()) == []


def test_valve_placeholder_validates() -> None:
    _assert_component_validates(ValvePlaceholder3DComponent(id="XV1", center=[0, 0, 0]))


def test_valve_ports_include_inlet_outlet() -> None:
    ports = ValvePlaceholder3DComponent(id="XV1", center=[0, 0, 0], length=400, orientation="X").ports()

    assert {"inlet", "outlet"}.issubset(ports)
    assert ports["inlet"]["position"] == [-200.0, 0.0, 0.0]
    assert ports["outlet"]["direction"] == [1.0, 0.0, 0.0]


@pytest.mark.parametrize(
    ("orientation", "expected_direction"),
    [
        ("X", [1.0, 0.0, 0.0]),
        ("Y", [0.0, 1.0, 0.0]),
        ("Z", [0.0, 0.0, 1.0]),
    ],
)
def test_valve_orientation_xyz_works(orientation: str, expected_direction: list[float]) -> None:
    valve = ValvePlaceholder3DComponent(id=f"XV_{orientation}", center=[0, 0, 0], orientation=orientation)

    assert valve.ports()["outlet"]["direction"] == expected_direction
    _assert_component_validates(valve)


def test_invalid_orientation_raises_value_error() -> None:
    with pytest.raises(ValueError):
        ValvePlaceholder3DComponent(id="XV1", orientation="BAD")


def test_invalid_dimensions_raise_value_error() -> None:
    with pytest.raises(ValueError):
        ValvePlaceholder3DComponent(id="XV1", length=-1)

    with pytest.raises(ValueError):
        ValvePlaceholder3DComponent(id="XV1", height=0)


def test_empty_valve_type_raises_value_error() -> None:
    with pytest.raises(ValueError):
        ValvePlaceholder3DComponent(id="XV1", valve_type="")

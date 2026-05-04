from __future__ import annotations

import pytest

from src.framework.cad3d.components.fittings import Flange3DComponent, Nozzle3DComponent
from src.framework.cad3d.components.scene import CAD3DComponentScene
from src.framework.cad3d.scene_schema import validate_cad3d_scene


def _assert_component_validates(component) -> None:
    scene = CAD3DComponentScene(title="Fitting Test")
    scene.add(component)
    assert validate_cad3d_scene(scene.to_scene_data()) == []


def test_nozzle_validates() -> None:
    _assert_component_validates(Nozzle3DComponent(id="N1", center=[0, 0, 0], orientation="X"))


def test_nozzle_ports_include_base_tip() -> None:
    ports = Nozzle3DComponent(id="N1", center=[0, 0, 0], length=400, orientation="X").ports()

    assert {"base", "tip"}.issubset(ports)
    assert ports["base"]["position"] == [-200.0, 0.0, 0.0]
    assert ports["tip"]["direction"] == [1.0, 0.0, 0.0]


def test_flange_validates() -> None:
    _assert_component_validates(Flange3DComponent(id="F1", center=[0, 0, 0], orientation="Y"))


def test_flange_ports_include_face_a_face_b() -> None:
    ports = Flange3DComponent(id="F1", center=[0, 0, 0], thickness=80, orientation="Z").ports()

    assert {"face_a", "face_b"}.issubset(ports)
    assert ports["face_a"]["position"] == [0.0, 0.0, -40.0]
    assert ports["face_b"]["direction"] == [0.0, 0.0, 1.0]


def test_invalid_orientation_raises_value_error() -> None:
    with pytest.raises(ValueError):
        Nozzle3DComponent(id="N1", orientation="BAD")

    with pytest.raises(ValueError):
        Flange3DComponent(id="F1", orientation="BAD")


def test_invalid_dimensions_raise_value_error() -> None:
    with pytest.raises(ValueError):
        Nozzle3DComponent(id="N1", diameter=0)

    with pytest.raises(ValueError):
        Flange3DComponent(id="F1", thickness=-1)

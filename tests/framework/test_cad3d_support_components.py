from __future__ import annotations

import pytest

from src.framework.cad3d.components.scene import CAD3DComponentScene
from src.framework.cad3d.components.supports import (
    PipeSupport3DComponent,
    SaddleSupport3DComponent,
    SupportLeg3DComponent,
)
from src.framework.cad3d.scene_schema import validate_cad3d_scene


def _assert_component_validates(component) -> None:
    scene = CAD3DComponentScene(title="Support Test")
    scene.add(component)
    assert validate_cad3d_scene(scene.to_scene_data()) == []


def test_support_leg_validates() -> None:
    _assert_component_validates(SupportLeg3DComponent(id="LEG1", center=[0, 0, 500]))


def test_support_leg_ports_include_top_bottom() -> None:
    ports = SupportLeg3DComponent(id="LEG1", center=[0, 0, 500], height=1000).ports()

    assert {"top", "bottom"}.issubset(ports)
    assert ports["top"]["position"] == [0.0, 0.0, 1000.0]
    assert ports["bottom"]["position"] == [0.0, 0.0, 0.0]


def test_saddle_support_validates() -> None:
    _assert_component_validates(SaddleSupport3DComponent(id="SAD1", center=[0, 0, 250]))


def test_pipe_support_validates() -> None:
    _assert_component_validates(PipeSupport3DComponent(id="PS1", center=[0, 0, 400]))


def test_pipe_support_port_includes_top() -> None:
    ports = PipeSupport3DComponent(id="PS1", center=[0, 0, 400], height=800).ports()

    assert "top" in ports
    assert ports["top"]["position"] == [0.0, 0.0, 800.0]


def test_invalid_dimensions_raise_value_error() -> None:
    with pytest.raises(ValueError):
        SupportLeg3DComponent(id="LEG1", diameter=-1)

    with pytest.raises(ValueError):
        SaddleSupport3DComponent(id="SAD1", width=0)

    with pytest.raises(ValueError):
        PipeSupport3DComponent(id="PS1", depth=-1)

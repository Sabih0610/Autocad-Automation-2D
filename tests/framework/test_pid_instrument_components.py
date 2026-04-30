from __future__ import annotations

import pytest

from src.framework.commands.schema import validate_command_sequence
from src.framework.pid.components.instruments import (
    ControllerLoopComponent,
    InstrumentBubbleComponent,
)
from src.framework.pid.components.scene import PIDComponentScene


def _assert_component_scene_valid(component) -> None:
    scene = PIDComponentScene(title="Instrument Test", components=[component])
    assert validate_command_sequence(scene.to_command_sequence()) == []


def test_instrument_bubble_requires_tag() -> None:
    with pytest.raises(ValueError, match="tag"):
        InstrumentBubbleComponent(id="PI101")


def test_instrument_bubble_ports_exist() -> None:
    component = InstrumentBubbleComponent(id="PI101", tag="PI-101", center=[0, 0], radius=80)

    assert set(component.ports()) == {"center", "bottom", "top", "left", "right"}
    assert component.ports()["top"] == [0.0, 80.0]


def test_instrument_bubble_render_validates_in_scene() -> None:
    _assert_component_scene_valid(
        InstrumentBubbleComponent(id="PI101", tag="PI-101", center=[0, 0])
    )


def test_controller_loop_render_validates() -> None:
    _assert_component_scene_valid(
        ControllerLoopComponent(
            id="LC_LOOP",
            instrument_tag="LT-101",
            controller_tag="LC-101",
            instrument_center=[0, 0],
            controller_center=[250, 0],
        )
    )


def test_controller_loop_ports_instrument_and_controller_exist() -> None:
    component = ControllerLoopComponent(
        id="LC_LOOP",
        instrument_tag="LT-101",
        controller_tag="LC-101",
        instrument_center=[0, 0],
        controller_center=[250, 0],
    )

    assert component.ports() == {
        "instrument": [0.0, 0.0],
        "controller": [250.0, 0.0],
    }

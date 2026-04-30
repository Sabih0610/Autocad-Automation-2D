from __future__ import annotations

import pytest

from src.framework.commands.schema import validate_command_sequence
from src.framework.pid.components.annotations import (
    FlowArrowComponent,
    LabelComponent,
    LeaderLineComponent,
)
from src.framework.pid.components.scene import PIDComponentScene


def _assert_component_scene_valid(component) -> None:
    scene = PIDComponentScene(title="Annotation Test", components=[component])
    assert validate_command_sequence(scene.to_command_sequence()) == []


def test_label_requires_text() -> None:
    with pytest.raises(ValueError, match="text must be"):
        LabelComponent(id="L1")


def test_label_render_validates() -> None:
    _assert_component_scene_valid(LabelComponent(id="L1", text="Vapor Outlet", center=[0, 0]))


@pytest.mark.parametrize("direction", ["RIGHT", "LEFT", "UP", "DOWN"])
def test_flow_arrow_supports_all_directions(direction: str) -> None:
    _assert_component_scene_valid(
        FlowArrowComponent(id=f"FA_{direction}", center=[0, 0], direction=direction)
    )


def test_invalid_flow_arrow_direction_raises_value_error() -> None:
    with pytest.raises(ValueError, match="direction must be"):
        FlowArrowComponent(id="FA1", direction="DIAGONAL")


def test_leader_line_render_with_text_validates() -> None:
    _assert_component_scene_valid(
        LeaderLineComponent(
            id="LL1",
            points=[[0, 0], [100, 100]],
            text="Note",
            text_position=[120, 120],
        )
    )


def test_leader_line_with_fewer_than_two_points_raises_value_error() -> None:
    with pytest.raises(ValueError, match="at least two points"):
        LeaderLineComponent(id="LL1", points=[[0, 0]])

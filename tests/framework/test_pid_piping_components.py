from __future__ import annotations

import pytest

from src.framework.commands.schema import validate_command_sequence
from src.framework.pid.components.piping import PipeRunComponent, SignalLineComponent
from src.framework.pid.components.scene import PIDComponentScene


def _assert_component_scene_valid(component) -> None:
    scene = PIDComponentScene(title="Piping Test", components=[component])
    assert validate_command_sequence(scene.to_command_sequence()) == []


def test_pipe_run_normalizes_points() -> None:
    component = PipeRunComponent(id="P1", points=[(0, 0, 0), [100, 0]])

    assert component.points == [[0.0, 0.0], [100.0, 0.0]]


def test_pipe_run_ports_start_and_end_are_correct() -> None:
    component = PipeRunComponent(id="P1", points=[[0, 0], [100, 0], [100, 50]])

    assert component.ports() == {
        "start": [0.0, 0.0],
        "end": [100.0, 50.0],
    }


def test_pipe_run_render_with_label_validates() -> None:
    _assert_component_scene_valid(
        PipeRunComponent(
            id="P1",
            points=[[0, 0], [100, 0]],
            label="Inlet",
            label_position=[0, 120],
        )
    )


def test_pipe_run_render_with_flow_arrow_validates() -> None:
    _assert_component_scene_valid(
        PipeRunComponent(
            id="P1",
            points=[[0, 0], [100, 0]],
            flow_direction="RIGHT",
            flow_arrow_position=[50, 0],
        )
    )


def test_pipe_run_with_fewer_than_two_points_raises_value_error() -> None:
    with pytest.raises(ValueError, match="at least two points"):
        PipeRunComponent(id="P1", points=[[0, 0]])


def test_signal_line_render_validates() -> None:
    _assert_component_scene_valid(
        SignalLineComponent(id="S1", points=[[0, 0], [100, 100], [200, 100]])
    )

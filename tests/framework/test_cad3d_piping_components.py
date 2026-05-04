from __future__ import annotations

import pytest

from src.framework.cad3d.components.piping import PipeRun3DComponent, vector_between_points
from src.framework.cad3d.components.scene import CAD3DComponentScene
from src.framework.cad3d.scene_schema import validate_cad3d_scene


def test_pipe_run_normalizes_points() -> None:
    pipe = PipeRun3DComponent(id="P1", points=[[0, 0], [100, 0, 50]])

    assert pipe.points == [[0.0, 0.0, 0.0], [100.0, 0.0, 50.0]]


def test_pipe_run_ports_include_start_end() -> None:
    ports = PipeRun3DComponent(id="P1", points=[[0, 0, 0], [100, 0, 0]]).ports()

    assert {"start", "end"}.issubset(ports)
    assert ports["start"]["direction"] == [-100.0, 0.0, 0.0]
    assert ports["end"]["direction"] == [100.0, 0.0, 0.0]


def test_pipe_run_scene_component_validates() -> None:
    scene = CAD3DComponentScene(title="Pipe Test")
    scene.add(PipeRun3DComponent(id="P1", points=[[0, 0, 0], [100, 0, 0]], diameter=50))

    assert validate_cad3d_scene(scene.to_scene_data()) == []


def test_pipe_run_with_fewer_than_two_points_raises_value_error() -> None:
    with pytest.raises(ValueError):
        PipeRun3DComponent(id="P1", points=[[0, 0, 0]])


def test_pipe_run_negative_diameter_raises_value_error() -> None:
    with pytest.raises(ValueError):
        PipeRun3DComponent(id="P1", points=[[0, 0, 0], [100, 0, 0]], diameter=-1)


def test_vector_between_points_works() -> None:
    assert vector_between_points([1, 2, 3], [4, 6, 8]) == [3.0, 4.0, 5.0]

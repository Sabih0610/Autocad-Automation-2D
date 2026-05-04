from __future__ import annotations

import pytest

from src.framework.cad3d.scene_examples import (
    available_cad3d_examples,
    get_cad3d_example,
    simple_3d_equipment_layout_scene,
)
from src.framework.cad3d.scene_schema import validate_cad3d_scene


def _component_ids(scene: dict) -> set[str]:
    return {component["id"] for component in scene["components"]}


def _component_types(scene: dict) -> set[str]:
    return {component["component_type"] for component in scene["components"]}


def test_simple_3d_equipment_layout_scene_validates() -> None:
    assert validate_cad3d_scene(simple_3d_equipment_layout_scene()) == []


def test_example_contains_vertical_tank_t101() -> None:
    assert "T101" in _component_ids(simple_3d_equipment_layout_scene())


def test_example_contains_horizontal_vessel_v201() -> None:
    assert "V201" in _component_ids(simple_3d_equipment_layout_scene())


def test_example_contains_pump_p101() -> None:
    assert "P101" in _component_ids(simple_3d_equipment_layout_scene())


def test_example_contains_pipe_run() -> None:
    assert "pipe_run_3d" in _component_types(simple_3d_equipment_layout_scene())


def test_available_cad3d_examples_includes_simple_equipment_layout() -> None:
    assert "simple_equipment_layout" in available_cad3d_examples()


def test_get_cad3d_example_validates() -> None:
    assert validate_cad3d_scene(get_cad3d_example("simple_equipment_layout")) == []


def test_get_cad3d_example_unknown_name_raises_value_error() -> None:
    with pytest.raises(ValueError):
        get_cad3d_example("unknown")

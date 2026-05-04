from __future__ import annotations

import pytest

from src.framework.cad3d.component_examples import (
    available_cad3d_component_examples,
    extended_3d_process_unit_scene,
    extended_3d_process_unit_scene_data,
    get_cad3d_component_example,
    routed_tank_pump_separator_scene_data,
    simple_3d_component_layout_scene,
    simple_3d_component_layout_scene_data,
)
from src.framework.cad3d.components.scene import CAD3DComponentScene
from src.framework.cad3d.routing import expand_pipe_connections
from src.framework.cad3d.scene_schema import validate_cad3d_scene


def _component_types(scene_data: dict) -> set[str]:
    return {component["component_type"] for component in scene_data["components"]}


def test_simple_3d_component_layout_scene_returns_scene() -> None:
    assert isinstance(simple_3d_component_layout_scene(), CAD3DComponentScene)


def test_simple_3d_component_layout_scene_has_at_least_seven_components() -> None:
    assert len(simple_3d_component_layout_scene().components) >= 7


def test_simple_3d_component_layout_scene_ports_include_expected_keys() -> None:
    ports = simple_3d_component_layout_scene().all_ports()

    assert "T101.bottom" in ports
    assert "P101.suction" in ports
    assert "P101.discharge" in ports
    assert "V201.end_a" in ports or "V201.end_b" in ports


def test_simple_3d_component_layout_scene_data_validates() -> None:
    assert validate_cad3d_scene(simple_3d_component_layout_scene_data()) == []


def test_scene_data_includes_expected_component_types() -> None:
    types = _component_types(simple_3d_component_layout_scene_data())

    assert "vertical_tank_3d" in types
    assert "pump_placeholder_3d" in types
    assert "horizontal_vessel_3d" in types
    assert "pipe_run_3d" in types
    assert "label_3d" in types


def test_available_examples_includes_simple_component_layout() -> None:
    assert "simple_component_layout" in available_cad3d_component_examples()


def test_get_known_example_works() -> None:
    assert isinstance(get_cad3d_component_example("simple_component_layout"), CAD3DComponentScene)


def test_extended_3d_process_unit_scene_returns_scene() -> None:
    assert isinstance(extended_3d_process_unit_scene(), CAD3DComponentScene)


def test_extended_3d_process_unit_scene_data_validates() -> None:
    assert validate_cad3d_scene(extended_3d_process_unit_scene_data()) == []


def test_extended_scene_contains_heat_exchanger() -> None:
    assert "heat_exchanger_3d" in _component_types(extended_3d_process_unit_scene_data())


def test_extended_scene_contains_valves() -> None:
    assert "valve_placeholder_3d" in _component_types(extended_3d_process_unit_scene_data())


def test_extended_scene_contains_flanges() -> None:
    assert "flange_3d" in _component_types(extended_3d_process_unit_scene_data())


def test_extended_scene_contains_supports() -> None:
    types = _component_types(extended_3d_process_unit_scene_data())

    assert {"support_leg_3d", "saddle_support_3d", "pipe_support_3d"}.issubset(types)


def test_available_examples_includes_extended_process_unit() -> None:
    assert "extended_process_unit" in available_cad3d_component_examples()


def test_get_extended_example_works() -> None:
    assert isinstance(get_cad3d_component_example("extended_process_unit"), CAD3DComponentScene)


def test_get_unknown_example_raises_value_error() -> None:
    with pytest.raises(ValueError):
        get_cad3d_component_example("unknown")


def test_routed_tank_pump_separator_scene_data_validates() -> None:
    assert validate_cad3d_scene(routed_tank_pump_separator_scene_data()) == []


def test_available_examples_includes_routed_tank_pump_separator() -> None:
    assert "routed_tank_pump_separator" in available_cad3d_component_examples()


def test_get_routed_tank_pump_separator_example_returns_scene() -> None:
    scene = get_cad3d_component_example("routed_tank_pump_separator")

    assert hasattr(scene, "to_scene_data")
    assert validate_cad3d_scene(scene.to_scene_data()) == []


def test_routed_example_contains_pipe_connection_3d() -> None:
    assert "pipe_connection_3d" in _component_types(routed_tank_pump_separator_scene_data())


def test_expand_routed_example_replaces_pipe_connections_with_pipe_runs() -> None:
    expanded = expand_pipe_connections(routed_tank_pump_separator_scene_data())
    types = _component_types(expanded)

    assert "pipe_connection_3d" not in types
    assert "pipe_run_3d" in types


def test_expanded_routed_example_validates() -> None:
    expanded = expand_pipe_connections(routed_tank_pump_separator_scene_data())

    assert validate_cad3d_scene(expanded) == []

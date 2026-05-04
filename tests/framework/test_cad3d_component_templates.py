from __future__ import annotations

import pytest

from src.framework.cad3d.component_templates import (
    available_cad3d_templates,
    choose_cad3d_template,
    dual_pump_skid_template_scene,
    extended_process_unit_template_scene,
    heat_exchanger_skid_template_scene,
    match_cad3d_template,
    tank_pump_separator_template_scene,
    vertical_scrubber_package_template_scene,
)
from src.framework.cad3d.routing import count_pipe_connections, expand_pipe_connections
from src.framework.cad3d.scene_schema import validate_cad3d_scene


def _component_types(scene: dict) -> set[str]:
    return {component["component_type"] for component in scene["components"]}


def _components_by_type(scene: dict, component_type: str) -> list[dict]:
    return [
        component
        for component in scene["components"]
        if component["component_type"] == component_type
    ]


@pytest.mark.parametrize(
    "template_fn",
    [
        tank_pump_separator_template_scene,
        extended_process_unit_template_scene,
        dual_pump_skid_template_scene,
        heat_exchanger_skid_template_scene,
        vertical_scrubber_package_template_scene,
    ],
)
def test_every_template_validates(template_fn) -> None:
    assert validate_cad3d_scene(template_fn()) == []


def test_available_cad3d_templates_includes_all_five() -> None:
    assert set(available_cad3d_templates()) == {
        "tank_pump_separator",
        "extended_process_unit",
        "dual_pump_skid",
        "heat_exchanger_skid",
        "vertical_scrubber_package",
    }


@pytest.mark.parametrize(
    ("prompt", "expected_template", "expected_confidence"),
    [
        ("Create a dual pump skid with suction header and discharge header", "dual_pump_skid", "high"),
        ("Create a heat exchanger skid with pump bypass inlet and outlet", "heat_exchanger_skid", "high"),
        (
            "Create a vertical scrubber package with gas inlet gas outlet vent and drain",
            "vertical_scrubber_package",
            "high",
        ),
        (
            "Create an extended process unit with tank pump heat exchanger separator valves flanges supports",
            "extended_process_unit",
            "high",
        ),
        ("Create a tank pump separator skid with connecting pipes", "tank_pump_separator", "high"),
        ("Create a simple industrial 3D package", "tank_pump_separator", "low"),
    ],
)
def test_match_cad3d_template(prompt: str, expected_template: str, expected_confidence: str) -> None:
    result = match_cad3d_template(prompt)

    assert result["template_name"] == expected_template
    assert result["confidence"] == expected_confidence
    assert result["reason"]


def test_choose_cad3d_template_returns_selected_valid_scene() -> None:
    template_name, scene = choose_cad3d_template(
        "Create a heat exchanger skid with pump bypass inlet and outlet"
    )

    assert template_name == "heat_exchanger_skid"
    assert validate_cad3d_scene(scene) == []


def test_dual_pump_template_has_at_least_two_pump_placeholders() -> None:
    scene = dual_pump_skid_template_scene()

    assert len(_components_by_type(scene, "pump_placeholder_3d")) >= 2


def test_heat_exchanger_skid_has_heat_exchanger() -> None:
    assert "heat_exchanger_3d" in _component_types(heat_exchanger_skid_template_scene())


def test_tank_pump_separator_template_contains_pipe_connection_3d() -> None:
    scene = tank_pump_separator_template_scene()

    assert "pipe_connection_3d" in _component_types(scene)
    assert count_pipe_connections(scene) >= 1


def test_extended_process_unit_template_contains_pipe_connection_3d() -> None:
    scene = extended_process_unit_template_scene()

    assert "pipe_connection_3d" in _component_types(scene)
    assert count_pipe_connections(scene) >= 1


def test_heat_exchanger_skid_template_contains_pipe_connection_3d() -> None:
    scene = heat_exchanger_skid_template_scene()

    assert "pipe_connection_3d" in _component_types(scene)
    assert count_pipe_connections(scene) >= 1


def test_every_template_expands_pipe_connections_to_valid_executable_scene() -> None:
    for template_fn in available_cad3d_templates().values():
        scene = template_fn()
        original_pipe_connections = count_pipe_connections(scene)
        expanded = expand_pipe_connections(scene)
        expanded_types = _component_types(expanded)

        assert validate_cad3d_scene(scene) == []
        assert validate_cad3d_scene(expanded) == []
        assert "pipe_connection_3d" not in expanded_types
        if original_pipe_connections:
            assert "pipe_run_3d" in expanded_types


def test_vertical_scrubber_has_vertical_tank_and_support_legs() -> None:
    types = _component_types(vertical_scrubber_package_template_scene())

    assert "vertical_tank_3d" in types
    assert "support_leg_3d" in types


def test_extended_process_unit_has_expanded_components() -> None:
    types = _component_types(extended_process_unit_template_scene())

    assert "heat_exchanger_3d" in types
    assert "valve_placeholder_3d" in types
    assert "flange_3d" in types
    assert {"support_leg_3d", "saddle_support_3d", "pipe_support_3d"}.issubset(types)

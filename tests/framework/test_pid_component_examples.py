from __future__ import annotations

import pytest

from src.framework.commands.schema import validate_command_sequence
from src.framework.pid.component_examples import (
    available_component_examples,
    horizontal_separator_component_scene,
    pump_tank_component_scene,
    render_component_example,
    render_horizontal_separator_component_pid,
    render_pump_tank_component_pid,
    render_vertical_vessel_component_pid,
    vertical_vessel_component_scene,
)
from src.framework.pid.components import PIDComponentScene


def _texts(sequence: dict) -> set[str]:
    return {
        command["text"]
        for command in sequence["commands"]
        if command["command"] == "TEXT"
    }


def _assert_valid(sequence: dict) -> None:
    assert validate_command_sequence(sequence) == []


def test_horizontal_separator_component_scene_returns_scene() -> None:
    assert isinstance(horizontal_separator_component_scene(), PIDComponentScene)


def test_horizontal_separator_command_sequence_validates() -> None:
    _assert_valid(render_horizontal_separator_component_pid())


def test_horizontal_separator_includes_expected_labels_and_instrument_tags() -> None:
    texts = _texts(render_horizontal_separator_component_pid())

    assert {
        "3 Phase Inlet",
        "Vapor Outlet",
        "Oil Outlet",
        "Water Outlet",
        "Drain",
        "Vent",
        "Demister Pad",
        "Weir",
        "Vortex Breaker",
        "PT-201",
        "PI-201",
        "LT-201",
        "LC-201",
    } <= texts


def test_vertical_vessel_component_scene_returns_scene() -> None:
    assert isinstance(vertical_vessel_component_scene(), PIDComponentScene)


def test_vertical_vessel_command_sequence_validates() -> None:
    _assert_valid(render_vertical_vessel_component_pid())


def test_vertical_vessel_includes_expected_labels_and_instrument_tags() -> None:
    texts = _texts(render_vertical_vessel_component_pid())

    assert {
        "Feed Inlet",
        "Vapor Outlet",
        "Liquid Outlet",
        "Level Control",
        "Temperature",
        "PT-301",
        "LT-301",
        "LC-301",
        "TI-301",
    } <= texts


def test_pump_tank_component_scene_returns_scene() -> None:
    assert isinstance(pump_tank_component_scene(), PIDComponentScene)


def test_pump_tank_command_sequence_validates() -> None:
    _assert_valid(render_pump_tank_component_pid())


def test_pump_tank_includes_expected_labels_and_instrument_tags() -> None:
    texts = _texts(render_pump_tank_component_pid())

    assert {
        "Tank T-101",
        "Pump P-101",
        "Suction",
        "Discharge",
        "PI-101",
        "FI-101",
    } <= texts


def test_available_component_examples_includes_expected_examples() -> None:
    examples = available_component_examples()

    assert {"horizontal_separator", "vertical_vessel", "pump_tank"} <= set(examples)


@pytest.mark.parametrize("name", ["horizontal_separator", "vertical_vessel", "pump_tank"])
def test_render_component_example_validates(name: str) -> None:
    _assert_valid(render_component_example(name))


def test_unknown_component_example_name_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unknown component example"):
        render_component_example("unknown")


def test_every_example_has_at_least_eight_components() -> None:
    for builder in available_component_examples().values():
        assert len(builder().components) >= 8


def test_every_rendered_example_has_more_than_twenty_five_commands() -> None:
    for name in available_component_examples():
        assert len(render_component_example(name)["commands"]) > 25


def test_component_scene_summaries_include_title() -> None:
    for builder in available_component_examples().values():
        scene = builder()
        assert scene.title in scene.summary()

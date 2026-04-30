from __future__ import annotations

import pytest

from src.framework.commands.schema import validate_command_sequence
from src.framework.pid.symbols import (
    PID_LAYER_EQUIPMENT,
    control_valve_commands,
    flow_arrow_commands,
    gate_valve_commands,
    horizontal_vessel_commands,
    instrument_bubble_commands,
    pid_standard_layers,
    pipe_line_commands,
    signal_line_commands,
    text_label_commands,
    vertical_vessel_commands,
    wrap_commands_as_sequence,
)


def _assert_valid(commands: list[dict]) -> None:
    assert validate_command_sequence(wrap_commands_as_sequence(commands)) == []


def test_pid_standard_layers_returns_layer_commands() -> None:
    commands = pid_standard_layers()

    assert commands
    assert all(command["command"] == "LAYER" for command in commands)
    assert {command["layer_name"] for command in commands} >= {
        "PID_EQUIPMENT",
        "PID_PIPING",
        "PID_VALVES",
        "PID_INSTRUMENTS",
        "PID_TEXT",
        "PID_SIGNAL",
        "PID_FLOW",
    }
    _assert_valid(commands)


def test_pipe_line_commands_returns_valid_polyline() -> None:
    commands = pipe_line_commands([[0, 0], [100, 0], [100, 50]])

    assert commands == [
        {
            "command": "POLYLINE",
            "points": [[0.0, 0.0], [100.0, 0.0], [100.0, 50.0]],
            "closed": False,
            "layer": "PID_PIPING",
        }
    ]
    _assert_valid(commands)


def test_horizontal_vessel_commands_returns_valid_sequence() -> None:
    commands = horizontal_vessel_commands(
        center=[0, 0],
        length=1600,
        diameter=500,
        tag="V-101",
    )

    assert any(command["command"] == "ARC" for command in commands)
    assert any(command.get("text") == "V-101" for command in commands)
    _assert_valid(commands)


def test_horizontal_vessel_tag_height_is_reasonable() -> None:
    commands = horizontal_vessel_commands(
        center=[0, 0],
        length=2600,
        diameter=700,
        tag="V-101",
    )
    tag_command = next(command for command in commands if command.get("text") == "V-101")

    assert 60 <= tag_command["height"] <= 120
    assert tag_command["position"][1] > 0


def test_vertical_vessel_commands_returns_valid_sequence() -> None:
    commands = vertical_vessel_commands(
        center=[0, 0],
        height=1400,
        diameter=500,
        tag="V-201",
    )

    assert any(command["command"] == "ARC" for command in commands)
    assert any(command.get("text") == "V-201" for command in commands)
    _assert_valid(commands)


def test_gate_valve_commands_works_for_horizontal_orientation() -> None:
    commands = gate_valve_commands(center=[0, 0], orientation="H")

    assert len(commands) >= 5
    assert {command["command"] for command in commands} <= {"LINE", "POLYLINE"}
    assert any(command["command"] == "POLYLINE" for command in commands)
    _assert_valid(commands)


def test_gate_valve_commands_works_for_vertical_orientation() -> None:
    commands = gate_valve_commands(center=[0, 0], orientation="V")

    assert len(commands) >= 5
    assert {command["command"] for command in commands} <= {"LINE", "POLYLINE"}
    assert any(command["command"] == "POLYLINE" for command in commands)
    _assert_valid(commands)


def test_control_valve_commands_returns_valid_commands() -> None:
    commands = control_valve_commands(center=[0, 0], orientation="H")

    assert any(command["command"] == "CIRCLE" for command in commands)
    assert any(command["command"] == "LINE" for command in commands)
    _assert_valid(commands)


def test_instrument_bubble_commands_returns_circle_line_and_text() -> None:
    commands = instrument_bubble_commands(center=[0, 0], tag="PI-101")
    command_types = {command["command"] for command in commands}
    text_command = next(command for command in commands if command["command"] == "TEXT")

    assert {"CIRCLE", "LINE", "TEXT"} <= command_types
    assert text_command["text"] == "PI-101"
    assert text_command["height"] <= 60
    _assert_valid(commands)


def test_signal_line_commands_returns_valid_commands() -> None:
    commands = signal_line_commands([[0, 0], [100, 100], [200, 100]])

    assert commands[0]["command"] == "POLYLINE"
    _assert_valid(commands)


@pytest.mark.parametrize("direction", ["RIGHT", "LEFT", "UP", "DOWN"])
def test_flow_arrow_commands_works_for_all_directions(direction: str) -> None:
    commands = flow_arrow_commands(position=[0, 0], direction=direction)

    assert commands[0]["command"] == "POLYLINE"
    assert commands[0]["closed"] is True
    _assert_valid(commands)


def test_text_label_commands_validates_non_empty_text() -> None:
    commands = text_label_commands("3 Phase Inlet", [0, 0])

    assert commands[0]["command"] == "TEXT"
    assert commands[0]["text"] == "3 Phase Inlet"
    _assert_valid(commands)

    with pytest.raises(ValueError, match="text cannot be empty"):
        text_label_commands("", [0, 0])


def test_invalid_orientation_raises_value_error() -> None:
    with pytest.raises(ValueError, match="orientation must be"):
        gate_valve_commands(center=[0, 0], orientation="DIAGONAL")

    with pytest.raises(ValueError, match="orientation must be"):
        control_valve_commands(center=[0, 0], orientation="DIAGONAL")


def test_negative_size_radius_or_diameter_raises_value_error() -> None:
    with pytest.raises(ValueError, match="diameter must be positive"):
        horizontal_vessel_commands(center=[0, 0], length=1000, diameter=-500)

    with pytest.raises(ValueError, match="diameter must be positive"):
        vertical_vessel_commands(center=[0, 0], height=1000, diameter=-500)

    with pytest.raises(ValueError, match="size must be positive"):
        gate_valve_commands(center=[0, 0], size=-100)

    with pytest.raises(ValueError, match="radius must be positive"):
        instrument_bubble_commands(center=[0, 0], tag="PI-101", radius=-80)


def test_combined_mini_pid_validates_as_one_command_sequence() -> None:
    commands = []
    commands += pid_standard_layers()
    commands += horizontal_vessel_commands(
        center=[0, 0],
        length=1600,
        diameter=500,
        tag="V-101",
    )
    commands += pipe_line_commands([[-1400, 0], [-800, 0]])
    commands += pipe_line_commands([[800, 0], [1400, 0]])
    commands += gate_valve_commands(center=[-1000, 0], orientation="H")
    commands += gate_valve_commands(center=[1000, 0], orientation="H")
    commands += instrument_bubble_commands(center=[0, 600], tag="PI-101")
    commands += text_label_commands("3 Phase Inlet", [-1500, 150])

    sequence = wrap_commands_as_sequence(commands)

    assert validate_command_sequence(sequence) == []
    assert any(command.get("layer") == PID_LAYER_EQUIPMENT for command in commands)

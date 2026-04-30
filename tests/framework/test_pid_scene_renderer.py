from __future__ import annotations

import pytest

from src.framework.commands.schema import validate_command_sequence
from src.framework.pid.scene_renderer import (
    PIDSceneRenderError,
    example_horizontal_separator_pid_scene,
    render_example_horizontal_separator_pid,
    render_pid_scene_to_commands,
)
from src.framework.pid.scene_schema import is_valid_pid_scene


def _minimal_horizontal_scene() -> dict:
    return {
        "schema_version": "1.0",
        "title": "Minimal Horizontal",
        "drawing_type": "P&ID",
        "assumptions": [],
        "equipment": [
            {
                "id": "V101",
                "type": "horizontal_vessel",
                "tag": "V-101",
                "center": [0, 0],
                "length": 1200,
                "diameter": 400,
            }
        ],
        "pipes": [],
        "valves": [],
        "instruments": [],
        "labels": [],
        "flow_arrows": [],
        "signal_lines": [],
    }


def _minimal_vertical_scene() -> dict:
    scene = _minimal_horizontal_scene()
    scene["title"] = "Minimal Vertical"
    scene["equipment"] = [
        {
            "id": "V201",
            "type": "vertical_vessel",
            "tag": "V-201",
            "center": [0, 0],
            "height": 1200,
            "diameter": 400,
        }
    ]
    return scene


def _rendered_commands(scene: dict) -> list[dict]:
    return render_pid_scene_to_commands(scene)["commands"]


def test_render_pid_scene_to_commands_rejects_invalid_scene() -> None:
    scene = _minimal_horizontal_scene()
    scene.pop("title")

    with pytest.raises(PIDSceneRenderError, match="Invalid P&ID scene"):
        render_pid_scene_to_commands(scene)


def test_minimal_horizontal_vessel_scene_renders_valid_command_sequence() -> None:
    sequence = render_pid_scene_to_commands(_minimal_horizontal_scene())

    assert validate_command_sequence(sequence) == []
    assert any(command.get("text") == "V-101" for command in sequence["commands"])


def test_minimal_vertical_vessel_scene_renders_valid_command_sequence() -> None:
    sequence = render_pid_scene_to_commands(_minimal_vertical_scene())

    assert validate_command_sequence(sequence) == []
    assert any(command.get("text") == "V-201" for command in sequence["commands"])


def test_scene_with_pipe_renders_polyline() -> None:
    scene = _minimal_horizontal_scene()
    scene["pipes"] = [{"id": "P1", "points": [[-500, 0], [500, 0]]}]

    commands = _rendered_commands(scene)

    assert any(command["command"] == "POLYLINE" for command in commands)


def test_scene_with_gate_valve_renders_valid_commands() -> None:
    scene = _minimal_horizontal_scene()
    scene["valves"] = [
        {
            "id": "XV1",
            "type": "gate_valve",
            "center": [0, 0],
            "orientation": "H",
        }
    ]

    sequence = render_pid_scene_to_commands(scene)

    assert validate_command_sequence(sequence) == []
    assert any(command["command"] == "LINE" for command in sequence["commands"])


def test_scene_with_control_valve_renders_valid_commands() -> None:
    scene = _minimal_horizontal_scene()
    scene["valves"] = [
        {
            "id": "CV1",
            "type": "control_valve",
            "center": [0, 0],
            "orientation": "H",
        }
    ]

    sequence = render_pid_scene_to_commands(scene)

    assert validate_command_sequence(sequence) == []
    assert any(command["command"] == "CIRCLE" for command in sequence["commands"])


def test_scene_with_instrument_bubble_renders_circle_and_text() -> None:
    scene = _minimal_horizontal_scene()
    scene["instruments"] = [
        {"id": "PI101", "tag": "PI-101", "center": [0, 600]}
    ]

    commands = _rendered_commands(scene)

    assert any(command["command"] == "CIRCLE" for command in commands)
    assert any(command.get("text") == "PI-101" for command in commands)


def test_scene_with_signal_line_renders_valid_commands() -> None:
    scene = _minimal_horizontal_scene()
    scene["signal_lines"] = [{"points": [[0, 0], [100, 100]]}]

    sequence = render_pid_scene_to_commands(scene)

    assert validate_command_sequence(sequence) == []
    assert any(command["command"] == "POLYLINE" for command in sequence["commands"])


def test_scene_with_flow_arrow_renders_valid_commands() -> None:
    scene = _minimal_horizontal_scene()
    scene["flow_arrows"] = [{"position": [0, 0], "direction": "RIGHT"}]

    sequence = render_pid_scene_to_commands(scene)

    assert validate_command_sequence(sequence) == []
    assert any(command["command"] == "POLYLINE" and command.get("closed") for command in sequence["commands"])


def test_example_horizontal_separator_pid_scene_validates() -> None:
    assert is_valid_pid_scene(example_horizontal_separator_pid_scene()) is True


def test_render_example_horizontal_separator_pid_returns_valid_command_sequence() -> None:
    sequence = render_example_horizontal_separator_pid()

    assert validate_command_sequence(sequence) == []


def test_rendered_example_includes_expected_labels() -> None:
    sequence = render_example_horizontal_separator_pid()
    texts = {command.get("text") for command in sequence["commands"] if command["command"] == "TEXT"}

    assert "V-101" in texts
    assert "3 Phase Inlet" in texts
    assert "Vapor Outlet" in texts
    assert "Water Outlet" in texts
    assert "Oil Outlet" in texts


def test_rendered_example_has_enough_commands_for_mini_pid() -> None:
    sequence = render_example_horizontal_separator_pid()

    assert len(sequence["commands"]) > 40


def test_rendered_example_keeps_vessel_tag_text_reasonable() -> None:
    sequence = render_example_horizontal_separator_pid()
    v101_text = [
        command
        for command in sequence["commands"]
        if command["command"] == "TEXT" and command.get("text") == "V-101"
    ]

    assert v101_text
    assert all(command["height"] <= 140 for command in v101_text)


def test_rendered_example_contains_instrument_tags() -> None:
    sequence = render_example_horizontal_separator_pid()
    texts = {command.get("text") for command in sequence["commands"] if command["command"] == "TEXT"}

    assert {"PT-101", "PI-101", "LT-101", "LC-101"} <= texts

from __future__ import annotations

from copy import deepcopy

from src.framework.commands.schema import (
    COMMAND_SCHEMA_VERSION,
    is_valid_command_sequence,
    validate_command_sequence,
)


def _base_sequence(commands: list[dict]) -> dict:
    return {
        "schema_version": COMMAND_SCHEMA_VERSION,
        "summary": "Test command sequence.",
        "estimated_drawing_type": "test",
        "assumptions": [],
        "commands": commands,
    }


def test_valid_simple_line_command_sequence_passes() -> None:
    sequence = _base_sequence(
        [
            {
                "command": "LINE",
                "from": [0, 0],
                "to": [100, 0],
                "layer": "OBJECT",
                "comment": "baseline",
            }
        ]
    )

    assert validate_command_sequence(sequence) == []


def test_valid_rectangle_made_from_four_line_commands_passes() -> None:
    sequence = _base_sequence(
        [
            {"command": "LINE", "from": [0, 0], "to": [100, 0]},
            {"command": "LINE", "from": [100, 0], "to": [100, 50]},
            {"command": "LINE", "from": [100, 50], "to": [0, 50]},
            {"command": "LINE", "from": [0, 50], "to": [0, 0]},
        ]
    )

    assert validate_command_sequence(sequence) == []


def test_missing_top_level_commands_fails() -> None:
    sequence = _base_sequence([{"command": "LINE", "from": [0, 0], "to": [1, 1]}])
    sequence.pop("commands")

    assert validate_command_sequence(sequence)


def test_empty_commands_array_fails() -> None:
    sequence = _base_sequence([])

    assert validate_command_sequence(sequence)


def test_unknown_command_type_fails() -> None:
    sequence = _base_sequence([{"command": "SPLINE", "points": [[0, 0], [1, 1]]}])

    assert validate_command_sequence(sequence)


def test_line_missing_to_fails() -> None:
    sequence = _base_sequence([{"command": "LINE", "from": [0, 0]}])

    assert validate_command_sequence(sequence)


def test_circle_with_negative_radius_fails() -> None:
    sequence = _base_sequence(
        [{"command": "CIRCLE", "center": [0, 0], "radius": -5}]
    )

    assert validate_command_sequence(sequence)


def test_text_with_empty_text_fails() -> None:
    sequence = _base_sequence(
        [{"command": "TEXT", "text": "", "position": [0, 0]}]
    )

    assert validate_command_sequence(sequence)


def test_polyline_with_only_one_point_fails() -> None:
    sequence = _base_sequence([{"command": "POLYLINE", "points": [[0, 0]]}])

    assert validate_command_sequence(sequence)


def test_layer_with_color_outside_1_to_255_fails() -> None:
    sequence = _base_sequence(
        [{"command": "LAYER", "layer_name": "OBJECT", "color": 256}]
    )

    assert validate_command_sequence(sequence)


def test_extra_unexpected_property_fails() -> None:
    sequence = _base_sequence(
        [{"command": "LINE", "from": [0, 0], "to": [1, 1], "width": 2}]
    )

    assert validate_command_sequence(sequence)


def test_is_valid_command_sequence_returns_true_false_correctly() -> None:
    valid_sequence = _base_sequence(
        [{"command": "LINE", "from": [0, 0], "to": [1, 1]}]
    )
    invalid_sequence = deepcopy(valid_sequence)
    invalid_sequence["commands"][0].pop("to")

    assert is_valid_command_sequence(valid_sequence) is True
    assert is_valid_command_sequence(invalid_sequence) is False

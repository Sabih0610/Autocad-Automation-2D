from __future__ import annotations

from copy import deepcopy

from src.framework.pid.scene_schema import (
    PID_SCENE_SCHEMA_VERSION,
    is_valid_pid_scene,
    validate_pid_scene,
)


def _minimal_horizontal_scene() -> dict:
    return {
        "schema_version": PID_SCENE_SCHEMA_VERSION,
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


def test_valid_minimal_horizontal_vessel_scene_passes() -> None:
    assert validate_pid_scene(_minimal_horizontal_scene()) == []


def test_valid_minimal_vertical_vessel_scene_passes() -> None:
    assert validate_pid_scene(_minimal_vertical_scene()) == []


def test_missing_title_fails() -> None:
    scene = _minimal_horizontal_scene()
    scene.pop("title")

    assert validate_pid_scene(scene)


def test_wrong_schema_version_fails() -> None:
    scene = _minimal_horizontal_scene()
    scene["schema_version"] = "2.0"

    assert validate_pid_scene(scene)


def test_horizontal_vessel_without_length_fails() -> None:
    scene = _minimal_horizontal_scene()
    scene["equipment"][0].pop("length")

    assert validate_pid_scene(scene)


def test_vertical_vessel_without_height_fails() -> None:
    scene = _minimal_vertical_scene()
    scene["equipment"][0].pop("height")

    assert validate_pid_scene(scene)


def test_pipe_with_fewer_than_two_points_fails() -> None:
    scene = _minimal_horizontal_scene()
    scene["pipes"] = [{"id": "P1", "points": [[0, 0]]}]

    assert validate_pid_scene(scene)


def test_invalid_valve_orientation_fails() -> None:
    scene = _minimal_horizontal_scene()
    scene["valves"] = [
        {
            "id": "XV1",
            "type": "gate_valve",
            "center": [0, 0],
            "orientation": "DIAGONAL",
        }
    ]

    assert validate_pid_scene(scene)


def test_invalid_flow_arrow_direction_fails() -> None:
    scene = _minimal_horizontal_scene()
    scene["flow_arrows"] = [{"position": [0, 0], "direction": "NORTHEAST"}]

    assert validate_pid_scene(scene)


def test_extra_top_level_property_fails() -> None:
    scene = _minimal_horizontal_scene()
    scene["extra"] = True

    assert validate_pid_scene(scene)


def test_is_valid_pid_scene_returns_true_false_correctly() -> None:
    valid_scene = _minimal_horizontal_scene()
    invalid_scene = deepcopy(valid_scene)
    invalid_scene["equipment"][0].pop("diameter")

    assert is_valid_pid_scene(valid_scene) is True
    assert is_valid_pid_scene(invalid_scene) is False

from __future__ import annotations

from copy import deepcopy

from src.framework.pid.component_schema import (
    is_valid_pid_component_scene_data,
    validate_pid_component_scene_data,
)


VALID_COMPONENT_SCENE = {
    "schema_version": "1.0",
    "title": "Test Component P&ID",
    "drawing_type": "P&ID",
    "assumptions": ["Test scene."],
    "components": [
        {
            "component_type": "horizontal_vessel",
            "id": "V201",
            "tag": "V-201",
            "center": [0, 0],
            "length": 3200,
            "diameter": 800,
        },
        {
            "component_type": "pipe_run",
            "id": "P_IN",
            "points": [[-2600, 0], [-1600, 0]],
            "label": "3 Phase Inlet",
            "flow_direction": "RIGHT",
        },
        {
            "component_type": "gate_valve",
            "id": "XV_IN",
            "center": [-2100, 0],
            "orientation": "H",
        },
        {
            "component_type": "instrument_bubble",
            "id": "PI201",
            "tag": "PI-201",
            "center": [0, 700],
        },
        {
            "component_type": "label",
            "id": "LBL1",
            "text": "Test Label",
            "center": [0, 1000],
        },
    ],
}


def test_valid_component_scene_passes() -> None:
    assert validate_pid_component_scene_data(VALID_COMPONENT_SCENE) == []


def test_missing_title_fails() -> None:
    data = deepcopy(VALID_COMPONENT_SCENE)
    data.pop("title")

    assert validate_pid_component_scene_data(data)


def test_empty_components_fails() -> None:
    data = deepcopy(VALID_COMPONENT_SCENE)
    data["components"] = []

    assert validate_pid_component_scene_data(data)


def test_unknown_component_type_fails() -> None:
    data = deepcopy(VALID_COMPONENT_SCENE)
    data["components"][0]["component_type"] = "pump"

    assert validate_pid_component_scene_data(data)


def test_horizontal_vessel_missing_length_fails() -> None:
    data = deepcopy(VALID_COMPONENT_SCENE)
    data["components"][0].pop("length")

    assert validate_pid_component_scene_data(data)


def test_vertical_vessel_missing_height_fails() -> None:
    data = deepcopy(VALID_COMPONENT_SCENE)
    data["components"] = [
        {
            "component_type": "vertical_vessel",
            "id": "V301",
            "tag": "V-301",
            "center": [0, 0],
            "diameter": 700,
        }
    ]

    assert validate_pid_component_scene_data(data)


def test_pipe_run_with_fewer_than_two_points_fails() -> None:
    data = deepcopy(VALID_COMPONENT_SCENE)
    data["components"][1]["points"] = [[0, 0]]

    assert validate_pid_component_scene_data(data)


def test_valve_invalid_orientation_fails() -> None:
    data = deepcopy(VALID_COMPONENT_SCENE)
    data["components"][2]["orientation"] = "DIAGONAL"

    assert validate_pid_component_scene_data(data)


def test_flow_arrow_invalid_direction_fails() -> None:
    data = deepcopy(VALID_COMPONENT_SCENE)
    data["components"] = [
        {
            "component_type": "flow_arrow",
            "id": "FA1",
            "center": [0, 0],
            "direction": "DIAGONAL",
        }
    ]

    assert validate_pid_component_scene_data(data)


def test_instrument_bubble_missing_tag_fails() -> None:
    data = deepcopy(VALID_COMPONENT_SCENE)
    data["components"][3].pop("tag")

    assert validate_pid_component_scene_data(data)


def test_label_missing_text_fails() -> None:
    data = deepcopy(VALID_COMPONENT_SCENE)
    data["components"][4].pop("text")

    assert validate_pid_component_scene_data(data)


def test_extra_top_level_property_fails() -> None:
    data = deepcopy(VALID_COMPONENT_SCENE)
    data["extra"] = True

    assert validate_pid_component_scene_data(data)


def test_is_valid_pid_component_scene_data_returns_true_false() -> None:
    assert is_valid_pid_component_scene_data(VALID_COMPONENT_SCENE) is True

    data = deepcopy(VALID_COMPONENT_SCENE)
    data["components"] = []
    assert is_valid_pid_component_scene_data(data) is False


def test_every_supported_component_type_can_appear_in_valid_scene() -> None:
    data = deepcopy(VALID_COMPONENT_SCENE)
    data["components"] = [
        {
            "component_type": "horizontal_vessel",
            "id": "V201",
            "tag": "V-201",
            "center": [0, 0],
            "length": 3200,
            "diameter": 800,
        },
        {
            "component_type": "vertical_vessel",
            "id": "V301",
            "tag": "V-301",
            "center": [1000, 0],
            "height": 1800,
            "diameter": 700,
        },
        {
            "component_type": "pipe_run",
            "id": "P1",
            "points": [[0, 0], [100, 0]],
        },
        {
            "component_type": "signal_line",
            "id": "S1",
            "points": [[0, 0], [100, 100]],
        },
        {
            "component_type": "gate_valve",
            "id": "XV1",
            "center": [0, 0],
            "orientation": "H",
        },
        {
            "component_type": "control_valve",
            "id": "LV1",
            "center": [200, 0],
            "orientation": "H",
        },
        {
            "component_type": "instrument_bubble",
            "id": "PI1",
            "tag": "PI-101",
            "center": [0, 300],
        },
        {
            "component_type": "controller_loop",
            "id": "LC1",
            "instrument_tag": "LT-101",
            "controller_tag": "LC-101",
            "instrument_center": [0, 400],
            "controller_center": [300, 400],
        },
        {
            "component_type": "label",
            "id": "LBL1",
            "text": "Label",
            "center": [0, 600],
        },
        {
            "component_type": "flow_arrow",
            "id": "FA1",
            "center": [0, 0],
            "direction": "RIGHT",
        },
        {
            "component_type": "leader_line",
            "id": "LL1",
            "points": [[0, 0], [100, 100]],
            "text": "Note",
        },
    ]

    assert validate_pid_component_scene_data(data) == []

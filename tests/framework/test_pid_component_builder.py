from __future__ import annotations

from copy import deepcopy

import pytest

from src.framework.commands.schema import validate_command_sequence
from src.framework.pid.component_builder import (
    PIDComponentBuildError,
    build_component_from_data,
    build_pid_component_scene,
    render_pid_component_scene_data,
)
from src.framework.pid.components import (
    ControlValveComponent,
    ControllerLoopComponent,
    FlowArrowComponent,
    GateValveComponent,
    HorizontalVesselComponent,
    InstrumentBubbleComponent,
    LabelComponent,
    LeaderLineComponent,
    PIDComponentScene,
    PipeRunComponent,
    VerticalVesselComponent,
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


def test_build_component_from_data_builds_horizontal_vessel() -> None:
    component = build_component_from_data(VALID_COMPONENT_SCENE["components"][0])

    assert isinstance(component, HorizontalVesselComponent)


def test_build_component_from_data_builds_vertical_vessel() -> None:
    component = build_component_from_data(
        {
            "component_type": "vertical_vessel",
            "id": "V301",
            "tag": "V-301",
            "center": [0, 0],
            "height": 1800,
            "diameter": 700,
        }
    )

    assert isinstance(component, VerticalVesselComponent)


def test_build_component_from_data_builds_pipe_run() -> None:
    component = build_component_from_data(VALID_COMPONENT_SCENE["components"][1])

    assert isinstance(component, PipeRunComponent)


def test_build_component_from_data_builds_gate_valve() -> None:
    component = build_component_from_data(VALID_COMPONENT_SCENE["components"][2])

    assert isinstance(component, GateValveComponent)


def test_build_component_from_data_builds_control_valve() -> None:
    component = build_component_from_data(
        {
            "component_type": "control_valve",
            "id": "LV1",
            "center": [0, 0],
            "orientation": "H",
        }
    )

    assert isinstance(component, ControlValveComponent)


def test_build_component_from_data_builds_instrument_bubble() -> None:
    component = build_component_from_data(VALID_COMPONENT_SCENE["components"][3])

    assert isinstance(component, InstrumentBubbleComponent)


def test_build_component_from_data_builds_controller_loop() -> None:
    component = build_component_from_data(
        {
            "component_type": "controller_loop",
            "id": "LC1",
            "instrument_tag": "LT-101",
            "controller_tag": "LC-101",
            "instrument_center": [0, 0],
            "controller_center": [300, 0],
        }
    )

    assert isinstance(component, ControllerLoopComponent)


def test_build_component_from_data_builds_label() -> None:
    component = build_component_from_data(VALID_COMPONENT_SCENE["components"][4])

    assert isinstance(component, LabelComponent)


def test_build_component_from_data_builds_flow_arrow() -> None:
    component = build_component_from_data(
        {
            "component_type": "flow_arrow",
            "id": "FA1",
            "center": [0, 0],
            "direction": "RIGHT",
        }
    )

    assert isinstance(component, FlowArrowComponent)


def test_build_component_from_data_builds_leader_line() -> None:
    component = build_component_from_data(
        {
            "component_type": "leader_line",
            "id": "LL1",
            "points": [[0, 0], [100, 100]],
            "text": "Note",
        }
    )

    assert isinstance(component, LeaderLineComponent)


def test_unsupported_component_type_raises_build_error() -> None:
    with pytest.raises(PIDComponentBuildError, match="Unsupported component type"):
        build_component_from_data({"component_type": "pump", "id": "P1"})


def test_build_pid_component_scene_returns_scene() -> None:
    scene = build_pid_component_scene(VALID_COMPONENT_SCENE)

    assert isinstance(scene, PIDComponentScene)


def test_built_scene_has_expected_component_count() -> None:
    scene = build_pid_component_scene(VALID_COMPONENT_SCENE)

    assert len(scene.components) == len(VALID_COMPONENT_SCENE["components"])


def test_built_scene_all_ports_includes_vessel_ports() -> None:
    scene = build_pid_component_scene(VALID_COMPONENT_SCENE)

    assert "V201.inlet_left" in scene.all_ports()


def test_render_pid_component_scene_data_returns_valid_command_sequence() -> None:
    sequence = render_pid_component_scene_data(VALID_COMPONENT_SCENE)

    assert validate_command_sequence(sequence) == []


def test_invalid_scene_raises_build_error() -> None:
    data = deepcopy(VALID_COMPONENT_SCENE)
    data["components"] = []

    with pytest.raises(PIDComponentBuildError, match="Invalid P&ID component scene"):
        build_pid_component_scene(data)


def test_duplicate_component_ids_raise_build_error() -> None:
    data = deepcopy(VALID_COMPONENT_SCENE)
    data["components"][1]["id"] = "V201"

    with pytest.raises(PIDComponentBuildError, match="duplicate component id"):
        build_pid_component_scene(data)

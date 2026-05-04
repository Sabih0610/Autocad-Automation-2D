from __future__ import annotations

from copy import deepcopy

from src.framework.cad3d.scene_schema import (
    CAD3D_SCENE_SCHEMA_VERSION,
    is_valid_cad3d_scene,
    validate_cad3d_scene,
)


VALID_SCENE = {
    "schema_version": CAD3D_SCENE_SCHEMA_VERSION,
    "title": "Test 3D Scene",
    "units": "mm",
    "assumptions": ["Test layout."],
    "components": [
        {
            "component_type": "vertical_tank_3d",
            "id": "T101",
            "tag": "T-101",
            "center": [0, 0, 900],
            "diameter": 900,
            "height": 1800,
        },
        {
            "component_type": "horizontal_vessel_3d",
            "id": "V201",
            "tag": "V-201",
            "center": [2000, 0, 600],
            "diameter": 700,
            "length": 1800,
            "orientation": "X",
        },
        {
            "component_type": "pipe_run_3d",
            "id": "P1",
            "points": [[0, 0, 500], [1000, 0, 500]],
            "diameter": 100,
        },
        {
            "component_type": "label_3d",
            "id": "LBL1",
            "text": "T-101",
            "position": [0, 500, 1900],
            "height": 150,
        },
    ],
}


def test_valid_simple_scene_passes() -> None:
    assert validate_cad3d_scene(VALID_SCENE) == []


def test_missing_title_fails() -> None:
    scene = deepcopy(VALID_SCENE)
    scene.pop("title")

    assert validate_cad3d_scene(scene)


def test_wrong_schema_version_fails() -> None:
    scene = deepcopy(VALID_SCENE)
    scene["schema_version"] = "2.0"

    assert validate_cad3d_scene(scene)


def test_vertical_tank_missing_height_fails() -> None:
    scene = deepcopy(VALID_SCENE)
    scene["components"][0].pop("height")

    assert validate_cad3d_scene(scene)


def test_horizontal_vessel_invalid_orientation_fails() -> None:
    scene = deepcopy(VALID_SCENE)
    scene["components"][1]["orientation"] = "Z"

    assert validate_cad3d_scene(scene)


def test_pipe_run_with_fewer_than_two_points_fails() -> None:
    scene = deepcopy(VALID_SCENE)
    scene["components"][2]["points"] = [[0, 0, 0]]

    assert validate_cad3d_scene(scene)


def test_pipe_run_visual_style_centerline_validates() -> None:
    scene = deepcopy(VALID_SCENE)
    scene["components"][2]["visual_style"] = "centerline"

    assert validate_cad3d_scene(scene) == []


def test_pipe_run_visual_style_solid_validates() -> None:
    scene = deepcopy(VALID_SCENE)
    scene["components"][2]["visual_style"] = "solid"

    assert validate_cad3d_scene(scene) == []


def test_pipe_run_visual_style_solid_with_centerline_validates() -> None:
    scene = deepcopy(VALID_SCENE)
    scene["components"][2]["visual_style"] = "solid_with_centerline"

    assert validate_cad3d_scene(scene) == []


def test_pipe_run_invalid_visual_style_fails() -> None:
    scene = deepcopy(VALID_SCENE)
    scene["components"][2]["visual_style"] = "mesh"

    assert validate_cad3d_scene(scene)


def test_pipe_run_draw_centerline_true_and_false_validate() -> None:
    scene = deepcopy(VALID_SCENE)
    scene["components"][2]["draw_centerline"] = True
    assert validate_cad3d_scene(scene) == []

    scene["components"][2]["draw_centerline"] = False
    assert validate_cad3d_scene(scene) == []


def test_negative_dimensions_fail() -> None:
    scene = deepcopy(VALID_SCENE)
    scene["components"][0]["diameter"] = -1

    assert validate_cad3d_scene(scene)


def test_unknown_component_type_fails() -> None:
    scene = deepcopy(VALID_SCENE)
    scene["components"][0]["component_type"] = "sphere_3d"

    assert validate_cad3d_scene(scene)


def _scene_with_component(component: dict) -> dict:
    scene = deepcopy(VALID_SCENE)
    scene["components"] = [component]
    return scene


def test_heat_exchanger_3d_validates() -> None:
    scene = _scene_with_component(
        {
            "component_type": "heat_exchanger_3d",
            "id": "E101",
            "tag": "E-101",
            "center": [0, 0, 600],
            "length": 2200,
            "diameter": 600,
            "orientation": "X",
        }
    )

    assert validate_cad3d_scene(scene) == []


def test_valve_placeholder_3d_validates() -> None:
    scene = _scene_with_component(
        {
            "component_type": "valve_placeholder_3d",
            "id": "XV101",
            "center": [0, 0, 500],
            "length": 400,
            "width": 300,
            "height": 300,
            "orientation": "X",
            "valve_type": "gate",
        }
    )

    assert validate_cad3d_scene(scene) == []


def test_nozzle_3d_validates() -> None:
    scene = _scene_with_component(
        {
            "component_type": "nozzle_3d",
            "id": "N101",
            "center": [0, 0, 500],
            "diameter": 150,
            "length": 400,
            "orientation": "Z",
        }
    )

    assert validate_cad3d_scene(scene) == []


def test_flange_3d_validates() -> None:
    scene = _scene_with_component(
        {
            "component_type": "flange_3d",
            "id": "FLG101",
            "center": [0, 0, 500],
            "diameter": 250,
            "thickness": 80,
            "orientation": "Y",
        }
    )

    assert validate_cad3d_scene(scene) == []


def test_support_leg_3d_validates() -> None:
    scene = _scene_with_component(
        {
            "component_type": "support_leg_3d",
            "id": "LEG101",
            "center": [0, 0, 500],
            "diameter": 120,
            "height": 1000,
        }
    )

    assert validate_cad3d_scene(scene) == []


def test_saddle_support_3d_validates() -> None:
    scene = _scene_with_component(
        {
            "component_type": "saddle_support_3d",
            "id": "SAD101",
            "center": [0, 0, 250],
            "length": 700,
            "width": 350,
            "height": 500,
        }
    )

    assert validate_cad3d_scene(scene) == []


def test_pipe_support_3d_validates() -> None:
    scene = _scene_with_component(
        {
            "component_type": "pipe_support_3d",
            "id": "PS101",
            "center": [0, 0, 400],
            "height": 800,
            "width": 300,
            "depth": 300,
        }
    )

    assert validate_cad3d_scene(scene) == []


def test_new_component_invalid_orientation_fails() -> None:
    scene = _scene_with_component(
        {
            "component_type": "nozzle_3d",
            "id": "N101",
            "center": [0, 0, 500],
            "diameter": 150,
            "length": 400,
            "orientation": "BAD",
        }
    )

    assert validate_cad3d_scene(scene)


def test_is_valid_cad3d_scene_returns_true_false_correctly() -> None:
    assert is_valid_cad3d_scene(VALID_SCENE) is True

    scene = deepcopy(VALID_SCENE)
    scene["components"] = []
    assert is_valid_cad3d_scene(scene) is False


def _valid_pipe_connection_component() -> dict:
    return {
        "component_type": "pipe_connection_3d",
        "id": "PIPE_T101_P101",
        "from_port": "T101.side_right",
        "to_port": "P101.suction",
        "diameter": 100,
    }


def test_pipe_connection_3d_validates() -> None:
    assert validate_cad3d_scene(_scene_with_component(_valid_pipe_connection_component())) == []


def test_pipe_connection_3d_missing_from_port_fails() -> None:
    component = _valid_pipe_connection_component()
    component.pop("from_port")

    assert validate_cad3d_scene(_scene_with_component(component))


def test_pipe_connection_3d_missing_to_port_fails() -> None:
    component = _valid_pipe_connection_component()
    component.pop("to_port")

    assert validate_cad3d_scene(_scene_with_component(component))


def test_pipe_connection_3d_negative_diameter_fails() -> None:
    component = _valid_pipe_connection_component()
    component["diameter"] = -100

    assert validate_cad3d_scene(_scene_with_component(component))


def test_pipe_connection_3d_orthogonal_routing_style_passes() -> None:
    component = _valid_pipe_connection_component()
    component["routing_style"] = "orthogonal"

    assert validate_cad3d_scene(_scene_with_component(component)) == []


def test_pipe_connection_3d_direct_routing_style_passes() -> None:
    component = _valid_pipe_connection_component()
    component["routing_style"] = "direct"

    assert validate_cad3d_scene(_scene_with_component(component)) == []


def test_pipe_connection_3d_invalid_routing_style_fails() -> None:
    component = _valid_pipe_connection_component()
    component["routing_style"] = "spline"

    assert validate_cad3d_scene(_scene_with_component(component))


def test_pipe_connection_3d_clearance_positive_passes_and_negative_fails() -> None:
    component = _valid_pipe_connection_component()
    component["clearance"] = 500
    assert validate_cad3d_scene(_scene_with_component(component)) == []

    component["clearance"] = -500
    assert validate_cad3d_scene(_scene_with_component(component))

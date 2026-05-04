from __future__ import annotations

from copy import deepcopy

import pytest

from src.framework.cad3d.routing import (
    CAD3DPortResolutionError,
    build_pipe_run_from_connection,
    component_ports,
    count_pipe_connections,
    dedupe_consecutive_points,
    direct_pipe_route_3d,
    expand_pipe_connections,
    normalize_port_reference,
    orthogonal_pipe_route_3d,
    resolve_port_reference,
)
from src.framework.cad3d.scene_schema import CAD3D_SCENE_SCHEMA_VERSION, validate_cad3d_scene


def _routing_scene() -> dict:
    return {
        "schema_version": CAD3D_SCENE_SCHEMA_VERSION,
        "title": "Routing Test Scene",
        "units": "mm",
        "assumptions": ["Routing test scene."],
        "components": [
            {
                "component_type": "vertical_tank_3d",
                "id": "T101",
                "tag": "T-101",
                "center": [0, 0, 1000],
                "diameter": 1000,
                "height": 2000,
            },
            {
                "component_type": "pump_placeholder_3d",
                "id": "P101",
                "tag": "P-101",
                "center": [2000, 500, 500],
                "length": 800,
                "width": 400,
                "height": 400,
            },
        ],
    }


def _scene_with_connection() -> dict:
    scene = _routing_scene()
    scene["components"].append(
        {
            "component_type": "pipe_connection_3d",
            "id": "PIPE_T101_P101",
            "from_port": "T101.side_right",
            "to_port": "P101.suction",
            "diameter": 100,
            "routing_style": "orthogonal",
            "clearance": 400,
        }
    )
    return scene


def test_normalize_port_reference_parses_valid_reference() -> None:
    assert normalize_port_reference(" T101.side_right ") == ("T101", "side_right")


@pytest.mark.parametrize("reference", ["", "T101", "T101.", ".side_right", "A.B.C"])
def test_normalize_port_reference_rejects_invalid_reference(reference: str) -> None:
    with pytest.raises(CAD3DPortResolutionError):
        normalize_port_reference(reference)


def test_component_ports_vertical_tank_include_expected_ports() -> None:
    ports = component_ports(_routing_scene()["components"][0])

    for port_name in ["top", "bottom", "side_left", "side_right", "inlet", "outlet", "drain", "vent"]:
        assert port_name in ports
    assert ports["side_right"]["position"] == [500.0, 0.0, 1000.0]
    assert ports["outlet"]["position"] == ports["side_right"]["position"]


def test_component_ports_horizontal_vessel_orientation_x_include_expected_ports() -> None:
    ports = component_ports(
        {
            "component_type": "horizontal_vessel_3d",
            "id": "V201",
            "tag": "V-201",
            "center": [0, 0, 500],
            "diameter": 600,
            "length": 2000,
            "orientation": "X",
        }
    )

    for port_name in ["end_a", "end_b", "inlet", "outlet", "top", "bottom"]:
        assert port_name in ports
    assert ports["end_a"]["position"] == [-1000.0, 0.0, 500.0]
    assert ports["end_b"]["position"] == [1000.0, 0.0, 500.0]


def test_component_ports_heat_exchanger_include_expected_ports() -> None:
    ports = component_ports(
        {
            "component_type": "heat_exchanger_3d",
            "id": "E101",
            "tag": "E-101",
            "center": [0, 0, 500],
            "length": 2000,
            "diameter": 500,
            "orientation": "X",
        }
    )

    assert {"inlet", "outlet"}.issubset(ports)


def test_component_ports_pump_placeholder_include_expected_ports() -> None:
    ports = component_ports(_routing_scene()["components"][1])

    for port_name in ["suction", "discharge", "inlet", "outlet"]:
        assert port_name in ports
    assert ports["suction"]["position"] == [1600.0, 500.0, 500.0]
    assert ports["discharge"]["position"] == [2400.0, 500.0, 500.0]


def test_resolve_port_reference_resolves_component_port() -> None:
    port = resolve_port_reference(_routing_scene(), "T101.side_right")

    assert port["position"] == [500.0, 0.0, 1000.0]
    assert port["direction"] == [1.0, 0.0, 0.0]


def test_resolve_port_reference_raises_for_missing_component() -> None:
    with pytest.raises(CAD3DPortResolutionError):
        resolve_port_reference(_routing_scene(), "MISSING.side_right")


def test_resolve_port_reference_raises_for_missing_port() -> None:
    with pytest.raises(CAD3DPortResolutionError):
        resolve_port_reference(_routing_scene(), "T101.not_a_port")


def test_direct_pipe_route_3d_returns_start_and_end() -> None:
    from_port = {"position": [0, 0, 0], "direction": [1, 0, 0]}
    to_port = {"position": [100, 200, 300], "direction": [-1, 0, 0]}

    assert direct_pipe_route_3d(from_port, to_port) == [[0.0, 0.0, 0.0], [100.0, 200.0, 300.0]]


def test_orthogonal_pipe_route_3d_returns_deterministic_non_duplicate_points() -> None:
    from_port = {"position": [0, 0, 0], "direction": [1, 0, 0]}
    to_port = {"position": [2000, 1000, 0], "direction": [-1, 0, 0]}

    points = orthogonal_pipe_route_3d(from_port, to_port, clearance=500, axis_order=["X", "Y", "Z"])

    assert points[0] == [0.0, 0.0, 0.0]
    assert points[-1] == [2000.0, 1000.0, 0.0]
    assert len(points) >= 3
    assert points == dedupe_consecutive_points(points)


def test_build_pipe_run_from_connection_returns_valid_pipe_run_3d() -> None:
    scene = _scene_with_connection()
    connection = scene["components"][-1]

    pipe_run = build_pipe_run_from_connection(connection, scene)
    expanded_scene = deepcopy(scene)
    expanded_scene["components"] = [pipe_run]

    assert pipe_run["component_type"] == "pipe_run_3d"
    assert pipe_run["id"] == "PIPE_T101_P101"
    assert len(pipe_run["points"]) >= 2
    assert pipe_run["metadata"]["generated_from"] == "pipe_connection_3d"
    assert validate_cad3d_scene(expanded_scene) == []


def test_expand_pipe_connections_replaces_connection_with_pipe_run() -> None:
    expanded = expand_pipe_connections(_scene_with_connection())

    component_types = [component["component_type"] for component in expanded["components"]]
    assert "pipe_connection_3d" not in component_types
    assert "pipe_run_3d" in component_types
    assert expanded["metadata"]["pipe_connections_expanded"] == 1


def test_expand_pipe_connections_validates_expanded_scene() -> None:
    assert validate_cad3d_scene(expand_pipe_connections(_scene_with_connection())) == []


def test_count_pipe_connections_returns_correct_count() -> None:
    scene = _scene_with_connection()
    scene["components"].append(
        {
            "component_type": "pipe_connection_3d",
            "id": "PIPE_2",
            "from_port": "P101.discharge",
            "to_port": "T101.inlet",
            "diameter": 75,
        }
    )

    assert count_pipe_connections(scene) == 2


def test_expand_pipe_connections_zero_connections_leaves_pipe_run_components_unchanged() -> None:
    scene = _routing_scene()
    scene["components"].append(
        {
            "component_type": "pipe_run_3d",
            "id": "P_EXISTING",
            "points": [[0, 0, 0], [500, 0, 0]],
            "diameter": 80,
        }
    )
    original_components = deepcopy(scene["components"])

    expanded = expand_pipe_connections(scene)

    assert expanded["components"] == original_components
    assert expanded["metadata"]["pipe_connections_expanded"] == 0

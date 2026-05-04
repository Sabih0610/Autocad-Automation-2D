"""Deterministic example 3D CAD scenes."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy


def simple_3d_equipment_layout_scene() -> dict:
    """Return a small 3D equipment layout using supported Phase 30.1 primitives."""
    return {
        "schema_version": "1.0",
        "title": "Simple 3D Equipment Layout",
        "units": "mm",
        "assumptions": [
            "Equipment is represented with deterministic AutoCAD primitive solids.",
            "Pipe runs are represented as 3D centerline placeholders in this phase.",
        ],
        "metadata": {
            "example_name": "simple_equipment_layout",
            "source": "deterministic_example",
        },
        "components": [
            {
                "component_type": "skid_base_3d",
                "id": "SKID101",
                "center": [1200, 0, -75],
                "length": 5200,
                "width": 1800,
                "height": 150,
            },
            {
                "component_type": "vertical_tank_3d",
                "id": "T101",
                "tag": "T-101",
                "center": [-1200, 0, 900],
                "diameter": 900,
                "height": 1800,
            },
            {
                "component_type": "pump_placeholder_3d",
                "id": "P101",
                "tag": "P-101",
                "center": [700, -350, 250],
                "length": 700,
                "width": 420,
                "height": 500,
            },
            {
                "component_type": "horizontal_vessel_3d",
                "id": "V201",
                "tag": "V-201",
                "center": [2500, 250, 650],
                "diameter": 700,
                "length": 1800,
                "orientation": "X",
            },
            {
                "component_type": "pipe_run_3d",
                "id": "P_TANK_PUMP",
                "tag": "Tank to pump suction",
                "points": [[-1200, -450, 450], [-300, -450, 450], [350, -350, 350]],
                "diameter": 120,
            },
            {
                "component_type": "pipe_run_3d",
                "id": "P_PUMP_VESSEL",
                "tag": "Pump discharge to vessel",
                "points": [[1050, -350, 420], [1700, -350, 520], [1700, 250, 650]],
                "diameter": 100,
            },
            {
                "component_type": "label_3d",
                "id": "LBL_T101",
                "text": "T-101",
                "position": [-1500, 650, 1950],
                "height": 180,
            },
            {
                "component_type": "label_3d",
                "id": "LBL_P101",
                "text": "P-101",
                "position": [450, -900, 750],
                "height": 160,
            },
            {
                "component_type": "label_3d",
                "id": "LBL_V201",
                "text": "V-201",
                "position": [2200, 850, 1150],
                "height": 180,
            },
        ],
    }


def available_cad3d_examples() -> dict[str, Callable[[], dict]]:
    return {
        "simple_equipment_layout": simple_3d_equipment_layout_scene,
    }


def get_cad3d_example(name: str) -> dict:
    examples = available_cad3d_examples()
    try:
        return deepcopy(examples[name]())
    except KeyError as exc:
        raise ValueError(f"Unknown CAD3D example: {name}") from exc

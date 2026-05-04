"""Reusable 3D component scene examples."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from src.framework.cad3d.components import (
    CAD3DComponentScene,
    Flange3DComponent,
    HeatExchanger3DComponent,
    HorizontalVessel3DComponent,
    Label3DComponent,
    PipeRun3DComponent,
    PipeSupport3DComponent,
    PumpPlaceholder3DComponent,
    SaddleSupport3DComponent,
    SkidBase3DComponent,
    SupportLeg3DComponent,
    ValvePlaceholder3DComponent,
    VerticalTank3DComponent,
)
from src.framework.cad3d.scene_schema import CAD3D_SCENE_SCHEMA_VERSION


@dataclass
class _CAD3DSceneDataExample:
    scene_data_factory: Callable[[], dict]

    def to_scene_data(self) -> dict:
        return deepcopy(self.scene_data_factory())


def simple_3d_component_layout_scene() -> CAD3DComponentScene:
    scene = CAD3DComponentScene(
        title="Simple 3D Component Equipment Layout",
        assumptions=[
            "Equipment is represented with reusable deterministic 3D components.",
            "Pipe runs are represented as 3D centerline placeholders in this phase.",
        ],
        metadata={
            "example_name": "simple_component_layout",
            "source": "deterministic_component_example",
        },
    )

    scene.add(SkidBase3DComponent(id="SKID101", center=[1200, 0, -75], length=5200, width=1800, height=150))
    scene.add(VerticalTank3DComponent(id="T101", tag="T-101", center=[-1200, 0, 900], diameter=900, height=1800))
    scene.add(PumpPlaceholder3DComponent(id="P101", tag="P-101", center=[700, -350, 250], length=700, width=420, height=500))
    scene.add(HorizontalVessel3DComponent(id="V201", tag="V-201", center=[2500, 250, 650], diameter=700, length=1800, orientation="X"))
    scene.add(
        PipeRun3DComponent(
            id="P_TANK_PUMP",
            tag="Tank to pump suction",
            points=[[-1200, -450, 450], [-300, -450, 450], [350, -350, 350]],
            diameter=120,
        )
    )
    scene.add(
        PipeRun3DComponent(
            id="P_PUMP_VESSEL",
            tag="Pump discharge to vessel",
            points=[[1050, -350, 420], [1700, -350, 520], [1700, 250, 650]],
            diameter=100,
        )
    )
    scene.add(Label3DComponent(id="LBL_T101", text="T-101", center=[-1500, 650, 1950], height=180))
    scene.add(Label3DComponent(id="LBL_P101", text="P-101", center=[450, -900, 750], height=160))
    scene.add(Label3DComponent(id="LBL_V201", text="V-201", center=[2200, 850, 1150], height=180))

    return scene


def simple_3d_component_layout_scene_data() -> dict:
    return simple_3d_component_layout_scene().to_scene_data()


def extended_3d_process_unit_scene() -> CAD3DComponentScene:
    scene = CAD3DComponentScene(
        title="Extended 3D Process Unit",
        assumptions=[
            "Equipment is represented with deterministic 3D CAD component placeholders.",
            "Valves, flanges, and supports are simplified but placed at useful schematic locations.",
            "Pipe runs are represented as 3D centerline placeholders in this phase.",
        ],
        metadata={
            "example_name": "extended_process_unit",
            "source": "deterministic_component_example",
        },
    )

    scene.add(SkidBase3DComponent(id="SKID201", center=[2200, 0, -100], length=8200, width=2600, height=200))
    scene.add(VerticalTank3DComponent(id="T101", tag="T-101", center=[-1800, -250, 1000], diameter=1000, height=2000))
    scene.add(PumpPlaceholder3DComponent(id="P101", tag="P-101", center=[200, -700, 300], length=800, width=450, height=500))
    scene.add(HeatExchanger3DComponent(id="E101", tag="E-101", center=[1850, -700, 700], length=1800, diameter=450, orientation="X"))
    scene.add(HorizontalVessel3DComponent(id="V201", tag="V-201", center=[4300, 350, 850], diameter=800, length=2200, orientation="X"))

    scene.add(PipeRun3DComponent(id="P_TANK_PUMP", points=[[-1800, -750, 450], [-700, -750, 450], [-200, -700, 350]], diameter=120))
    scene.add(PipeRun3DComponent(id="P_PUMP_EXCHANGER", points=[[600, -700, 420], [950, -700, 520], [950, -700, 700]], diameter=100))
    scene.add(PipeRun3DComponent(id="P_EXCHANGER_VESSEL", points=[[2750, -700, 700], [3350, -700, 700], [3350, 350, 850]], diameter=100))
    scene.add(PipeRun3DComponent(id="P_VESSEL_OUT", points=[[5400, 350, 850], [6200, 350, 850]], diameter=120))

    scene.add(ValvePlaceholder3DComponent(id="XV101", tag="XV-101", center=[-850, -750, 450], orientation="X", valve_type="gate"))
    scene.add(ValvePlaceholder3DComponent(id="CV101", tag="CV-101", center=[3180, -700, 700], orientation="X", valve_type="control"))
    scene.add(Flange3DComponent(id="FLG101", center=[950, -700, 700], diameter=260, thickness=80, orientation="X"))
    scene.add(Flange3DComponent(id="FLG102", center=[2750, -700, 700], diameter=260, thickness=80, orientation="X"))

    scene.add(SupportLeg3DComponent(id="LEG_T101_A", center=[-2100, -550, 350], diameter=100, height=700))
    scene.add(SupportLeg3DComponent(id="LEG_T101_B", center=[-1500, -550, 350], diameter=100, height=700))
    scene.add(SaddleSupport3DComponent(id="SAD_V201_A", center=[3750, 350, 250], length=500, width=450, height=500))
    scene.add(SaddleSupport3DComponent(id="SAD_V201_B", center=[4850, 350, 250], length=500, width=450, height=500))
    scene.add(PipeSupport3DComponent(id="PS101", center=[3350, -250, 350], height=700, width=260, depth=260))

    scene.add(Label3DComponent(id="LBL_T101", text="T-101", center=[-2150, 650, 2200], height=180))
    scene.add(Label3DComponent(id="LBL_P101", text="P-101", center=[-100, -1200, 850], height=160))
    scene.add(Label3DComponent(id="LBL_E101", text="E-101", center=[1500, -1200, 1200], height=160))
    scene.add(Label3DComponent(id="LBL_V201", text="V-201", center=[3900, 1050, 1350], height=180))

    return scene


def extended_3d_process_unit_scene_data() -> dict:
    return extended_3d_process_unit_scene().to_scene_data()


def routed_tank_pump_separator_scene_data() -> dict:
    return {
        "schema_version": CAD3D_SCENE_SCHEMA_VERSION,
        "title": "Routed Tank Pump Separator",
        "units": "mm",
        "assumptions": [
            "Pipe connections are resolved deterministically from component ports.",
            "Routed pipes are represented as executable 3D centerline pipe runs.",
        ],
        "metadata": {
            "example_name": "routed_tank_pump_separator",
            "source": "deterministic_component_example",
        },
        "components": [
            {
                "component_type": "skid_base_3d",
                "id": "SKID101",
                "center": [500, 0, -75],
                "length": 5200,
                "width": 1800,
                "height": 150,
            },
            {
                "component_type": "vertical_tank_3d",
                "id": "T101",
                "tag": "T-101",
                "center": [-1400, 0, 900],
                "diameter": 900,
                "height": 1800,
            },
            {
                "component_type": "pump_placeholder_3d",
                "id": "P101",
                "tag": "P-101",
                "center": [300, 0, 250],
                "length": 700,
                "width": 420,
                "height": 500,
            },
            {
                "component_type": "horizontal_vessel_3d",
                "id": "V201",
                "tag": "V-201",
                "center": [2200, 0, 650],
                "diameter": 700,
                "length": 1600,
                "orientation": "X",
            },
            {
                "component_type": "pipe_connection_3d",
                "id": "PIPE_T101_P101",
                "tag": "Tank to pump suction",
                "from_port": "T101.side_right",
                "to_port": "P101.suction",
                "diameter": 100,
                "routing_style": "orthogonal",
                "clearance": 400,
            },
            {
                "component_type": "pipe_connection_3d",
                "id": "PIPE_P101_V201",
                "tag": "Pump discharge to separator",
                "from_port": "P101.discharge",
                "to_port": "V201.end_a",
                "diameter": 100,
                "routing_style": "orthogonal",
                "clearance": 400,
            },
            {
                "component_type": "label_3d",
                "id": "LBL_T101",
                "text": "T-101",
                "position": [-1700, 650, 1950],
                "height": 180,
            },
            {
                "component_type": "label_3d",
                "id": "LBL_P101",
                "text": "P-101",
                "position": [0, -650, 750],
                "height": 160,
            },
            {
                "component_type": "label_3d",
                "id": "LBL_V201",
                "text": "V-201",
                "position": [1850, 650, 1150],
                "height": 180,
            },
        ],
    }


def _routed_tank_pump_separator_scene() -> _CAD3DSceneDataExample:
    return _CAD3DSceneDataExample(routed_tank_pump_separator_scene_data)


def available_cad3d_component_examples() -> dict[str, Callable[[], Any]]:
    return {
        "simple_component_layout": simple_3d_component_layout_scene,
        "extended_process_unit": extended_3d_process_unit_scene,
        "routed_tank_pump_separator": _routed_tank_pump_separator_scene,
    }


def get_cad3d_component_example(name: str) -> Any:
    examples = available_cad3d_component_examples()
    try:
        return examples[name]()
    except KeyError as exc:
        raise ValueError(f"Unknown CAD3D component example: {name}") from exc

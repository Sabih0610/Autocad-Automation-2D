"""Reusable component-based P&ID example scenes."""

from __future__ import annotations

from collections.abc import Callable

from src.framework.pid.components import (
    ControlValveComponent,
    ControllerLoopComponent,
    FlowArrowComponent,
    GateValveComponent,
    HorizontalVesselComponent,
    InstrumentBubbleComponent,
    LabelComponent,
    PIDComponentScene,
    PipeRunComponent,
    SignalLineComponent,
    VerticalVesselComponent,
)


def horizontal_separator_component_scene() -> PIDComponentScene:
    scene = PIDComponentScene(
        title="Horizontal Separator Component P&ID",
        assumptions=[
            "Component example uses schematic P&ID geometry.",
            "Internal vessel details are symbolic and not fabrication-grade.",
        ],
    )

    vessel = HorizontalVesselComponent(
        id="V201",
        tag="V-201",
        center=[0, 0],
        length=2800,
        diameter=760,
    )
    ports = vessel.ports()
    scene.add(vessel)

    scene.add(
        PipeRunComponent(
            id="P201_INLET",
            points=[[-3200, 0], ports["inlet_left"]],
            label="3 Phase Inlet",
            label_position=[-2850, 145],
            flow_direction="RIGHT",
            flow_arrow_position=[-2850, 0],
        )
    )
    scene.add(
        PipeRunComponent(
            id="P201_VAPOR",
            points=[ports["vapor_top"], [850, 920], [3000, 920]],
            label="Vapor Outlet",
            label_position=[2300, 1060],
            flow_direction="RIGHT",
            flow_arrow_position=[2760, 920],
        )
    )
    scene.add(
        PipeRunComponent(
            id="P201_OIL",
            points=[ports["oil_bottom_right"], [840, -1120], [3000, -1120]],
            label="Oil Outlet",
            label_position=[2180, -980],
            flow_direction="RIGHT",
            flow_arrow_position=[2740, -1120],
        )
    )
    scene.add(
        PipeRunComponent(
            id="P201_WATER",
            points=[ports["water_bottom_left"], [-840, -940], [-3000, -940]],
            label="Water Outlet",
            label_position=[-2860, -800],
            flow_direction="LEFT",
            flow_arrow_position=[-2740, -940],
        )
    )
    scene.add(
        PipeRunComponent(
            id="P201_DRAIN",
            points=[ports["bottom_center"], [0, -1450]],
            label="Drain",
            label_position=[130, -1360],
            flow_direction="DOWN",
            flow_arrow_position=[0, -1320],
        )
    )
    scene.add(
        PipeRunComponent(
            id="P201_VENT",
            points=[ports["top_center"], [0, 1320]],
            label="Vent",
            label_position=[120, 1220],
            flow_direction="UP",
            flow_arrow_position=[0, 1140],
        )
    )

    scene.add(GateValveComponent(id="XV201_IN", center=[-2150, 0], orientation="H"))
    scene.add(GateValveComponent(id="XV201_VAPOR", center=[1680, 920], orientation="H"))
    scene.add(GateValveComponent(id="XV201_WATER", center=[-1750, -940], orientation="H"))
    scene.add(GateValveComponent(id="XV201_DRAIN", center=[0, -1120], orientation="V"))
    scene.add(ControlValveComponent(id="LV201_OIL", center=[1900, -1120], orientation="H"))

    scene.add(InstrumentBubbleComponent(id="PT201", tag="PT-201", center=[-620, 1030]))
    scene.add(InstrumentBubbleComponent(id="PI201", tag="PI-201", center=[1220, 1190]))
    scene.add(
        ControllerLoopComponent(
            id="LC201_LOOP",
            instrument_tag="LT-201",
            controller_tag="LC-201",
            instrument_center=[1650, 250],
            controller_center=[2180, 250],
            signal_points=[[1650, 250], [2180, 250], [2180, -950], [1900, -1010]],
        )
    )
    scene.add(SignalLineComponent(id="SIG201_PT", points=[[-620, 945], [-620, 380]]))
    scene.add(SignalLineComponent(id="SIG201_PI", points=[[1220, 1105], [1220, 920]]))

    scene.add(LabelComponent(id="LBL201_DEMISTER", text="Demister Pad", center=[640, 320], height=55))
    scene.add(LabelComponent(id="LBL201_WEIR", text="Weir", center=[-260, -210], height=55))
    scene.add(LabelComponent(id="LBL201_VORTEX", text="Vortex Breaker", center=[300, -510], height=55))

    return scene


def render_horizontal_separator_component_pid() -> dict:
    return horizontal_separator_component_scene().to_command_sequence()


def vertical_vessel_component_scene() -> PIDComponentScene:
    scene = PIDComponentScene(
        title="Vertical Vessel Component P&ID",
        assumptions=["Component example uses a simplified vertical vessel schematic."],
    )

    vessel = VerticalVesselComponent(
        id="V301",
        tag="V-301",
        center=[0, 0],
        height=1900,
        diameter=720,
    )
    ports = vessel.ports()
    scene.add(vessel)

    scene.add(
        PipeRunComponent(
            id="P301_FEED",
            points=[[-2600, 0], ports["left"]],
            label="Feed Inlet",
            label_position=[-2380, 145],
            flow_direction="RIGHT",
            flow_arrow_position=[-2280, 0],
        )
    )
    scene.add(
        PipeRunComponent(
            id="P301_VAPOR",
            points=[ports["top"], [0, 1350], [2300, 1350]],
            label="Vapor Outlet",
            label_position=[1500, 1490],
            flow_direction="RIGHT",
            flow_arrow_position=[2050, 1350],
        )
    )
    scene.add(
        PipeRunComponent(
            id="P301_LIQUID",
            points=[ports["bottom"], [0, -1320], [2300, -1320]],
            label="Liquid Outlet",
            label_position=[1450, -1180],
            flow_direction="RIGHT",
            flow_arrow_position=[2050, -1320],
        )
    )
    scene.add(
        PipeRunComponent(
            id="P301_RECYCLE",
            points=[ports["right"], [980, 0], [980, -780], [360, -780]],
            label="Recycle Return",
            label_position=[1040, -420],
            flow_direction="LEFT",
            flow_arrow_position=[520, -780],
        )
    )

    scene.add(GateValveComponent(id="XV301_FEED", center=[-1700, 0], orientation="H"))
    scene.add(GateValveComponent(id="XV301_VAPOR", center=[1380, 1350], orientation="H"))
    scene.add(ControlValveComponent(id="LV301_LIQUID", center=[1400, -1320], orientation="H"))

    scene.add(InstrumentBubbleComponent(id="PT301", tag="PT-301", center=[-640, 1200]))
    scene.add(InstrumentBubbleComponent(id="TI301", tag="TI-301", center=[-820, -260]))
    scene.add(
        ControllerLoopComponent(
            id="LC301_LOOP",
            instrument_tag="LT-301",
            controller_tag="LC-301",
            instrument_center=[760, 280],
            controller_center=[1320, 280],
            signal_points=[[760, 280], [1320, 280], [1320, -1120], [1400, -1220]],
        )
    )
    scene.add(SignalLineComponent(id="SIG301_PT", points=[[-640, 1115], [-200, 840]]))
    scene.add(SignalLineComponent(id="SIG301_TI", points=[[-735, -260], [-360, -260]]))

    scene.add(LabelComponent(id="LBL301_LEVEL", text="Level Control", center=[1120, 520], height=55))
    scene.add(LabelComponent(id="LBL301_TEMP", text="Temperature", center=[-1160, -120], height=55))

    return scene


def render_vertical_vessel_component_pid() -> dict:
    return vertical_vessel_component_scene().to_command_sequence()


def pump_tank_component_scene() -> PIDComponentScene:
    scene = PIDComponentScene(
        title="Pump and Tank Component P&ID",
        assumptions=[
            "Pump is represented by a simple circular placeholder using existing components.",
        ],
    )

    tank = VerticalVesselComponent(
        id="T101",
        tag="T-101",
        center=[-1000, 0],
        height=1500,
        diameter=760,
    )
    tank_ports = tank.ports()
    scene.add(tank)

    scene.add(LabelComponent(id="LBL101_TANK", text="Tank T-101", center=[-1300, 960], height=65))
    scene.add(InstrumentBubbleComponent(id="P101_PLACEHOLDER", tag="P-101", center=[600, -520], radius=110))
    scene.add(LabelComponent(id="LBL101_PUMP", text="Pump P-101", center=[430, -330], height=65))

    scene.add(
        PipeRunComponent(
            id="P101_SUCTION",
            points=[tank_ports["bottom"], [-1000, -980], [600, -980], [600, -630]],
            label="Suction",
            label_position=[-420, -850],
            flow_direction="RIGHT",
            flow_arrow_position=[170, -980],
        )
    )
    scene.add(
        PipeRunComponent(
            id="P101_DISCHARGE",
            points=[[710, -520], [1600, -520], [1600, 420], [2500, 420]],
            label="Discharge",
            label_position=[1770, 560],
            flow_direction="RIGHT",
            flow_arrow_position=[2240, 420],
        )
    )

    scene.add(GateValveComponent(id="XV101_SUCTION", center=[-280, -980], orientation="H"))
    scene.add(GateValveComponent(id="XV101_DISCHARGE", center=[1100, -520], orientation="H"))
    scene.add(ControlValveComponent(id="FV101_DISCHARGE", center=[1900, 420], orientation="H"))

    scene.add(InstrumentBubbleComponent(id="PI101", tag="PI-101", center=[1240, -250]))
    scene.add(InstrumentBubbleComponent(id="FI101", tag="FI-101", center=[1900, 720]))
    scene.add(SignalLineComponent(id="SIG101_PI", points=[[1240, -335], [1240, -520]]))
    scene.add(SignalLineComponent(id="SIG101_FI", points=[[1900, 635], [1900, 500]]))

    return scene


def render_pump_tank_component_pid() -> dict:
    return pump_tank_component_scene().to_command_sequence()


def available_component_examples() -> dict[str, Callable[[], PIDComponentScene]]:
    return {
        "horizontal_separator": horizontal_separator_component_scene,
        "vertical_vessel": vertical_vessel_component_scene,
        "pump_tank": pump_tank_component_scene,
    }


def render_component_example(name: str) -> dict:
    examples = available_component_examples()
    if name not in examples:
        raise ValueError(f"Unknown component example: {name}")

    return examples[name]().to_command_sequence()

"""Builder for validated component-based P&ID scene data."""

from __future__ import annotations

from typing import Any

from src.framework.pid.component_schema import validate_pid_component_scene_data
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
    SignalLineComponent,
    VerticalVesselComponent,
)


class PIDComponentBuildError(Exception):
    """Raised when component-scene data cannot be built."""


def _common_kwargs(data: dict[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"id": data["id"]}
    for key in ("tag", "center", "metadata"):
        if key in data:
            kwargs[key] = data[key]
    return kwargs


def build_component_from_data(data: dict):
    """Build a concrete component from a component JSON object."""
    component_type = data.get("component_type")

    try:
        if component_type == "horizontal_vessel":
            return HorizontalVesselComponent(
                **_common_kwargs(data),
                length=data["length"],
                diameter=data["diameter"],
            )
        if component_type == "vertical_vessel":
            return VerticalVesselComponent(
                **_common_kwargs(data),
                height=data["height"],
                diameter=data["diameter"],
            )
        if component_type == "pipe_run":
            return PipeRunComponent(
                **_common_kwargs(data),
                points=data["points"],
                label=data.get("label"),
                label_position=data.get("label_position"),
                flow_direction=data.get("flow_direction"),
                flow_arrow_position=data.get("flow_arrow_position"),
            )
        if component_type == "signal_line":
            return SignalLineComponent(
                **_common_kwargs(data),
                points=data["points"],
            )
        if component_type == "gate_valve":
            return GateValveComponent(
                **_common_kwargs(data),
                orientation=data["orientation"],
                size=data.get("size", GateValveComponent.size),
            )
        if component_type == "control_valve":
            return ControlValveComponent(
                **_common_kwargs(data),
                orientation=data["orientation"],
                size=data.get("size", ControlValveComponent.size),
            )
        if component_type == "instrument_bubble":
            return InstrumentBubbleComponent(
                **_common_kwargs(data),
                radius=data.get("radius", InstrumentBubbleComponent.radius),
            )
        if component_type == "controller_loop":
            return ControllerLoopComponent(
                **_common_kwargs(data),
                instrument_tag=data["instrument_tag"],
                controller_tag=data["controller_tag"],
                instrument_center=data["instrument_center"],
                controller_center=data["controller_center"],
                signal_points=data.get("signal_points"),
                radius=data.get("radius", ControllerLoopComponent.radius),
            )
        if component_type == "label":
            return LabelComponent(
                **_common_kwargs(data),
                text=data["text"],
                height=data.get("height", LabelComponent.height),
            )
        if component_type == "flow_arrow":
            return FlowArrowComponent(
                **_common_kwargs(data),
                direction=data["direction"],
                size=data.get("size", FlowArrowComponent.size),
            )
        if component_type == "leader_line":
            return LeaderLineComponent(
                **_common_kwargs(data),
                points=data["points"],
                text=data.get("text"),
                text_position=data.get("text_position"),
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise PIDComponentBuildError(
            f"Failed to build component {data.get('id', '<unknown>')}: {exc}"
        ) from exc

    raise PIDComponentBuildError(f"Unsupported component type: {component_type}")


def build_pid_component_scene(data: dict) -> PIDComponentScene:
    """Build a P&ID component scene from validated JSON data."""
    errors = validate_pid_component_scene_data(data)
    if errors:
        joined_errors = "\n".join(f"- {error}" for error in errors)
        raise PIDComponentBuildError(f"Invalid P&ID component scene:\n{joined_errors}")

    scene = PIDComponentScene(
        title=data["title"],
        assumptions=data["assumptions"],
        metadata=data.get("metadata", {}),
    )

    for component_data in data["components"]:
        component = build_component_from_data(component_data)
        try:
            scene.add(component)
        except ValueError as exc:
            raise PIDComponentBuildError(str(exc)) from exc

    return scene


def render_pid_component_scene_data(data: dict) -> dict:
    """Build and render component-scene JSON to command sequence JSON."""
    scene = build_pid_component_scene(data)
    return scene.to_command_sequence()

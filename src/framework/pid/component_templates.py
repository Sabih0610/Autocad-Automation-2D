"""Deterministic component-scene templates for common P&ID requests."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy

from src.framework.pid.component_schema import validate_pid_component_scene_data


class PIDComponentTemplateError(Exception):
    """Raised when a deterministic P&ID component template is invalid."""


_AUTO_TAG_COMPONENT_TYPES = {
    "pipe_run": "P",
    "gate_valve": "XV",
    "control_valve": "CV",
}


def _component_tag_prefix(component: dict) -> str:
    component_id = str(
        component.get("id", "")
    ).strip().upper()

    prefix_chars = []

    for char in component_id:
        if char.isalpha():
            prefix_chars.append(char)
            continue

        break

    if prefix_chars:
        return "".join(prefix_chars)

    return _AUTO_TAG_COMPONENT_TYPES.get(
        component.get("component_type"),
        "C",
    )


def ensure_addressable_component_tags(
    scene: dict,
) -> dict:
    """Give every addressable pipe/valve a unique engineering tag.

    Equipment and instrument components already carry explicit engineering
    tags. Historically, pipe and valve tags were optional, which meant their
    generated geometry could not later be recovered through the project
    entity index.

    Missing pipe and valve tags are therefore generated deterministically in
    PREFIX-NNN form, for example:

        P-101
        XV-101
        FV-101
        LV-101

    Existing tags are never overwritten.
    """
    components = scene.get(
        "components"
    )

    if not isinstance(
        components,
        list,
    ):
        return scene

    used_tags = {
        str(
            component.get("tag")
        ).strip().casefold()
        for component in components
        if isinstance(component, dict)
        and isinstance(
            component.get("tag"),
            str,
        )
        and component.get(
            "tag",
            "",
        ).strip()
    }

    next_number: dict[
        str,
        int,
    ] = {}

    for component in components:
        if not isinstance(
            component,
            dict,
        ):
            continue

        component_type = (
            component.get(
                "component_type"
            )
        )

        if (
            component_type
            not in
            _AUTO_TAG_COMPONENT_TYPES
        ):
            continue

        existing = component.get(
            "tag"
        )

        if (
            isinstance(existing, str)
            and existing.strip()
        ):
            component["tag"] = (
                existing.strip()
            )
            continue

        prefix = (
            _component_tag_prefix(
                component
            )
        )

        number = max(
            next_number.get(
                prefix,
                100,
            ) + 1,
            101,
        )

        candidate = (
            f"{prefix}-{number:03d}"
        )

        while (
            candidate.casefold()
            in used_tags
        ):
            number += 1

            candidate = (
                f"{prefix}-{number:03d}"
            )

        component["tag"] = candidate

        used_tags.add(
            candidate.casefold()
        )

        next_number[prefix] = (
            number
        )

    return scene


def validate_template_scene(
    scene: dict,
) -> dict:
    """Validate and return a defensive, fully-addressable template copy."""
    copied_scene = deepcopy(
        scene
    )

    ensure_addressable_component_tags(
        copied_scene
    )

    errors = (
        validate_pid_component_scene_data(
            copied_scene
        )
    )

    if errors:
        joined_errors = "\n".join(
            f"- {error}"
            for error in errors
        )

        raise PIDComponentTemplateError(
            "Invalid P&ID component template:\n"
            f"{joined_errors}"
        )

    return copied_scene


def horizontal_separator_template_scene(
    title: str = "Horizontal Separator P&ID",
) -> dict:
    scene = {
        "schema_version": "1.0",
        "title": title,
        "drawing_type": "P&ID",
        "assumptions": [
            "Generated from deterministic horizontal separator component template.",
            "Schematic is for concept review and requires engineering verification.",
        ],
        "metadata": {
            "source": "deterministic_template",
            "template_name": "horizontal_separator",
        },
        "components": [
            {
                "component_type": "horizontal_vessel",
                "id": "V201",
                "tag": "V-201",
                "center": [0, 0],
                "length": 2800,
                "diameter": 760,
            },
            {
                "component_type": "pipe_run",
                "id": "P_INLET",
                "points": [[-3200, 0], [-1400, 0]],
                "label": "3 Phase Inlet",
                "label_position": [-2850, 145],
                "flow_direction": "RIGHT",
                "flow_arrow_position": [-2850, 0],
            },
            {
                "component_type": "pipe_run",
                "id": "P_VAPOR",
                "points": [[840, 380], [840, 920], [3000, 920]],
                "label": "Vapor Outlet",
                "label_position": [2300, 1060],
                "flow_direction": "RIGHT",
                "flow_arrow_position": [2760, 920],
            },
            {
                "component_type": "pipe_run",
                "id": "P_OIL",
                "points": [[840, -380], [840, -1120], [3000, -1120]],
                "label": "Oil Outlet",
                "label_position": [2180, -980],
                "flow_direction": "RIGHT",
                "flow_arrow_position": [2740, -1120],
            },
            {
                "component_type": "pipe_run",
                "id": "P_WATER",
                "points": [[-840, -380], [-840, -940], [-3000, -940]],
                "label": "Water Outlet",
                "label_position": [-2860, -800],
                "flow_direction": "LEFT",
                "flow_arrow_position": [-2740, -940],
            },
            {
                "component_type": "pipe_run",
                "id": "P_DRAIN",
                "points": [[0, -380], [0, -1450]],
                "label": "Drain",
                "label_position": [130, -1360],
                "flow_direction": "DOWN",
                "flow_arrow_position": [0, -1320],
            },
            {
                "component_type": "pipe_run",
                "id": "P_VENT",
                "points": [[0, 380], [0, 1320]],
                "label": "Vent",
                "label_position": [120, 1220],
                "flow_direction": "UP",
                "flow_arrow_position": [0, 1140],
            },
            {"component_type": "gate_valve", "id": "XV_IN", "center": [-2150, 0], "orientation": "H"},
            {"component_type": "gate_valve", "id": "XV_VAPOR", "center": [1680, 920], "orientation": "H"},
            {"component_type": "gate_valve", "id": "XV_WATER", "center": [-1750, -940], "orientation": "H"},
            {"component_type": "gate_valve", "id": "XV_DRAIN", "center": [0, -1120], "orientation": "V"},
            {"component_type": "control_valve", "id": "LV_OIL", "center": [1900, -1120], "orientation": "H"},
            {"component_type": "instrument_bubble", "id": "PT201", "tag": "PT-201", "center": [-620, 1030]},
            {"component_type": "instrument_bubble", "id": "PI201", "tag": "PI-201", "center": [1220, 1190]},
            {
                "component_type": "controller_loop",
                "id": "LC201_LOOP",
                "instrument_tag": "LT-201",
                "controller_tag": "LC-201",
                "instrument_center": [1650, 250],
                "controller_center": [2180, 250],
                "signal_points": [[1650, 250], [2180, 250], [2180, -950], [1900, -1010]],
            },
            {"component_type": "signal_line", "id": "SIG_PT", "points": [[-620, 945], [-620, 380]]},
            {"component_type": "signal_line", "id": "SIG_PI", "points": [[1220, 1105], [1220, 920]]},
            {"component_type": "label", "id": "LBL_DEMISTER", "text": "Demister Pad", "center": [640, 320], "height": 55},
            {"component_type": "label", "id": "LBL_WEIR", "text": "Weir", "center": [-260, -210], "height": 55},
            {"component_type": "label", "id": "LBL_VORTEX", "text": "Vortex Breaker", "center": [300, -510], "height": 55},
        ],
    }
    return validate_template_scene(scene)


def vertical_vessel_template_scene(
    title: str = "Vertical Vessel P&ID",
) -> dict:
    scene = {
        "schema_version": "1.0",
        "title": title,
        "drawing_type": "P&ID",
        "assumptions": [
            "Generated from deterministic vertical vessel component template.",
            "Schematic is for concept review and requires engineering verification.",
        ],
        "metadata": {
            "source": "deterministic_template",
            "template_name": "vertical_vessel",
        },
        "components": [
            {
                "component_type": "vertical_vessel",
                "id": "V301",
                "tag": "V-301",
                "center": [0, 0],
                "height": 1900,
                "diameter": 720,
            },
            {
                "component_type": "pipe_run",
                "id": "P_FEED",
                "points": [[-2600, 0], [-360, 0]],
                "label": "Feed Inlet",
                "label_position": [-2380, 145],
                "flow_direction": "RIGHT",
                "flow_arrow_position": [-2280, 0],
            },
            {
                "component_type": "pipe_run",
                "id": "P_VAPOR",
                "points": [[0, 950], [0, 1350], [2300, 1350]],
                "label": "Vapor Outlet",
                "label_position": [1500, 1490],
                "flow_direction": "RIGHT",
                "flow_arrow_position": [2050, 1350],
            },
            {
                "component_type": "pipe_run",
                "id": "P_LIQUID",
                "points": [[0, -950], [0, -1320], [2300, -1320]],
                "label": "Liquid Outlet",
                "label_position": [1450, -1180],
                "flow_direction": "RIGHT",
                "flow_arrow_position": [2050, -1320],
            },
            {"component_type": "gate_valve", "id": "XV_FEED", "center": [-1700, 0], "orientation": "H"},
            {"component_type": "gate_valve", "id": "XV_VAPOR", "center": [1380, 1350], "orientation": "H"},
            {"component_type": "control_valve", "id": "LV_LIQUID", "center": [1400, -1320], "orientation": "H"},
            {"component_type": "instrument_bubble", "id": "PT301", "tag": "PT-301", "center": [-640, 1200]},
            {"component_type": "instrument_bubble", "id": "TI301", "tag": "TI-301", "center": [-820, -260]},
            {
                "component_type": "controller_loop",
                "id": "LC301_LOOP",
                "instrument_tag": "LT-301",
                "controller_tag": "LC-301",
                "instrument_center": [760, 280],
                "controller_center": [1320, 280],
                "signal_points": [[760, 280], [1320, 280], [1320, -1120], [1400, -1220]],
            },
            {"component_type": "signal_line", "id": "SIG_PT", "points": [[-640, 1115], [-200, 840]]},
            {"component_type": "signal_line", "id": "SIG_TI", "points": [[-735, -260], [-360, -260]]},
            {"component_type": "label", "id": "LBL_LEVEL", "text": "Level Control", "center": [1120, 520], "height": 55},
            {"component_type": "label", "id": "LBL_TEMP", "text": "Temperature", "center": [-1160, -120], "height": 55},
        ],
    }
    return validate_template_scene(scene)


def pump_tank_template_scene(
    title: str = "Pump and Tank P&ID",
) -> dict:
    scene = {
        "schema_version": "1.0",
        "title": title,
        "drawing_type": "P&ID",
        "assumptions": [
            "Generated from deterministic pump and tank component template.",
            "Pump is represented by a labeled circular placeholder.",
        ],
        "metadata": {
            "source": "deterministic_template",
            "template_name": "pump_tank",
        },
        "components": [
            {
                "component_type": "vertical_vessel",
                "id": "T101",
                "tag": "T-101",
                "center": [-1000, 0],
                "height": 1500,
                "diameter": 760,
            },
            {"component_type": "label", "id": "LBL_TANK", "text": "Tank T-101", "center": [-1300, 960], "height": 65},
            {"component_type": "instrument_bubble", "id": "P101_MARKER", "tag": "P-101", "center": [600, -520], "radius": 110},
            {"component_type": "label", "id": "LBL_PUMP", "text": "Pump P-101", "center": [430, -330], "height": 65},
            {
                "component_type": "pipe_run",
                "id": "P_SUCTION",
                "points": [[-1000, -750], [-1000, -980], [600, -980], [600, -630]],
                "label": "Suction",
                "label_position": [-420, -850],
                "flow_direction": "RIGHT",
                "flow_arrow_position": [170, -980],
            },
            {
                "component_type": "pipe_run",
                "id": "P_DISCHARGE",
                "points": [[710, -520], [1600, -520], [1600, 420], [2500, 420]],
                "label": "Discharge",
                "label_position": [1770, 560],
                "flow_direction": "RIGHT",
                "flow_arrow_position": [2240, 420],
            },
            {"component_type": "gate_valve", "id": "XV_SUCTION", "center": [-280, -980], "orientation": "H"},
            {"component_type": "gate_valve", "id": "XV_DISCHARGE", "center": [1100, -520], "orientation": "H"},
            {"component_type": "control_valve", "id": "FV_DISCHARGE", "center": [1900, 420], "orientation": "H"},
            {"component_type": "instrument_bubble", "id": "PI101", "tag": "PI-101", "center": [1240, -250]},
            {"component_type": "instrument_bubble", "id": "FI101", "tag": "FI-101", "center": [1900, 720]},
            {"component_type": "signal_line", "id": "SIG_PI", "points": [[1240, -335], [1240, -520]]},
            {"component_type": "signal_line", "id": "SIG_FI", "points": [[1900, 635], [1900, 500]]},
        ],
    }
    return validate_template_scene(scene)


def available_pid_component_templates() -> dict[str, Callable[[], dict]]:
    return {
        "horizontal_separator": horizontal_separator_template_scene,
        "vertical_vessel": vertical_vessel_template_scene,
        "pump_tank": pump_tank_template_scene,
    }


def choose_pid_component_template(user_request: str) -> tuple[str, dict]:
    normalized = user_request.lower()

    if any(term in normalized for term in ["pump", "suction", "discharge", "tank"]):
        template_name = "pump_tank"
    elif any(term in normalized for term in ["vertical", "column", "tower", "vessel vertical"]):
        template_name = "vertical_vessel"
    elif any(
        term in normalized
        for term in ["separator", "3 phase", "three phase", "oil", "water", "vapor", "horizontal"]
    ):
        template_name = "horizontal_separator"
    else:
        template_name = "horizontal_separator"

    return template_name, available_pid_component_templates()[template_name]()

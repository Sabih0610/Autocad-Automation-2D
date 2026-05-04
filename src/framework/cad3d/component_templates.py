"""Deterministic CAD3D design-family templates."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
import re

from src.framework.cad3d.component_examples import (
    extended_3d_process_unit_scene_data,
    simple_3d_component_layout_scene_data,
)
from src.framework.cad3d.scene_schema import CAD3D_SCENE_SCHEMA_VERSION, validate_cad3d_scene


class CAD3DTemplateError(Exception):
    """Raised when a deterministic CAD3D template is invalid."""


def _scene(
    title: str,
    template_name: str,
    assumptions: list[str],
    components: list[dict],
) -> dict:
    return validate_cad3d_template_scene(
        {
            "schema_version": CAD3D_SCENE_SCHEMA_VERSION,
            "title": title,
            "units": "mm",
            "assumptions": assumptions,
            "metadata": {
                "source": "deterministic_template",
                "template_name": template_name,
            },
            "components": components,
        }
    )


def _with_template_metadata(scene: dict, template_name: str) -> dict:
    result = deepcopy(scene)
    result.setdefault("metadata", {})
    result["metadata"].update(
        {
            "source": "deterministic_template",
            "template_name": template_name,
        }
    )
    return validate_cad3d_template_scene(result)


def _replace_components_by_id(scene: dict, replacements: dict[str, dict]) -> dict:
    result = deepcopy(scene)
    result["components"] = [
        deepcopy(replacements.get(component.get("id"), component))
        for component in result.get("components", [])
    ]
    return result


def tank_pump_separator_template_scene() -> dict:
    """Return a simple tank-pump-separator 3D template scene."""
    scene = _replace_components_by_id(
        simple_3d_component_layout_scene_data(),
        {
            "P_TANK_PUMP": {
                "component_type": "pipe_connection_3d",
                "id": "PIPE_T101_P101",
                "tag": "Tank to pump suction",
                "from_port": "T101.side_right",
                "to_port": "P101.suction",
                "diameter": 100,
                "routing_style": "orthogonal",
                "clearance": 400,
            },
            "P_PUMP_VESSEL": {
                "component_type": "pipe_connection_3d",
                "id": "PIPE_P101_V201",
                "tag": "Pump discharge to separator",
                "from_port": "P101.discharge",
                "to_port": "V201.end_a",
                "diameter": 100,
                "routing_style": "orthogonal",
                "clearance": 400,
            },
        },
    )
    return _with_template_metadata(
        scene,
        "tank_pump_separator",
    )


def extended_process_unit_template_scene() -> dict:
    """Return an extended process unit 3D template scene."""
    scene = _replace_components_by_id(
        extended_3d_process_unit_scene_data(),
        {
            "P_TANK_PUMP": {
                "component_type": "pipe_connection_3d",
                "id": "PIPE_T101_P101",
                "tag": "Tank to pump suction",
                "from_port": "T101.side_right",
                "to_port": "P101.suction",
                "diameter": 120,
                "routing_style": "orthogonal",
                "clearance": 450,
            },
            "P_PUMP_EXCHANGER": {
                "component_type": "pipe_connection_3d",
                "id": "PIPE_P101_E101",
                "tag": "Pump discharge to exchanger",
                "from_port": "P101.discharge",
                "to_port": "E101.inlet",
                "diameter": 100,
                "routing_style": "orthogonal",
                "clearance": 450,
            },
            "P_EXCHANGER_VESSEL": {
                "component_type": "pipe_connection_3d",
                "id": "PIPE_E101_V201",
                "tag": "Exchanger outlet to separator",
                "from_port": "E101.outlet",
                "to_port": "V201.end_a",
                "diameter": 100,
                "routing_style": "orthogonal",
                "clearance": 450,
            },
        },
    )
    return _with_template_metadata(
        scene,
        "extended_process_unit",
    )


def dual_pump_skid_template_scene() -> dict:
    """Return a dual-pump skid with suction and discharge headers."""
    components = [
        {
            "component_type": "skid_base_3d",
            "id": "SKID_DP",
            "center": [1800, 0, -100],
            "length": 5200,
            "width": 2400,
            "height": 200,
        },
        {
            "component_type": "pump_placeholder_3d",
            "id": "P101",
            "tag": "P-101",
            "center": [800, -500, 300],
            "length": 800,
            "width": 450,
            "height": 500,
        },
        {
            "component_type": "pump_placeholder_3d",
            "id": "P102",
            "tag": "P-102",
            "center": [800, 500, 300],
            "length": 800,
            "width": 450,
            "height": 500,
        },
        {
            "component_type": "pipe_run_3d",
            "id": "P_SUCTION_HEADER",
            "tag": "Suction Header",
            "points": [[-900, -950, 350], [2600, -950, 350]],
            "diameter": 150,
        },
        {
            "component_type": "pipe_run_3d",
            "id": "P_DISCHARGE_HEADER",
            "tag": "Discharge Header",
            "points": [[-900, 950, 600], [2600, 950, 600]],
            "diameter": 125,
        },
        {
            "component_type": "pipe_run_3d",
            "id": "P_P101_SUCTION",
            "points": [[400, -950, 350], [400, -500, 350]],
            "diameter": 100,
        },
        {
            "component_type": "pipe_run_3d",
            "id": "P_P102_SUCTION",
            "points": [[400, -950, 350], [400, 500, 350]],
            "diameter": 100,
        },
        {
            "component_type": "pipe_run_3d",
            "id": "P_P101_DISCHARGE",
            "points": [[1200, -500, 600], [1200, 950, 600]],
            "diameter": 100,
        },
        {
            "component_type": "pipe_run_3d",
            "id": "P_P102_DISCHARGE",
            "points": [[1200, 500, 600], [1200, 950, 600]],
            "diameter": 100,
        },
        {
            "component_type": "valve_placeholder_3d",
            "id": "XV_P101_SUC",
            "center": [400, -750, 350],
            "length": 300,
            "width": 220,
            "height": 220,
            "orientation": "Y",
            "valve_type": "gate",
        },
        {
            "component_type": "valve_placeholder_3d",
            "id": "XV_P102_SUC",
            "center": [400, 200, 350],
            "length": 300,
            "width": 220,
            "height": 220,
            "orientation": "Y",
            "valve_type": "gate",
        },
        {
            "component_type": "valve_placeholder_3d",
            "id": "XV_P101_DIS",
            "center": [1200, 200, 600],
            "length": 300,
            "width": 220,
            "height": 220,
            "orientation": "Y",
            "valve_type": "check",
        },
        {
            "component_type": "valve_placeholder_3d",
            "id": "XV_P102_DIS",
            "center": [1200, 750, 600],
            "length": 300,
            "width": 220,
            "height": 220,
            "orientation": "Y",
            "valve_type": "check",
        },
        {
            "component_type": "flange_3d",
            "id": "FLG_SUC",
            "center": [-400, -950, 350],
            "diameter": 260,
            "thickness": 80,
            "orientation": "X",
        },
        {
            "component_type": "flange_3d",
            "id": "FLG_DIS",
            "center": [2200, 950, 600],
            "diameter": 240,
            "thickness": 80,
            "orientation": "X",
        },
        {
            "component_type": "pipe_support_3d",
            "id": "PS_SUC",
            "center": [-100, -950, 150],
            "height": 300,
            "width": 260,
            "depth": 260,
        },
        {
            "component_type": "pipe_support_3d",
            "id": "PS_DIS",
            "center": [2200, 950, 300],
            "height": 600,
            "width": 260,
            "depth": 260,
        },
        {"component_type": "label_3d", "id": "LBL_P101", "text": "P-101", "position": [450, -1000, 850], "height": 160},
        {"component_type": "label_3d", "id": "LBL_P102", "text": "P-102", "position": [450, 1000, 850], "height": 160},
        {"component_type": "label_3d", "id": "LBL_SUC", "text": "Suction Header", "position": [-800, -1250, 650], "height": 150},
        {"component_type": "label_3d", "id": "LBL_DIS", "text": "Discharge Header", "position": [-800, 1200, 900], "height": 150},
    ]
    return _scene(
        "Dual Pump Skid 3D Template",
        "dual_pump_skid",
        ["Generated from deterministic dual-pump skid template."],
        components,
    )


def heat_exchanger_skid_template_scene() -> dict:
    """Return a heat-exchanger skid with bypass and supports."""
    components = [
        {"component_type": "skid_base_3d", "id": "SKID_HEX", "center": [2000, 0, -100], "length": 5600, "width": 2200, "height": 200},
        {"component_type": "pump_placeholder_3d", "id": "P101", "tag": "P-101", "center": [200, -550, 300], "length": 800, "width": 450, "height": 500},
        {"component_type": "heat_exchanger_3d", "id": "E101", "tag": "E-101", "center": [2300, -550, 650], "length": 1900, "diameter": 500, "orientation": "X"},
        {"component_type": "pipe_run_3d", "id": "P_INLET", "tag": "Inlet", "points": [[-900, -550, 350], [-200, -550, 350]], "diameter": 120},
        {"component_type": "pipe_connection_3d", "id": "PIPE_P101_E101", "from_port": "P101.discharge", "to_port": "E101.inlet", "diameter": 100, "routing_style": "orthogonal", "clearance": 400},
        {"component_type": "pipe_run_3d", "id": "P_OUTLET", "tag": "Outlet", "points": [[3250, -550, 650], [4200, -550, 650]], "diameter": 100},
        {"component_type": "pipe_run_3d", "id": "P_BYPASS", "tag": "Bypass", "points": [[900, -550, 650], [900, 550, 650], [3500, 550, 650], [3500, -550, 650]], "diameter": 80},
        {"component_type": "valve_placeholder_3d", "id": "XV_IN", "center": [-450, -550, 350], "length": 300, "width": 220, "height": 220, "orientation": "X", "valve_type": "gate"},
        {"component_type": "valve_placeholder_3d", "id": "XV_OUT", "center": [3850, -550, 650], "length": 300, "width": 220, "height": 220, "orientation": "X", "valve_type": "gate"},
        {"component_type": "valve_placeholder_3d", "id": "XV_BYP", "center": [2200, 550, 650], "length": 300, "width": 220, "height": 220, "orientation": "X", "valve_type": "gate"},
        {"component_type": "flange_3d", "id": "FLG_E101_A", "center": [1350, -550, 650], "diameter": 260, "thickness": 80, "orientation": "X"},
        {"component_type": "flange_3d", "id": "FLG_E101_B", "center": [3250, -550, 650], "diameter": 260, "thickness": 80, "orientation": "X"},
        {"component_type": "pipe_support_3d", "id": "PS_IN", "center": [-700, -550, 175], "height": 350, "width": 260, "depth": 260},
        {"component_type": "pipe_support_3d", "id": "PS_OUT", "center": [4000, -550, 325], "height": 650, "width": 260, "depth": 260},
        {"component_type": "label_3d", "id": "LBL_P101", "text": "P-101", "position": [-100, -1050, 850], "height": 160},
        {"component_type": "label_3d", "id": "LBL_E101", "text": "E-101", "position": [1900, -1050, 1100], "height": 170},
        {"component_type": "label_3d", "id": "LBL_IN", "text": "Inlet", "position": [-900, -850, 650], "height": 140},
        {"component_type": "label_3d", "id": "LBL_OUT", "text": "Outlet", "position": [3800, -850, 950], "height": 140},
        {"component_type": "label_3d", "id": "LBL_BYP", "text": "Bypass", "position": [1900, 850, 950], "height": 140},
    ]
    return _scene(
        "Heat Exchanger Skid 3D Template",
        "heat_exchanger_skid",
        ["Generated from deterministic heat-exchanger skid template."],
        components,
    )


def vertical_scrubber_package_template_scene() -> dict:
    """Return a vertical scrubber package with gas inlet/outlet, vent, and drain."""
    components = [
        {"component_type": "vertical_tank_3d", "id": "V301", "tag": "V-301", "center": [0, 0, 1500], "diameter": 1100, "height": 3000},
        {"component_type": "pipe_run_3d", "id": "P_GAS_IN", "tag": "Gas Inlet", "points": [[-2200, -250, 1000], [-550, -250, 1000]], "diameter": 150},
        {"component_type": "pipe_run_3d", "id": "P_GAS_OUT", "tag": "Gas Outlet", "points": [[550, 250, 2200], [2200, 250, 2200]], "diameter": 150},
        {"component_type": "pipe_run_3d", "id": "P_VENT", "tag": "Vent", "points": [[0, 0, 3000], [0, 0, 3600], [800, 0, 3600]], "diameter": 80},
        {"component_type": "pipe_run_3d", "id": "P_DRAIN", "tag": "Drain", "points": [[0, 0, 0], [0, -1000, 0]], "diameter": 80},
        {"component_type": "valve_placeholder_3d", "id": "XV_IN", "center": [-1300, -250, 1000], "length": 300, "width": 220, "height": 220, "orientation": "X", "valve_type": "gate"},
        {"component_type": "valve_placeholder_3d", "id": "XV_OUT", "center": [1400, 250, 2200], "length": 300, "width": 220, "height": 220, "orientation": "X", "valve_type": "gate"},
        {"component_type": "valve_placeholder_3d", "id": "XV_DRAIN", "center": [0, -650, 0], "length": 260, "width": 200, "height": 200, "orientation": "Y", "valve_type": "gate"},
        {"component_type": "flange_3d", "id": "FLG_IN", "center": [-550, -250, 1000], "diameter": 300, "thickness": 90, "orientation": "X"},
        {"component_type": "flange_3d", "id": "FLG_OUT", "center": [550, 250, 2200], "diameter": 300, "thickness": 90, "orientation": "X"},
        {"component_type": "support_leg_3d", "id": "LEG_A", "center": [-350, -350, 300], "diameter": 100, "height": 600},
        {"component_type": "support_leg_3d", "id": "LEG_B", "center": [350, -350, 300], "diameter": 100, "height": 600},
        {"component_type": "support_leg_3d", "id": "LEG_C", "center": [0, 450, 300], "diameter": 100, "height": 600},
        {"component_type": "pipe_support_3d", "id": "PS_OUT", "center": [1800, 250, 1100], "height": 2200, "width": 260, "depth": 260},
        {"component_type": "label_3d", "id": "LBL_V301", "text": "V-301", "position": [-450, 900, 3000], "height": 180},
        {"component_type": "label_3d", "id": "LBL_IN", "text": "Gas Inlet", "position": [-2100, -600, 1300], "height": 150},
        {"component_type": "label_3d", "id": "LBL_OUT", "text": "Gas Outlet", "position": [1300, 600, 2500], "height": 150},
        {"component_type": "label_3d", "id": "LBL_DRAIN", "text": "Drain", "position": [200, -1100, 250], "height": 140},
        {"component_type": "label_3d", "id": "LBL_VENT", "text": "Vent", "position": [500, 250, 3850], "height": 140},
    ]
    return _scene(
        "Vertical Scrubber Package 3D Template",
        "vertical_scrubber_package",
        ["Generated from deterministic vertical scrubber package template."],
        components,
    )


def available_cad3d_templates() -> dict[str, Callable[[], dict]]:
    return {
        "tank_pump_separator": tank_pump_separator_template_scene,
        "extended_process_unit": extended_process_unit_template_scene,
        "dual_pump_skid": dual_pump_skid_template_scene,
        "heat_exchanger_skid": heat_exchanger_skid_template_scene,
        "vertical_scrubber_package": vertical_scrubber_package_template_scene,
    }


def validate_cad3d_template_scene(scene: dict) -> dict:
    errors = validate_cad3d_scene(scene)
    if errors:
        joined_errors = "\n".join(f"- {error}" for error in errors)
        raise CAD3DTemplateError(f"Invalid CAD3D template scene:\n{joined_errors}")
    return scene


def _normalize_prompt(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def _score(text: str, terms: tuple[str, ...]) -> int:
    return sum(1 for term in terms if term in text)


def match_cad3d_template(user_request: str) -> dict:
    normalized = _normalize_prompt(user_request)

    dual_terms = ("two pumps", "2 pumps", "pump skid", "suction header", "discharge header")
    if "dual pump" in normalized or _score(normalized, dual_terms) >= 2:
        return {
            "template_name": "dual_pump_skid",
            "confidence": "high",
            "reason": "Matched dual pump skid/header keywords.",
        }

    scrubber_terms = ("scrubber", "vertical vessel", "gas inlet", "gas outlet", "vent", "drain")
    if "vertical scrubber" in normalized or _score(normalized, scrubber_terms) >= 2:
        return {
            "template_name": "vertical_scrubber_package",
            "confidence": "high",
            "reason": "Matched vertical scrubber package keywords.",
        }

    if "heat exchanger skid" in normalized:
        return {
            "template_name": "heat_exchanger_skid",
            "confidence": "high",
            "reason": "Matched heat exchanger skid keywords.",
        }

    extended_terms = ("tank", "pump", "heat exchanger", "separator", "valves", "flanges", "supports", "process unit")
    extended_score = _score(normalized, extended_terms)
    if "extended process unit" in normalized or extended_score >= 4:
        return {
            "template_name": "extended_process_unit",
            "confidence": "high",
            "reason": "Matched extended process unit equipment keywords.",
        }

    heat_terms = ("exchanger", "cooler", "bypass", "inlet outlet", "thermal")
    if "heat exchanger" in normalized or _score(normalized, heat_terms) >= 2:
        return {
            "template_name": "heat_exchanger_skid",
            "confidence": "high",
            "reason": "Matched heat exchanger or thermal skid keywords.",
        }

    tank_pump_terms = ("tank", "pump", "horizontal separator", "vessel", "connecting pipes", "skid")
    if _score(normalized, tank_pump_terms) >= 3:
        return {
            "template_name": "tank_pump_separator",
            "confidence": "high",
            "reason": "Matched tank, pump, separator, or skid keywords.",
        }

    if extended_score >= 3:
        return {
            "template_name": "extended_process_unit",
            "confidence": "high",
            "reason": "Matched multiple process unit equipment keywords.",
        }

    return {
        "template_name": "tank_pump_separator",
        "confidence": "low",
        "reason": "Default 3D template fallback.",
    }


def choose_cad3d_template(user_request: str) -> tuple[str, dict]:
    match = match_cad3d_template(user_request)
    template_name = match["template_name"]
    templates = available_cad3d_templates()
    try:
        scene_data = templates[template_name]()
    except KeyError as exc:
        raise CAD3DTemplateError(f"Unknown CAD3D template: {template_name}") from exc
    return template_name, scene_data

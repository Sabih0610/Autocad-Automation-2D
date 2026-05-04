"""AI planner for structured 3D CAD scenes.

This module plans CAD3D scene JSON only. It does not emit AutoCAD commands,
execute AutoCAD, expose API routes, or build geometry directly.
"""

from __future__ import annotations

import json
from typing import Any

from src.ai.client import ask_ai
from src.framework.cad3d.component_templates import choose_cad3d_template
from src.framework.cad3d.scene_schema import (
    CAD3D_SCENE_SCHEMA,
    CAD3D_SCENE_SCHEMA_VERSION,
    validate_cad3d_scene,
)


CAD3D_SCENE_PLANNER_MAX_TOKENS = 4000


CAD3D_SCENE_PLANNER_SYSTEM_PROMPT = """
You are a 3D CAD scene planner for AutoCAD.

You do not generate AutoCAD commands.
You do not generate Python code.
You only return valid JSON matching the CAD3D_SCENE_SCHEMA.

Your job is to convert a user's 3D CAD request into a structured 3D component scene.

Supported component_type values:
- vertical_tank_3d
- horizontal_vessel_3d
- pump_placeholder_3d
- pipe_run_3d
- pipe_connection_3d
- skid_base_3d
- box_3d
- label_3d
- heat_exchanger_3d
- valve_placeholder_3d
- nozzle_3d
- flange_3d
- support_leg_3d
- saddle_support_3d
- pipe_support_3d

All dimensions and coordinates must be in millimeters.

Use simple, clean, safe geometry:
- tanks as vertical cylinders
- horizontal vessels as horizontal cylinders
- pumps as placeholder boxes
- pipes as logical pipe_connection_3d where ports are known, or pipe_run_3d centerline paths where needed
- skid/base as boxes
- labels as label_3d components
- heat exchangers as heat_exchanger_3d components
- valves as valve_placeholder_3d components
- flanges around equipment nozzles or pipe joints
- support legs, saddle supports, and pipe supports where useful
- nozzles for vessel/tank connections where useful

Keep the scene compact and buildable.
Avoid unsupported component types.
Avoid excessive complexity.
Use realistic spacing.
Use readable labels.
Prefer 8-35 components for normal prompts.
Use more components only when explicitly requested.
Return JSON only.

Pipe routing rules:
1. Prefer pipe_connection_3d for equipment-to-equipment connections when both components have known ports.
2. Use pipe_run_3d only for free-form headers, bypass lines, vents, drains, or custom pipe segments where a port-to-port connection is not obvious.
3. pipe_connection_3d is logical. It will be expanded by Python into pipe_run_3d before AutoCAD execution.
4. from_port and to_port must use format COMPONENT_ID.PORT_NAME.
5. Use component IDs without dashes, for example T101, P101, E101, V201.
6. Use tags with dashes for labels, for example T-101, P-101, E-101, V-201.

Known port examples:
- vertical_tank_3d: top, bottom, side_left, side_right, side_front, side_back, inlet, outlet, drain, vent
- horizontal_vessel_3d: end_a, end_b, inlet, outlet, top, bottom, drain, vent
- heat_exchanger_3d: inlet, outlet, end_a, end_b
- pump_placeholder_3d: suction, discharge, inlet, outlet
- valve_placeholder_3d: inlet, outlet
- nozzle_3d: base, tip, inlet, outlet
- flange_3d: face_a, face_b, inlet, outlet
- pipe_run_3d: start, end

Valid pipe_connection_3d examples:
{"component_type":"pipe_connection_3d","id":"PIPE_T101_P101","from_port":"T101.side_right","to_port":"P101.suction","diameter":100,"routing_style":"orthogonal","clearance":400}
{"component_type":"pipe_connection_3d","id":"PIPE_P101_E101","from_port":"P101.discharge","to_port":"E101.inlet","diameter":100,"routing_style":"orthogonal","clearance":400}
""".strip()


_SUPPORTED_COMPONENT_TYPES = [
    "vertical_tank_3d",
    "horizontal_vessel_3d",
    "pump_placeholder_3d",
    "pipe_run_3d",
    "pipe_connection_3d",
    "skid_base_3d",
    "box_3d",
    "label_3d",
    "heat_exchanger_3d",
    "valve_placeholder_3d",
    "nozzle_3d",
    "flange_3d",
    "support_leg_3d",
    "saddle_support_3d",
    "pipe_support_3d",
]


_PIPE_ROUTING_RULES = [
    "Pipe routing rules:",
    "- Prefer pipe_connection_3d for equipment-to-equipment connections when both components have known ports.",
    "- Use pipe_run_3d only for free-form headers, bypass lines, vents, drains, or custom pipe segments where a port-to-port connection is not obvious.",
    "- pipe_connection_3d is logical and will be expanded by Python into pipe_run_3d before AutoCAD execution.",
    "- from_port and to_port must use format COMPONENT_ID.PORT_NAME.",
    "- Use component IDs without dashes, for example T101, P101, E101, V201.",
    "- Use tags with dashes for labels, for example T-101, P-101, E-101, V-201.",
]


_KNOWN_PORT_EXAMPLES = [
    "Known port examples:",
    "- vertical_tank_3d: top, bottom, side_left, side_right, side_front, side_back, inlet, outlet, drain, vent",
    "- horizontal_vessel_3d: end_a, end_b, inlet, outlet, top, bottom, drain, vent",
    "- heat_exchanger_3d: inlet, outlet, end_a, end_b",
    "- pump_placeholder_3d: suction, discharge, inlet, outlet",
    "- valve_placeholder_3d: inlet, outlet",
    "- nozzle_3d: base, tip, inlet, outlet",
    "- flange_3d: face_a, face_b, inlet, outlet",
    "- pipe_run_3d: start, end",
    "- Example references: T101.side_right, P101.suction, P101.discharge, E101.inlet",
]


_PIPE_CONNECTION_EXAMPLES = [
    "Valid pipe_connection_3d examples:",
    json.dumps(
        {
            "component_type": "pipe_connection_3d",
            "id": "PIPE_T101_P101",
            "from_port": "T101.side_right",
            "to_port": "P101.suction",
            "diameter": 100,
            "routing_style": "orthogonal",
            "clearance": 400,
        },
        separators=(",", ": "),
    ),
    json.dumps(
        {
            "component_type": "pipe_connection_3d",
            "id": "PIPE_P101_E101",
            "from_port": "P101.discharge",
            "to_port": "E101.inlet",
            "diameter": 100,
            "routing_style": "orthogonal",
            "clearance": 400,
        },
        separators=(",", ": "),
    ),
]


_EXAMPLE_CAD3D_SCENE: dict[str, Any] = {
    "schema_version": CAD3D_SCENE_SCHEMA_VERSION,
    "title": "Compact Routed Tank Pump Exchanger Skid",
    "units": "mm",
    "assumptions": ["Used logical pipe connections for clear equipment-to-equipment routed pipes."],
    "components": [
        {
            "component_type": "skid_base_3d",
            "id": "SKID101",
            "center": [1200, 0, -100],
            "length": 5200,
            "width": 2200,
            "height": 200,
        },
        {
            "component_type": "vertical_tank_3d",
            "id": "T101",
            "tag": "T-101",
            "center": [-1200, -550, 900],
            "diameter": 900,
            "height": 1800,
        },
        {
            "component_type": "pump_placeholder_3d",
            "id": "P101",
            "tag": "P-101",
            "center": [300, -550, 300],
            "length": 800,
            "width": 450,
            "height": 500,
        },
        {
            "component_type": "heat_exchanger_3d",
            "id": "E101",
            "tag": "E-101",
            "center": [2100, -550, 650],
            "length": 1800,
            "diameter": 500,
            "orientation": "X",
        },
        {
            "component_type": "pipe_connection_3d",
            "id": "PIPE_T101_P101",
            "from_port": "T101.side_right",
            "to_port": "P101.suction",
            "diameter": 100,
            "routing_style": "orthogonal",
            "clearance": 400,
        },
        {
            "component_type": "pipe_connection_3d",
            "id": "PIPE_P101_E101",
            "from_port": "P101.discharge",
            "to_port": "E101.inlet",
            "diameter": 100,
            "routing_style": "orthogonal",
            "clearance": 400,
        },
        {
            "component_type": "label_3d",
            "id": "LBL_T101",
            "text": "T-101",
            "position": [-1500, -50, 1950],
            "height": 170,
        },
        {
            "component_type": "label_3d",
            "id": "LBL_P101",
            "text": "P-101",
            "position": [0, -1050, 850],
            "height": 160,
        },
        {
            "component_type": "label_3d",
            "id": "LBL_E101",
            "text": "E-101",
            "position": [1700, -1050, 1100],
            "height": 170,
        },
    ],
}


def build_cad3d_planner_prompt(
    user_request: str,
    drawing_style: str = "simple clean 3D equipment layout",
) -> str:
    supported_types = "\n".join(f"- {component_type}" for component_type in _SUPPORTED_COMPONENT_TYPES)
    example_json = json.dumps(_EXAMPLE_CAD3D_SCENE, indent=2)

    return "\n".join(
        [
            "Original user 3D CAD request:",
            user_request,
            "",
            "Requested drawing style:",
            drawing_style,
            "",
            "Supported component types:",
            supported_types,
            "",
            "Coordinate and layout guidance:",
            "- Use millimeters.",
            "- Keep major equipment on or above a skid/base where appropriate.",
            "- Place tanks/vessels with clear spacing and simple orthogonal pipe paths.",
            "- Use readable label_3d components near each major tagged item.",
            "- Use pipe_connection_3d for clear equipment-to-equipment pipe routes.",
            "- Use pipe_run_3d centerline placeholders for headers, vents, drains, bypasses, and custom free-form paths.",
            "- Use heat_exchanger_3d when the prompt mentions exchanger, cooler, heater, or thermal equipment.",
            "- Use valve_placeholder_3d for valves and control/check/gate valve placeholders.",
            "- Use flange_3d around equipment nozzles or pipe joints where useful.",
            "- Use support_leg_3d, saddle_support_3d, and pipe_support_3d for equipment and pipe support.",
            "- Use nozzle_3d for vessel and tank nozzles when useful.",
            "- Use assumptions for inferred layout or simplifications.",
            "- Prefer 8-35 components for normal prompts.",
            "- Return CAD3D scene JSON only, not AutoCAD command JSON.",
            "",
            "Design family hints:",
            "- tank pump separator: vertical tank, pump, horizontal separator, skid, connecting pipes.",
            "- dual pump skid: two pumps, suction header, discharge header, valves, flanges, pipe supports.",
            "- heat exchanger skid: pump, heat exchanger, inlet/outlet piping, bypass, valves, flanges.",
            "- vertical scrubber package: vertical vessel, gas inlet/outlet, vent, drain, support legs.",
            "- extended process unit: tank, pump, heat exchanger, separator, valves, flanges, supports.",
            "",
            *_PIPE_ROUTING_RULES,
            "",
            *_KNOWN_PORT_EXAMPLES,
            "",
            *_PIPE_CONNECTION_EXAMPLES,
            "",
            "Compact example CAD3D scene JSON:",
            example_json,
            "",
            "Return one complete CAD3D scene JSON object matching the provided schema.",
        ]
    )


def _validate_scene_or_raise(scene_data: dict) -> None:
    validation_errors = validate_cad3d_scene(scene_data)
    if validation_errors:
        joined_errors = "\n".join(f"- {error}" for error in validation_errors)
        raise ValueError(f"CAD3D scene failed validation:\n{joined_errors}")


def plan_cad3d_scene(
    user_request: str,
    drawing_style: str = "simple clean 3D equipment layout",
) -> dict:
    """Plan a validated CAD3D scene from a natural-language request."""
    clean_request = user_request.strip()
    if not clean_request:
        raise ValueError("user_request cannot be empty")

    clean_style = drawing_style.strip() if drawing_style else "simple clean 3D equipment layout"
    planner_prompt = build_cad3d_planner_prompt(clean_request, clean_style)

    result = ask_ai(
        prompt=planner_prompt,
        schema=CAD3D_SCENE_SCHEMA,
        system_prompt=CAD3D_SCENE_PLANNER_SYSTEM_PROMPT,
        max_retries=2,
        max_tokens=CAD3D_SCENE_PLANNER_MAX_TOKENS,
    )

    if not isinstance(result, dict):
        raise ValueError("CAD3D scene result must be a dict")

    result.setdefault("schema_version", CAD3D_SCENE_SCHEMA_VERSION)
    _validate_scene_or_raise(result)

    metadata = result.setdefault("metadata", {})
    metadata["planner_strategy"] = "ai_cad3d_scene_planner"
    metadata["fallback_used"] = False

    return result


def plan_cad3d_scene_resilient(
    user_request: str,
    drawing_style: str = "simple clean 3D equipment layout",
    allow_example_fallback: bool = True,
) -> dict:
    """Plan a CAD3D scene, falling back to a deterministic design template if AI fails."""
    clean_request = user_request.strip()
    if not clean_request:
        raise ValueError("user_request cannot be empty")

    try:
        scene_data = plan_cad3d_scene(clean_request, drawing_style=drawing_style)
    except Exception as exc:
        if not allow_example_fallback:
            raise

        template_name, scene_data = choose_cad3d_template(clean_request)
        scene_data.setdefault("assumptions", []).append(
            "AI 3D planner failed, so a deterministic 3D design template was used."
        )
        metadata = scene_data.setdefault("metadata", {})
        metadata["planner_strategy"] = "template_fallback"
        metadata["fallback_used"] = True
        metadata["fallback_template_name"] = template_name
        metadata["fallback_example_name"] = template_name
        metadata["fallback_reason"] = f"{type(exc).__name__}: {exc}"
        metadata["ai_planner_attempted"] = True
        metadata["ai_planner_error_type"] = type(exc).__name__
        metadata["ai_planner_error"] = str(exc)
        return scene_data

    metadata = scene_data.setdefault("metadata", {})
    metadata["planner_strategy"] = "ai_cad3d_scene_planner"
    metadata["fallback_used"] = False
    metadata["ai_planner_attempted"] = True
    metadata["ai_planner_error_type"] = None
    metadata["ai_planner_error"] = None
    return scene_data

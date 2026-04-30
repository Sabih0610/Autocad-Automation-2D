"""AI planner for component-based P&ID scenes.

This module plans structured P&ID component scene JSON only. It does not
generate raw AutoCAD commands directly, execute AutoCAD, expose API routes, or
modify drawings.
"""

from __future__ import annotations

import json
from typing import Any

from src.ai.client import ask_ai
from src.framework.commands.schema import validate_command_sequence
from src.framework.pid.component_builder import render_pid_component_scene_data
from src.framework.pid.component_schema import (
    PID_COMPONENT_SCHEMA_VERSION,
    PID_COMPONENT_SCENE_SCHEMA,
    validate_pid_component_scene_data,
)
from src.framework.pid.component_templates import choose_pid_component_template


_SUPPORTED_COMPONENT_TYPES = [
    "horizontal_vessel",
    "vertical_vessel",
    "pipe_run",
    "signal_line",
    "gate_valve",
    "control_valve",
    "instrument_bubble",
    "controller_loop",
    "label",
    "flow_arrow",
    "leader_line",
]


PID_COMPONENT_PLANNER_MAX_TOKENS = 5000


_EXAMPLE_COMPONENT_SCENE: dict[str, Any] = {
    "schema_version": PID_COMPONENT_SCHEMA_VERSION,
    "title": "Simple Vessel P&ID",
    "drawing_type": "P&ID",
    "assumptions": ["Used clean schematic layout."],
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
            "flow_arrow_position": [-2400, 0],
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
    ],
}


PID_COMPONENT_PLANNER_SYSTEM_PROMPT = f"""
You are a P&ID component scene planner, not an AutoCAD command generator.

Rules:
- Output JSON only.
- Output must match the provided P&ID component scene schema.
- Do not output raw AutoCAD commands.
- Do not output markdown.
- Do not output Python code.
- Use only supported component types:
  - horizontal_vessel
  - vertical_vessel
  - pipe_run
  - signal_line
  - gate_valve
  - control_valve
  - instrument_bubble
  - controller_loop
  - label
  - flow_arrow
  - leader_line
- Always include schema_version "{PID_COMPONENT_SCHEMA_VERSION}".
- All coordinates are in millimeters.
- Keep layout clean and orthogonal.
- Use reasonable fixed coordinates.
- Keep major equipment centered.
- Put labels away from lines and equipment.
- Use pipe_run components for pipes.
- Use valve components instead of drawing valve geometry.
- Use instrument_bubble components for instrument tags.
- Use controller_loop or signal_line components for control relationships.
- Use flow_arrow components to show flow direction.
- Use assumptions for anything inferred.
- For complex requests, simplify safely but preserve core requested equipment,
  lines, instruments, and labels.
- Prefer component scenes with 8 to 35 components.
- Do not create extremely huge drawings.
- Do not use unsupported component types.
- Do not include extra fields not in the schema.

Layout guidance:
- Horizontal vessel separator: center vessel around [0, 0], inlet from left,
  vapor outlet upper/right, oil outlet lower/right, water outlet lower/left.
- Vertical vessel: center vessel around [0, 0], feed inlet from left, top
  vapor outlet, bottom liquid outlet.
- Pump/tank: tank left, pump or pump label center/right, discharge to right.

Component ID guidance:
- Equipment: V201, V301, T101.
- Pipes: P_IN, P_OUT, P_VAPOR, P_OIL, P_WATER.
- Valves: XV_IN, XV_OUT, CV_OIL, LV_OUT.
- Instruments: PI201, PT201, LT201, LC201.
- Labels: LBL_TITLE, LBL_INLET, LBL_OUTLET.
""".strip()


def _build_planner_prompt(user_request: str, drawing_style: str) -> str:
    supported_types = "\n".join(f"- {component_type}" for component_type in _SUPPORTED_COMPONENT_TYPES)
    example_json = json.dumps(_EXAMPLE_COMPONENT_SCENE, indent=2)

    return "\n".join(
        [
            "Original user P&ID request:",
            user_request,
            "",
            "Requested drawing style:",
            drawing_style,
            "",
            "Supported component types:",
            supported_types,
            "",
            "Layout rules:",
            "- Use millimeters.",
            "- Keep major equipment near the center of the drawing.",
            "- Route pipes orthogonally where possible.",
            "- Place labels offset from pipe runs and equipment outlines.",
            "- Prefer 8 to 35 components for normal P&ID requests.",
            "- Use assumptions for inferred process details.",
            "- Return component scene JSON only, not AutoCAD command JSON.",
            "",
            "Compact example component scene JSON:",
            example_json,
            "",
            "Return one complete component scene JSON object matching the provided schema.",
        ]
    )


def plan_pid_component_scene(
    user_request: str,
    drawing_style: str = "clean schematic P&ID",
) -> dict:
    """Plan a validated P&ID component scene from a natural-language request."""
    clean_request = user_request.strip()
    if not clean_request:
        raise ValueError("user_request cannot be empty")

    clean_style = drawing_style.strip() if drawing_style else "clean schematic P&ID"
    planner_prompt = _build_planner_prompt(clean_request, clean_style)

    result = ask_ai(
        prompt=planner_prompt,
        schema=PID_COMPONENT_SCENE_SCHEMA,
        system_prompt=PID_COMPONENT_PLANNER_SYSTEM_PROMPT,
        max_retries=2,
        max_tokens=PID_COMPONENT_PLANNER_MAX_TOKENS,
    )

    if not isinstance(result, dict):
        raise ValueError("P&ID component scene result must be a dict")

    result.setdefault("schema_version", PID_COMPONENT_SCHEMA_VERSION)

    validation_errors = validate_pid_component_scene_data(result)
    if validation_errors:
        joined_errors = "\n".join(f"- {error}" for error in validation_errors)
        raise ValueError(f"P&ID component scene failed validation:\n{joined_errors}")

    return result


def plan_and_render_pid_component_scene(
    user_request: str,
    drawing_style: str = "clean schematic P&ID",
) -> dict:
    """Plan a P&ID component scene and render it to validated command JSON."""
    scene_data = plan_pid_component_scene(user_request, drawing_style=drawing_style)
    command_sequence = render_pid_component_scene_data(scene_data)

    command_errors = validate_command_sequence(command_sequence)
    if command_errors:
        joined_errors = "\n".join(f"- {error}" for error in command_errors)
        raise ValueError(f"Rendered P&ID command sequence failed validation:\n{joined_errors}")

    return {
        "ok": True,
        "component_scene": scene_data,
        "command_sequence": command_sequence,
        "component_count": len(scene_data["components"]),
    }


def plan_pid_component_scene_resilient(
    user_request: str,
    drawing_style: str = "clean schematic P&ID",
    allow_template_fallback: bool = True,
    template_first: bool = False,
) -> dict:
    """Plan a component scene, falling back to deterministic templates if AI fails."""
    clean_request = user_request.strip()
    if not clean_request:
        raise ValueError("user_request cannot be empty")

    if template_first:
        template_name, scene_data = choose_pid_component_template(clean_request)
        metadata = scene_data.setdefault("metadata", {})
        metadata["planner_strategy"] = "template_selected"
        metadata["fallback_used"] = False
        metadata["template_name"] = template_name
        metadata["ai_planner_attempted"] = False
        metadata["ai_planner_error_type"] = None
        metadata["ai_planner_error"] = None
        return scene_data

    try:
        scene_data = plan_pid_component_scene(clean_request, drawing_style=drawing_style)
    except Exception as exc:
        if not allow_template_fallback:
            raise

        template_name, scene_data = choose_pid_component_template(clean_request)
        scene_data.setdefault("assumptions", []).append(
            (
                "AI component planner failed, so a deterministic template fallback "
                "was used. Review and edit the result as needed."
            )
        )
        metadata = scene_data.setdefault("metadata", {})
        metadata["planner_strategy"] = "template_fallback"
        metadata["fallback_used"] = True
        metadata["fallback_reason"] = f"{type(exc).__name__}: {exc}"
        metadata["template_name"] = template_name
        metadata["ai_planner_attempted"] = True
        metadata["ai_planner_error_type"] = type(exc).__name__
        metadata["ai_planner_error"] = str(exc)
        return scene_data

    metadata = scene_data.setdefault("metadata", {})
    metadata["planner_strategy"] = "ai_component_planner"
    metadata["fallback_used"] = False
    metadata["ai_planner_attempted"] = True
    metadata["ai_planner_error_type"] = None
    metadata["ai_planner_error"] = None
    return scene_data


def plan_and_render_pid_component_scene_resilient(
    user_request: str,
    drawing_style: str = "clean schematic P&ID",
    allow_template_fallback: bool = True,
    template_first: bool = False,
) -> dict:
    """Plan with fallback and render to validated command sequence JSON."""
    scene_data = plan_pid_component_scene_resilient(
        user_request,
        drawing_style=drawing_style,
        allow_template_fallback=allow_template_fallback,
        template_first=template_first,
    )
    command_sequence = render_pid_component_scene_data(scene_data)

    command_errors = validate_command_sequence(command_sequence)
    if command_errors:
        joined_errors = "\n".join(f"- {error}" for error in command_errors)
        raise ValueError(f"Rendered P&ID command sequence failed validation:\n{joined_errors}")

    metadata = scene_data.get("metadata", {})
    return {
        "ok": True,
        "component_scene": scene_data,
        "command_sequence": command_sequence,
        "component_count": len(scene_data["components"]),
        "planner_strategy": metadata.get("planner_strategy"),
        "fallback_used": metadata.get("fallback_used", False),
        "fallback_reason": metadata.get("fallback_reason"),
        "template_name": metadata.get("template_name"),
    }

"""AI and deterministic planner for CAD3D scene-level edit plans."""

from __future__ import annotations

import json
import re
from typing import Any

from src.ai.client import ask_ai
from src.framework.cad3d.edit_schema import validate_cad3d_edit_plan
from src.framework.cad3d.scene_editor import CAD3DSceneEditError


CAD3D_EDIT_PLANNER_SYSTEM_PROMPT = """
You are a CAD3D scene edit planner.

Return only JSON. Do not return markdown or prose.
Do not edit AutoCAD entities, handles, or raw geometry.
Edit CAD3D scene components by ID.

Use operation types:
- move_component
- update_component
- add_component
- delete_component

Rules:
- Use component IDs from the current scene.
- For tags with dashes, map tag P-101 to component id P101 when available.
- Use 3D coordinates [x, y, z].
- right = +X
- left = -X
- forward = +Y
- backward = -Y
- up = +Z
- down = -Z
- Use millimeters.
- Do not modify id or component_type.
- If adding pipe connections, use pipe_connection_3d when clear.
- If deleting a component, connected pipes may be removed by the scene editor.
""".strip()


CAD3D_EDIT_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": True,
    "required": ["schema_version", "edit_intent", "summary", "operations"],
    "properties": {
        "schema_version": {"const": "1.0"},
        "edit_intent": {"type": "string"},
        "summary": {"type": "string"},
        "operations": {"type": "array", "minItems": 1},
        "metadata": {"type": "object"},
    },
}


def summarize_scene_for_edit_prompt(scene: dict) -> list[dict]:
    summary = []
    key_dimension_fields = [
        "length",
        "width",
        "height",
        "diameter",
        "orientation",
        "thickness",
        "valve_type",
    ]
    for component in scene.get("components", []):
        item = {
            "id": component.get("id"),
            "tag": component.get("tag"),
            "component_type": component.get("component_type"),
        }
        if "center" in component:
            item["center"] = component["center"]
        if "position" in component:
            item["position"] = component["position"]
        if "points" in component:
            item["points"] = component["points"]
        for field_name in key_dimension_fields:
            if field_name in component:
                item[field_name] = component[field_name]
        summary.append(item)
    return summary


def build_cad3d_edit_planner_prompt(user_request: str, scene: dict) -> str:
    components = summarize_scene_for_edit_prompt(scene)
    example_plan = {
        "schema_version": "1.0",
        "edit_intent": "Move pump P-101 1000 mm to the right.",
        "summary": "Move P101 along positive X.",
        "operations": [
            {
                "operation_type": "move_component",
                "component_id": "P101",
                "delta": [1000, 0, 0],
            }
        ],
        "metadata": {},
    }
    return "\n".join(
        [
            "User CAD3D edit request:",
            user_request,
            "",
            "Current CAD3D components:",
            json.dumps(components, indent=2),
            "",
            "Supported operations:",
            "- move_component: component_id plus delta or new_center",
            "- update_component: component_id plus updates",
            "- add_component: component",
            "- delete_component: component_id",
            "",
            "Direction mapping:",
            "- right = +X",
            "- left = -X",
            "- forward = +Y",
            "- backward = -Y",
            "- up = +Z",
            "- down = -Z",
            "",
            "Return one CAD3D edit plan JSON object.",
            "Example:",
            json.dumps(example_plan, indent=2),
        ]
    )


def plan_cad3d_edit(user_request: str, scene: dict) -> dict:
    clean_request = user_request.strip()
    if not clean_request:
        raise ValueError("user_request cannot be empty")

    prompt = build_cad3d_edit_planner_prompt(clean_request, scene)
    result = ask_ai(
        prompt=prompt,
        schema=CAD3D_EDIT_PLAN_SCHEMA,
        system_prompt=CAD3D_EDIT_PLANNER_SYSTEM_PROMPT,
        max_retries=2,
        max_tokens=2000,
    )
    plan = validate_cad3d_edit_plan(result)
    _validate_edit_plan_references_scene(plan, scene)
    return plan


def _validate_edit_plan_references_scene(plan: dict, scene: dict) -> None:
    component_ids = {
        component.get("id")
        for component in scene.get("components", [])
        if component.get("id")
    }
    for operation in plan.get("operations", []):
        if operation.get("operation_type") == "add_component":
            continue
        component_id = operation.get("component_id")
        if component_id and component_id not in component_ids:
            raise CAD3DSceneEditError(
                f"Edit plan references missing CAD3D component: {component_id}"
            )


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _normalize_identifier(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def _component_matches(component: dict, normalized_request: str, compact_request: str) -> bool:
    component_id = str(component.get("id") or "")
    tag = str(component.get("tag") or "")
    if component_id and _normalize_identifier(component_id) in compact_request:
        return True
    if tag and tag.lower() in normalized_request:
        return True
    if tag and _normalize_identifier(tag) in compact_request:
        return True
    return False


def _generic_type_candidates(scene: dict, normalized_request: str) -> list[dict]:
    type_words = {
        "pump": {"pump_placeholder_3d"},
        "tank": {"vertical_tank_3d"},
        "vessel": {"horizontal_vessel_3d", "vertical_tank_3d"},
        "separator": {"horizontal_vessel_3d"},
        "exchanger": {"heat_exchanger_3d"},
        "valve": {"valve_placeholder_3d"},
    }
    matched_types: set[str] = set()
    for word, component_types in type_words.items():
        if word in normalized_request:
            matched_types.update(component_types)
    if not matched_types:
        return []
    return [
        component
        for component in scene.get("components", [])
        if component.get("component_type") in matched_types
    ]


def _find_component_for_request(user_request: str, scene: dict) -> dict:
    normalized_request = _normalize_text(user_request)
    compact_request = _normalize_identifier(user_request)

    explicit_matches = [
        component
        for component in scene.get("components", [])
        if _component_matches(component, normalized_request, compact_request)
    ]
    if len(explicit_matches) == 1:
        return explicit_matches[0]
    if len(explicit_matches) > 1:
        exact_id_matches = [
            component
            for component in explicit_matches
            if _normalize_identifier(component.get("id")) in compact_request
        ]
        if len(exact_id_matches) == 1:
            return exact_id_matches[0]

    generic_matches = _generic_type_candidates(scene, normalized_request)
    if len(generic_matches) == 1:
        return generic_matches[0]

    raise CAD3DSceneEditError("Could not determine which CAD3D component to edit")


def _parse_move_delta(user_request: str) -> list[float] | None:
    normalized = _normalize_text(user_request)
    direction_vectors = {
        "right": [1.0, 0.0, 0.0],
        "left": [-1.0, 0.0, 0.0],
        "forward": [0.0, 1.0, 0.0],
        "backward": [0.0, -1.0, 0.0],
        "up": [0.0, 0.0, 1.0],
        "down": [0.0, 0.0, -1.0],
    }
    patterns = [
        r"(?P<distance>\d+(?:\.\d+)?)\s*(?:mm)?\s*(?:to\s+the\s+)?(?P<direction>right|left|forward|backward|up|down)",
        r"(?P<direction>right|left|forward|backward|up|down)\s+(?P<distance>\d+(?:\.\d+)?)\s*(?:mm)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        distance = float(match.group("distance"))
        vector = direction_vectors[match.group("direction")]
        return [value * distance for value in vector]
    return None


def _parse_dimension_update(user_request: str) -> tuple[str, float] | None:
    normalized = _normalize_text(user_request)
    fields = "length|width|height|diameter"
    patterns = [
        rf"(?:change|set|increase)\b.*?\b(?P<field>{fields})\b\s+(?:to\s+)?(?P<value>\d+(?:\.\d+)?)\s*(?:mm)?",
        rf"\b(?P<field>{fields})\b\s+(?:to\s+)?(?P<value>\d+(?:\.\d+)?)\s*(?:mm)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            return match.group("field"), float(match.group("value"))
    return None


def deterministic_edit_plan_from_request(user_request: str, scene: dict) -> dict:
    clean_request = user_request.strip()
    normalized = _normalize_text(clean_request)

    if re.search(r"\b(move|shift)\b", normalized):
        component = _find_component_for_request(clean_request, scene)
        delta = _parse_move_delta(clean_request)
        if delta is None:
            raise CAD3DSceneEditError("Could not parse move distance and direction")
        return validate_cad3d_edit_plan(
            {
                "schema_version": "1.0",
                "edit_intent": clean_request,
                "summary": f"Move {component['id']} by {delta}.",
                "operations": [
                    {
                        "operation_type": "move_component",
                        "component_id": component["id"],
                        "delta": delta,
                    }
                ],
                "metadata": {"planner_strategy": "deterministic_edit_fallback"},
            }
        )

    if re.search(r"\b(delete|remove)\b", normalized):
        component = _find_component_for_request(clean_request, scene)
        return validate_cad3d_edit_plan(
            {
                "schema_version": "1.0",
                "edit_intent": clean_request,
                "summary": f"Delete {component['id']}.",
                "operations": [
                    {
                        "operation_type": "delete_component",
                        "component_id": component["id"],
                    }
                ],
                "metadata": {"planner_strategy": "deterministic_edit_fallback"},
            }
        )

    dimension_update = _parse_dimension_update(clean_request)
    if dimension_update is not None:
        component = _find_component_for_request(clean_request, scene)
        field_name, value = dimension_update
        return validate_cad3d_edit_plan(
            {
                "schema_version": "1.0",
                "edit_intent": clean_request,
                "summary": f"Set {component['id']} {field_name} to {value}.",
                "operations": [
                    {
                        "operation_type": "update_component",
                        "component_id": component["id"],
                        "updates": {field_name: value},
                    }
                ],
                "metadata": {"planner_strategy": "deterministic_edit_fallback"},
            }
        )

    raise CAD3DSceneEditError("No deterministic CAD3D edit fallback matched the request")


def plan_cad3d_edit_resilient(
    user_request: str,
    scene: dict,
    allow_fallback: bool = True,
) -> dict:
    try:
        plan = plan_cad3d_edit(user_request, scene)
    except Exception as exc:
        if not allow_fallback:
            raise
        fallback_plan = deterministic_edit_plan_from_request(user_request, scene)
        metadata = fallback_plan.setdefault("metadata", {})
        metadata["planner_strategy"] = "deterministic_edit_fallback"
        metadata["fallback_used"] = True
        metadata["ai_planner_attempted"] = True
        metadata["ai_planner_error_type"] = type(exc).__name__
        metadata["ai_planner_error"] = str(exc)
        return validate_cad3d_edit_plan(fallback_plan)

    metadata = plan.setdefault("metadata", {})
    metadata["planner_strategy"] = "ai_cad3d_edit_planner"
    metadata["fallback_used"] = False
    metadata["ai_planner_attempted"] = True
    metadata["ai_planner_error_type"] = None
    metadata["ai_planner_error"] = None
    return validate_cad3d_edit_plan(plan)

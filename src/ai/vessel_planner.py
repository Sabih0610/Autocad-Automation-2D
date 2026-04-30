"""
AI parameter extraction for horizontal pressure vessels.

Phase 20:
- Convert a natural-language vessel request into structured JSON.
- Convert extracted JSON into VesselParameters.
- Format extracted values for user review before rendering.

Important:
AI does NOT draw CAD.
AI only extracts parameters.
The deterministic generator validates and renders the drawing.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from src.ai.client import ask_ai
from src.parametric.vessel.parameters import (
    HeadType,
    Nozzle,
    NozzlePosition,
    Orientation,
    Saddle,
    VesselParameters,
)


VESSEL_PARAMETER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "tag",
        "internal_diameter_mm",
        "tangent_to_tangent_mm",
        "head_type",
        "orientation",
        "wall_thickness_mm",
        "nozzles",
        "saddles",
        "assumptions",
    ],
    "properties": {
        "tag": {
            "type": "string",
            "minLength": 1,
            "description": "Vessel tag like V-201, T-101, etc.",
        },
        "internal_diameter_mm": {
            "type": "number",
            "minimum": 100,
            "maximum": 10000,
            "description": "Internal diameter in millimeters.",
        },
        "tangent_to_tangent_mm": {
            "type": "number",
            "minimum": 200,
            "maximum": 30000,
            "description": "Distance between left and right tangent lines in mm.",
        },
        "wall_thickness_mm": {
            "type": "number",
            "minimum": 1,
            "maximum": 200,
            "description": "Shell wall thickness in mm. Default 10 if unspecified.",
        },
        "head_type": {
            "type": "string",
            "enum": ["ELLIPSOIDAL_2_1"],
            "description": "Only 2:1 ellipsoidal heads are supported in this phase.",
        },
        "orientation": {
            "type": "string",
            "enum": ["HORIZONTAL"],
            "description": "Only horizontal vessels are supported in this phase.",
        },
        "nozzles": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "tag",
                    "nominal_size_inches",
                    "position",
                    "axial_position_mm",
                ],
                "properties": {
                    "tag": {
                        "type": "string",
                        "minLength": 1,
                    },
                    "nominal_size_inches": {
                        "type": "number",
                        "enum": [1, 1.5, 2, 3, 4, 6, 8, 10, 12],
                    },
                    "position": {
                        "type": "string",
                        "enum": [
                            "TOP",
                            "BOTTOM",
                            "LEFT_END",
                            "RIGHT_END",
                            "SIDE_FRONT",
                            "SIDE_BACK",
                        ],
                    },
                    "axial_position_mm": {
                        "type": "number",
                        "minimum": 0,
                    },
                    "radial_angle_degrees": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 360,
                    },
                },
            },
        },
        "saddles": {
            "type": "array",
            "description": "Optional. Use [] if not specified. Geometry layer fills defaults.",
            "items": {
                "type": "object",
                "required": ["axial_position_mm"],
                "properties": {
                    "axial_position_mm": {
                        "type": "number",
                        "minimum": 0,
                    },
                    "width_mm": {
                        "type": "number",
                        "minimum": 50,
                    },
                    "height_mm": {
                        "type": "number",
                        "minimum": 50,
                    },
                },
            },
        },
        "assumptions": {
            "type": "array",
            "description": "Every default, inference, or estimate made by the AI.",
            "items": {
                "type": "string",
            },
        },
    },
}


VESSEL_EXTRACTION_SYSTEM_PROMPT = """
You are a parameter extractor for horizontal pressure vessel drawings.

Your job:
Read the user's request and output one JSON object matching the provided schema.

You do not design vessels.
You do not validate engineering.
You do not draw CAD.
You only translate the user's words into structured data.

UNIT CONVERSION:
- All vessel length values must be in millimeters.
- If the user gives meters, convert to mm.
- If the user gives inches or feet for vessel dimensions, convert to mm.
- Nozzle nominal sizes stay in inches.

DEFAULTS:
Use these only if the user did not specify the value:
- head_type: ELLIPSOIDAL_2_1
- orientation: HORIZONTAL
- wall_thickness_mm: 10
- saddles: []
- radial_angle_degrees: 0 for SIDE_FRONT or SIDE_BACK nozzles

NOZZLE POSITION INTERPRETATION:
- "top" or "top center" means TOP
- "bottom" or "bottom center" means BOTTOM
- "side", "on the side", or "level instrument" means SIDE_FRONT by default
- "left end", "feed end", or "inlet head" means LEFT_END
- "right end", "discharge end", or "outlet head" means RIGHT_END

AXIAL POSITION INTERPRETATION:
- "center", "middle", or "midpoint" means tangent_to_tangent_mm / 2
- "top center" means TOP at tangent_to_tangent_mm / 2
- "bottom center" means BOTTOM at tangent_to_tangent_mm / 2
- "side center" means SIDE_FRONT at tangent_to_tangent_mm / 2
- "near left end" or "near inlet end" means 500 mm from left tangent
- "near right end" or "near discharge end" means tangent_to_tangent_mm - 500
- "relief valve", "PSV", "safety valve", or "vent" on TOP with no axial position means TOP at 500 mm from left tangent.
- If a nozzle axial position is completely unspecified, use midpoint and add an assumption.
- Do not place two nozzles on the same surface at the same axial position unless the user explicitly says they are at the same location.
- If two nozzles would duplicate the same surface and axial position, move the later unspecified nozzle to a nearby clear axial position and list that as an assumption.

NOZZLE TAGS:
- If nozzle tags are not provided, generate N1, N2, N3, ... in the order nozzles appear.
- Do not invent extra nozzles.

ASSUMPTIONS:
- Every default, inference, or estimate must be listed in the assumptions array.
- If wall thickness was defaulted, mention it.
- If head type was defaulted, mention it.
- If orientation was defaulted, mention it.
- If axial position was inferred, mention it.
- If radial angle was defaulted, mention it.
- If saddles are defaulted by the geometry layer, mention it.
- If a duplicate nozzle location was avoided by choosing a clearer location, mention it.
- If there are no assumptions, return an empty array.

OUTPUT RULES:
- Output only one JSON object.
- No markdown.
- No code fences.
- No explanations outside JSON.
""".strip()


def _enum_from_name_or_value(enum_cls, raw_value: str):
    """
    Convert an AI string to an enum value.

    Supports:
    - enum member name, e.g. TOP
    - enum value, e.g. top
    - case-insensitive match
    """
    raw = str(raw_value).strip()

    try:
        return enum_cls(raw)
    except Exception:
        pass

    try:
        return enum_cls[raw]
    except Exception:
        pass

    raw_upper = raw.upper()
    raw_lower = raw.lower()

    for member in enum_cls:
        if member.name.upper() == raw_upper:
            return member
        if str(member.value).lower() == raw_lower:
            return member
        if str(member.value).replace("-", "_").upper() == raw_upper:
            return member

    raise ValueError(f"Unsupported {enum_cls.__name__} value: {raw_value}")


def _append_assumption(extracted: dict[str, Any], message: str) -> None:
    """Append an assumption message if it is not already present."""
    assumptions = extracted.setdefault("assumptions", [])

    if message not in assumptions:
        assumptions.append(message)


def _normalize_extracted_defaults(extracted: dict[str, Any]) -> dict[str, Any]:
    """
    Make the AI output safe for downstream conversion.

    This does not replace validate_parameters().
    It only fills optional/default fields that the schema expects.
    """
    cleaned = deepcopy(extracted)

    if "head_type" not in cleaned:
        cleaned["head_type"] = "ELLIPSOIDAL_2_1"
        _append_assumption(
            cleaned,
            "head_type defaulted to ELLIPSOIDAL_2_1 because it was not specified.",
        )

    if "orientation" not in cleaned:
        cleaned["orientation"] = "HORIZONTAL"
        _append_assumption(
            cleaned,
            "orientation defaulted to HORIZONTAL because it was not specified.",
        )

    if "wall_thickness_mm" not in cleaned:
        cleaned["wall_thickness_mm"] = 10.0
        _append_assumption(
            cleaned,
            "wall_thickness_mm defaulted to 10 mm because it was not specified.",
        )

    if "saddles" not in cleaned or cleaned["saddles"] is None:
        cleaned["saddles"] = []
        _append_assumption(
            cleaned,
            "saddles not specified; geometry layer will apply default saddle positions.",
        )

    if "assumptions" not in cleaned or cleaned["assumptions"] is None:
        cleaned["assumptions"] = []

    for nozzle in cleaned.get("nozzles", []):
        if "radial_angle_degrees" not in nozzle:
            nozzle["radial_angle_degrees"] = 0.0

            if nozzle.get("position") in {"SIDE_FRONT", "SIDE_BACK"}:
                _append_assumption(
                    cleaned,
                    f"{nozzle.get('tag', 'Nozzle')} radial_angle_degrees defaulted to 0.",
                )

    return cleaned


def _location_key(nozzle: dict[str, Any]) -> tuple[str, float, float]:
    """Build a duplicate-detection key similar to validate_parameters()."""
    position = str(nozzle.get("position", "")).upper()
    axial = round(float(nozzle.get("axial_position_mm", 0.0)), 3)
    radial = round(float(nozzle.get("radial_angle_degrees", 0.0)), 3)

    return (position, axial, radial)


def _find_clear_axial_position(
    occupied: set[tuple[str, float, float]],
    position: str,
    current_axial: float,
    tangent_length: float,
    radial: float = 0.0,
) -> float:
    """
    Pick a simple clear axial position for an unspecified duplicate nozzle.

    This is not engineering design. It is only a safe extraction fallback that
    avoids exact duplicate locations before deterministic validation.
    """
    midpoint = tangent_length / 2.0

    candidates = [
        500.0,
        tangent_length - 500.0,
        midpoint - 500.0,
        midpoint + 500.0,
        tangent_length * 0.25,
        tangent_length * 0.75,
        current_axial - 500.0,
        current_axial + 500.0,
    ]

    for candidate in candidates:
        if candidate < 0.0 or candidate > tangent_length:
            continue

        key = (
            position,
            round(float(candidate), 3),
            round(float(radial), 3),
        )

        if key not in occupied:
            return float(candidate)

    # Last fallback: scan every 250 mm.
    step = 250.0
    candidate = 0.0

    while candidate <= tangent_length:
        key = (
            position,
            round(float(candidate), 3),
            round(float(radial), 3),
        )

        if key not in occupied:
            return float(candidate)

        candidate += step

    return float(current_axial)


def _repair_duplicate_nozzle_locations(
    extracted: dict[str, Any],
    user_request: str,
) -> dict[str, Any]:
    """
    Avoid exact duplicate nozzle locations from the AI output.

    The validator still remains the final authority. This function only repairs
    obvious extraction mistakes, like two TOP nozzles both defaulting to midpoint.
    """
    cleaned = deepcopy(extracted)

    tangent_length = float(cleaned.get("tangent_to_tangent_mm", 0.0))
    nozzles = cleaned.get("nozzles", [])

    if tangent_length <= 0 or not nozzles:
        return cleaned

    occupied: set[tuple[str, float, float]] = set()
    request_lower = user_request.lower()

    relief_terms_present = any(
        term in request_lower
        for term in ["relief", "psv", "safety valve", "vent"]
    )

    for nozzle in nozzles:
        nozzle.setdefault("radial_angle_degrees", 0.0)

        key = _location_key(nozzle)

        if key not in occupied:
            occupied.add(key)
            continue

        old_axial = float(nozzle["axial_position_mm"])
        position = str(nozzle["position"]).upper()
        radial = float(nozzle.get("radial_angle_degrees", 0.0))

        if position == "TOP" and relief_terms_present:
            new_axial = 500.0
            new_key = (
                position,
                round(new_axial, 3),
                round(radial, 3),
            )

            if new_key in occupied:
                new_axial = _find_clear_axial_position(
                    occupied=occupied,
                    position=position,
                    current_axial=old_axial,
                    tangent_length=tangent_length,
                    radial=radial,
                )
        else:
            new_axial = _find_clear_axial_position(
                occupied=occupied,
                position=position,
                current_axial=old_axial,
                tangent_length=tangent_length,
                radial=radial,
            )

        nozzle["axial_position_mm"] = float(new_axial)

        _append_assumption(
            cleaned,
            (
                f"{nozzle.get('tag', 'Nozzle')} axial_position_mm moved "
                f"from {old_axial:g} mm to {new_axial:g} mm to avoid a duplicate "
                f"{position} nozzle location."
            ),
        )

        occupied.add(_location_key(nozzle))

    return cleaned


def _postprocess_extracted(
    extracted: dict[str, Any],
    user_request: str,
) -> dict[str, Any]:
    """
    Apply deterministic extraction cleanup before dataclass conversion.

    Final engineering validation still happens outside this function through
    validate_parameters().
    """
    cleaned = _normalize_extracted_defaults(extracted)
    cleaned = _repair_duplicate_nozzle_locations(cleaned, user_request)

    return cleaned


def plan_vessel(user_request: str) -> dict[str, Any]:
    """
    Extract vessel parameters from natural language.

    Returns:
        dict matching VESSEL_PARAMETER_SCHEMA after safe extraction cleanup.
    """
    if not user_request or not user_request.strip():
        raise ValueError("user_request must not be empty.")

    extracted = ask_ai(
        prompt=user_request,
        schema=VESSEL_PARAMETER_SCHEMA,
        system_prompt=VESSEL_EXTRACTION_SYSTEM_PROMPT,
        max_retries=2,
    )

    return _postprocess_extracted(extracted, user_request)


def extracted_to_vessel_parameters(extracted: dict[str, Any]) -> VesselParameters:
    """
    Convert AI-extracted JSON into VesselParameters.

    This does not validate engineering.
    Validation is still done by validate_parameters().
    """
    nozzles = []

    for nozzle_data in extracted.get("nozzles", []):
        nozzles.append(
            Nozzle(
                tag=str(nozzle_data["tag"]),
                nominal_size_inches=float(nozzle_data["nominal_size_inches"]),
                position=_enum_from_name_or_value(
                    NozzlePosition,
                    nozzle_data["position"],
                ),
                axial_position_mm=float(nozzle_data["axial_position_mm"]),
                radial_angle_degrees=float(
                    nozzle_data.get("radial_angle_degrees", 0.0)
                ),
            )
        )

    saddles = []

    for saddle_data in extracted.get("saddles", []):
        saddles.append(
            Saddle(
                axial_position_mm=float(saddle_data["axial_position_mm"]),
                width_mm=float(saddle_data.get("width_mm", 200.0)),
                height_mm=float(saddle_data.get("height_mm", 1000.0)),
            )
        )

    return VesselParameters(
        tag=str(extracted["tag"]),
        internal_diameter_mm=float(extracted["internal_diameter_mm"]),
        tangent_to_tangent_mm=float(extracted["tangent_to_tangent_mm"]),
        wall_thickness_mm=float(extracted.get("wall_thickness_mm", 10.0)),
        head_type=_enum_from_name_or_value(
            HeadType,
            extracted.get("head_type", "ELLIPSOIDAL_2_1"),
        ),
        orientation=_enum_from_name_or_value(
            Orientation,
            extracted.get("orientation", "HORIZONTAL"),
        ),
        nozzles=nozzles,
        saddles=saddles,
    )


def format_for_review(extracted: dict[str, Any]) -> str:
    """
    Pretty-print extracted vessel parameters for user review.
    """
    lines = []

    lines.append("Extracted vessel parameters:")
    lines.append(f"  Tag: {extracted['tag']}")
    lines.append(
        f"  Internal diameter: {extracted['internal_diameter_mm']} mm"
    )
    lines.append(
        f"  Tangent-to-tangent: {extracted['tangent_to_tangent_mm']} mm"
    )
    lines.append(
        f"  Wall thickness: {extracted.get('wall_thickness_mm', 10)} mm"
    )
    lines.append(
        f"  Head type: {extracted.get('head_type', 'ELLIPSOIDAL_2_1')}"
    )
    lines.append(
        f"  Orientation: {extracted.get('orientation', 'HORIZONTAL')}"
    )

    nozzles = extracted.get("nozzles", [])
    lines.append("")
    lines.append(f"Nozzles ({len(nozzles)}):")

    if nozzles:
        for nozzle in nozzles:
            size = nozzle["nominal_size_inches"]
            tag = nozzle["tag"]
            position = nozzle["position"]
            axial = nozzle["axial_position_mm"]
            radial = nozzle.get("radial_angle_degrees", 0.0)

            lines.append(
                f"  {tag}: {size}\" {position} "
                f"at axial {axial} mm, radial {radial}°"
            )
    else:
        lines.append("  None")

    saddles = extracted.get("saddles", [])

    lines.append("")
    if saddles:
        lines.append(f"Saddles ({len(saddles)}):")
        for saddle in saddles:
            lines.append(
                f"  axial {saddle['axial_position_mm']} mm, "
                f"width {saddle.get('width_mm', 200)} mm, "
                f"height {saddle.get('height_mm', 1000)} mm"
            )
    else:
        lines.append("Saddles: defaults by geometry layer")

    assumptions = extracted.get("assumptions", [])

    lines.append("")
    if assumptions:
        lines.append("Assumptions made:")
        for assumption in assumptions:
            lines.append(f"  - {assumption}")
    else:
        lines.append("Assumptions: none")

    return "\n".join(lines)
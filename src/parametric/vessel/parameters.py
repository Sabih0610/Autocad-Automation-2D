"""Dataclass parameter contract for the parametric horizontal vessel workflow.

All linear dimensions are expressed in millimeters. Nozzle nominal sizes use
inches NPS. Angles use degrees.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class HeadType(Enum):
    """Supported vessel head styles for the current tier."""

    ELLIPSOIDAL_2_1 = "ELLIPSOIDAL_2_1"


class Orientation(Enum):
    """Supported vessel orientations for the current tier."""

    HORIZONTAL = "HORIZONTAL"


class NozzlePosition(Enum):
    """Allowed nozzle positions on the horizontal vessel."""

    TOP = "TOP"
    BOTTOM = "BOTTOM"
    LEFT_END = "LEFT_END"
    RIGHT_END = "RIGHT_END"
    SIDE_FRONT = "SIDE_FRONT"
    SIDE_BACK = "SIDE_BACK"


@dataclass
class Nozzle:
    """Nozzle definition measured from the left tangent line in millimeters."""

    tag: str
    nominal_size_inches: float
    position: NozzlePosition
    axial_position_mm: float
    radial_angle_degrees: float = 0.0
    projection_mm: float = 150.0


@dataclass
class Saddle:
    """Support saddle measured from the left tangent line in millimeters."""

    axial_position_mm: float
    width_mm: float = 200.0
    height_mm: float = 1000.0


@dataclass
class VesselParameters:
    """Top-level vessel parameters for the pure-math Tier 3a workflow."""

    tag: str
    internal_diameter_mm: float
    tangent_to_tangent_mm: float
    head_type: HeadType = HeadType.ELLIPSOIDAL_2_1
    wall_thickness_mm: float = 10.0
    orientation: Orientation = Orientation.HORIZONTAL
    nozzles: list[Nozzle] = field(default_factory=list)
    saddles: list[Saddle] = field(default_factory=list)


def default_projection_mm(nominal_size_inches: float) -> float:
    """Return a conventional nozzle projection by nominal size in inches.

    The 5 in case is intentionally grouped with the 6-8 in band so callers have
    a continuous practical default between the explicitly requested ranges.
    """

    if nominal_size_inches <= 4.0:
        return 150.0
    if nominal_size_inches < 10.0:
        return 200.0
    return 250.0


def default_saddles_for(diameter_mm: float, tangent_length_mm: float) -> list[Saddle]:
    """Return the standard two-saddle arrangement for a horizontal vessel."""

    saddle_height_mm = 0.5 * diameter_mm
    return [
        Saddle(
            axial_position_mm=0.2 * tangent_length_mm,
            width_mm=200.0,
            height_mm=saddle_height_mm,
        ),
        Saddle(
            axial_position_mm=0.8 * tangent_length_mm,
            width_mm=200.0,
            height_mm=saddle_height_mm,
        ),
    ]


def validate_parameters(params: VesselParameters) -> list[str]:
    """Validate vessel parameters and return a list of error messages.

    The function mutates ``params.saddles`` when the list is empty so default
    saddle placement is available to downstream geometry code without a second
    normalization pass.
    """

    errors: list[str] = []

    if not params.saddles:
        params.saddles = default_saddles_for(
            diameter_mm=params.internal_diameter_mm,
            tangent_length_mm=params.tangent_to_tangent_mm,
        )

    if not isinstance(params.tag, str) or not params.tag.strip():
        errors.append("Vessel tag must be a non-empty string.")

    if params.internal_diameter_mm < 100.0:
        errors.append("Internal diameter must be at least 100 mm.")

    if params.tangent_to_tangent_mm < 200.0:
        errors.append("Tangent-to-tangent length must be at least 200 mm.")

    if params.wall_thickness_mm <= 0.0:
        errors.append("Wall thickness must be greater than 0 mm.")
    elif params.internal_diameter_mm > 0.0 and params.wall_thickness_mm >= (
        params.internal_diameter_mm / 4.0
    ):
        errors.append("Wall thickness must be less than one quarter of the internal diameter.")

    seen_nozzle_tags: set[str] = set()
    seen_locations: set[tuple[str, float, float]] = set()

    for nozzle in params.nozzles:
        if not isinstance(nozzle.tag, str) or not nozzle.tag.strip():
            errors.append("Each nozzle tag must be a non-empty string.")
        elif nozzle.tag in seen_nozzle_tags:
            errors.append(f"Duplicate nozzle tag: {nozzle.tag}.")
        else:
            seen_nozzle_tags.add(nozzle.tag)

        if nozzle.nominal_size_inches <= 0.0:
            errors.append(f"Nozzle {nozzle.tag or '<unnamed>'} must have nominal size > 0.")

        if not (0.0 <= nozzle.radial_angle_degrees <= 360.0):
            errors.append(
                f"Nozzle {nozzle.tag or '<unnamed>'} radial angle must be between 0 and 360 degrees."
            )

        if not (0.0 <= nozzle.axial_position_mm <= params.tangent_to_tangent_mm):
            errors.append(
                f"Nozzle {nozzle.tag or '<unnamed>'} axial position must be between 0 and the tangent-to-tangent length."
            )

        location_key = (
            nozzle.position.value,
            float(nozzle.axial_position_mm),
            float(_location_angle_for_validation(nozzle)),
        )
        if location_key in seen_locations:
            errors.append(
                f"Nozzle {nozzle.tag or '<unnamed>'} duplicates another nozzle location at "
                f"{location_key}."
            )
        else:
            seen_locations.add(location_key)

    sorted_saddles = sorted(params.saddles, key=lambda saddle: saddle.axial_position_mm)
    for saddle in sorted_saddles:
        if not (0.0 <= saddle.axial_position_mm <= params.tangent_to_tangent_mm):
            errors.append("Each saddle axial position must be between 0 and the tangent-to-tangent length.")

    for left_saddle, right_saddle in zip(sorted_saddles, sorted_saddles[1:]):
        left_extent = left_saddle.axial_position_mm + (left_saddle.width_mm / 2.0)
        right_extent = right_saddle.axial_position_mm - (right_saddle.width_mm / 2.0)
        if left_extent >= right_extent:
            errors.append("Saddles must not overlap.")

    return errors


def _location_angle_for_validation(nozzle: Nozzle) -> float:
    """Return the effective angle used when checking duplicate nozzle locations."""

    if nozzle.position in (NozzlePosition.TOP, NozzlePosition.BOTTOM, NozzlePosition.LEFT_END, NozzlePosition.RIGHT_END):
        return 0.0
    return float(nozzle.radial_angle_degrees)

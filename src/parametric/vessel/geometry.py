"""Pure geometry math for the horizontal vessel generator.

The coordinate system is vessel-local:

- origin at the left tangent line on the vessel axis
- +X along vessel length
- +Y upward
- +Z toward the viewer

All linear dimensions are millimeters. Nozzle nominal sizes use inches NPS.
"""

from __future__ import annotations

import math

from fluids import piping

from src.parametric.vessel.parameters import Nozzle, NozzlePosition, Saddle, VesselParameters


ANSI_B16_5_150_RF_FLANGE_OD_MM = {
    1.0: 110.0,
    1.5: 125.0,
    2.0: 150.0,
    3.0: 190.0,
    4.0: 230.0,
    6.0: 280.0,
    8.0: 345.0,
    10.0: 405.0,
    12.0: 485.0,
}


def compute_shell_outline(params: VesselParameters) -> dict:
    """Return the straight shell outline in vessel-local coordinates."""

    shell_outer_radius_mm = _shell_outer_radius_mm(params)
    shell_inner_radius_mm = params.internal_diameter_mm / 2.0
    return {
        "top_line": ((0.0, shell_outer_radius_mm), (params.tangent_to_tangent_mm, shell_outer_radius_mm)),
        "bottom_line": (
            (0.0, -shell_outer_radius_mm),
            (params.tangent_to_tangent_mm, -shell_outer_radius_mm),
        ),
        "left_tangent_x": 0.0,
        "right_tangent_x": params.tangent_to_tangent_mm,
        "shell_outer_radius_mm": shell_outer_radius_mm,
        "shell_inner_radius_mm": shell_inner_radius_mm,
    }


def compute_head_arc(params: VesselParameters, side: str) -> dict:
    """Return ellipse metadata for the requested 2:1 ellipsoidal head.

    The angles describe which half of the ellipse to use in standard CAD
    convention: counterclockwise from the positive X axis. The left head uses
    the western half of the ellipse and the right head uses the eastern half.
    """

    normalized_side = side.lower()
    if normalized_side not in {"left", "right"}:
        raise ValueError("Head side must be 'left' or 'right'.")

    major_axis_mm = _shell_outer_radius_mm(params)
    minor_axis_mm = major_axis_mm / 2.0

    if normalized_side == "left":
        return {
            "side": "left",
            "center": (0.0, 0.0),
            "major_axis_mm": major_axis_mm,
            "minor_axis_mm": minor_axis_mm,
            "start_angle_degrees": 90.0,
            "end_angle_degrees": 270.0,
            "extends_negative_x": True,
        }

    return {
        "side": "right",
        "center": (params.tangent_to_tangent_mm, 0.0),
        "major_axis_mm": major_axis_mm,
        "minor_axis_mm": minor_axis_mm,
        "start_angle_degrees": 270.0,
        "end_angle_degrees": 90.0,
        "extends_negative_x": False,
    }


def compute_nozzle_geometry(params: VesselParameters, nozzle: Nozzle) -> dict:
    """Return insertion, tip, centerline, and reference-size metadata for one nozzle."""

    shell_outer_radius_mm = _shell_outer_radius_mm(params)
    head_depth_mm = _head_depth_inner_mm(params)

    if nozzle.position == NozzlePosition.TOP:
        insertion_point = (nozzle.axial_position_mm, shell_outer_radius_mm, 0.0)
        direction = (0.0, 1.0, 0.0)
    elif nozzle.position == NozzlePosition.BOTTOM:
        insertion_point = (nozzle.axial_position_mm, -shell_outer_radius_mm, 0.0)
        direction = (0.0, -1.0, 0.0)
    elif nozzle.position == NozzlePosition.LEFT_END:
        insertion_point = (-head_depth_mm, 0.0, 0.0)
        direction = (-1.0, 0.0, 0.0)
    elif nozzle.position == NozzlePosition.RIGHT_END:
        insertion_point = (params.tangent_to_tangent_mm + head_depth_mm, 0.0, 0.0)
        direction = (1.0, 0.0, 0.0)
    else:
        resolved_angle_degrees = _resolved_side_angle_degrees(nozzle)
        resolved_angle_radians = math.radians(resolved_angle_degrees)
        insertion_point = (
            nozzle.axial_position_mm,
            shell_outer_radius_mm * math.sin(resolved_angle_radians),
            shell_outer_radius_mm * math.cos(resolved_angle_radians),
        )
        direction = (
            0.0,
            math.sin(resolved_angle_radians),
            math.cos(resolved_angle_radians),
        )

    tip_point = (
        insertion_point[0] + (direction[0] * nozzle.projection_mm),
        insertion_point[1] + (direction[1] * nozzle.projection_mm),
        insertion_point[2] + (direction[2] * nozzle.projection_mm),
    )

    _, pipe_id_m, pipe_od_m, pipe_wall_m = piping.nearest_pipe(
        NPS=nozzle.nominal_size_inches,
        schedule="40",
    )
    flange_od_mm = _lookup_flange_od_mm(nozzle.nominal_size_inches)

    return {
        "nozzle_tag": nozzle.tag,
        "nominal_size_inches": nozzle.nominal_size_inches,
        "position": nozzle.position,
        "axial_position_mm": nozzle.axial_position_mm,
        "insertion_point": insertion_point,
        "tip_point": tip_point,
        "centerline_direction": direction,
        "pipe_od_mm": round(pipe_od_m * 1000.0, 3),
        "pipe_id_mm": round(pipe_id_m * 1000.0, 3),
        "wall_thickness_mm": round(pipe_wall_m * 1000.0, 3),
        "flange_od_mm": flange_od_mm,
        "projection_mm": nozzle.projection_mm,
    }


def compute_saddle_geometry(params: VesselParameters, saddle: Saddle) -> dict:
    """Return a simplified side-elevation saddle outline.

    The top contour is sampled with 10 segments across the saddle width so it
    follows the shell OD in the longitudinal elevation. The true circumferential
    120 degree wrap remains design metadata for later phases.
    """

    shell_outer_radius_mm = _shell_outer_radius_mm(params)
    half_width_mm = saddle.width_mm / 2.0
    base_half_width_mm = half_width_mm + 50.0
    base_y = -shell_outer_radius_mm - saddle.height_mm
    overlap_mm = 1.0

    top_points: list[tuple[float, float]] = []
    for index in range(11):
        x_offset = -half_width_mm + ((saddle.width_mm / 10.0) * index)
        y_on_shell = -math.sqrt(max((shell_outer_radius_mm**2) - (x_offset**2), 0.0))
        top_points.append(
            (
                saddle.axial_position_mm + x_offset,
                y_on_shell + overlap_mm,
            )
        )

    outline_points = [
        (saddle.axial_position_mm - base_half_width_mm, base_y),
        (saddle.axial_position_mm - half_width_mm, top_points[0][1]),
        *top_points,
        (saddle.axial_position_mm + half_width_mm, top_points[-1][1]),
        (saddle.axial_position_mm + base_half_width_mm, base_y),
    ]

    return {
        "saddle_axial_position_mm": saddle.axial_position_mm,
        "outline_points": outline_points,
        "contact_angle_degrees": 120.0,
        "base_y": base_y,
        "shell_contact_y": min(point[1] for point in top_points),
    }


def compute_centerlines(params: VesselParameters) -> dict:
    """Return the main vessel centerline and 2D nozzle centerline projections."""

    head_depth_mm = _head_depth_inner_mm(params)
    nozzle_centerlines = []

    for nozzle in params.nozzles:
        nozzle_geometry = compute_nozzle_geometry(params, nozzle)
        direction = nozzle_geometry["centerline_direction"]
        tip_point = nozzle_geometry["tip_point"]
        start_point = _axis_point_for_nozzle(params, nozzle)
        end_point = (
            tip_point[0] + (direction[0] * 25.0),
            tip_point[1] + (direction[1] * 25.0),
        )
        nozzle_centerlines.append(
            {
                "nozzle_tag": nozzle.tag,
                "line": (start_point, end_point),
            }
        )

    return {
        "main_horizontal": (
            (-head_depth_mm - 100.0, 0.0),
            (params.tangent_to_tangent_mm + head_depth_mm + 100.0, 0.0),
        ),
        "nozzle_centerlines": nozzle_centerlines,
    }


def _shell_outer_radius_mm(params: VesselParameters) -> float:
    return (params.internal_diameter_mm / 2.0) + params.wall_thickness_mm


def _head_depth_inner_mm(params: VesselParameters) -> float:
    return params.internal_diameter_mm / 4.0


def _resolved_side_angle_degrees(nozzle: Nozzle) -> float:
    if nozzle.position == NozzlePosition.SIDE_FRONT:
        return float(nozzle.radial_angle_degrees)
    if nozzle.position == NozzlePosition.SIDE_BACK:
        return float((180.0 + nozzle.radial_angle_degrees) % 360.0)
    raise ValueError("Resolved side angle is only defined for side nozzles.")


def _lookup_flange_od_mm(nominal_size_inches: float) -> float:
    if nominal_size_inches not in ANSI_B16_5_150_RF_FLANGE_OD_MM:
        raise ValueError(
            f"No ANSI B16.5 Class 150 RF flange OD reference is defined for NPS {nominal_size_inches}."
        )
    return ANSI_B16_5_150_RF_FLANGE_OD_MM[nominal_size_inches]


def _axis_point_for_nozzle(params: VesselParameters, nozzle: Nozzle) -> tuple[float, float]:
    head_depth_mm = _head_depth_inner_mm(params)
    if nozzle.position == NozzlePosition.LEFT_END:
        return (-head_depth_mm, 0.0)
    if nozzle.position == NozzlePosition.RIGHT_END:
        return (params.tangent_to_tangent_mm + head_depth_mm, 0.0)
    return (nozzle.axial_position_mm, 0.0)

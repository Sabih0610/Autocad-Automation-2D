"""
Dimension drawing helpers for vessel drawings.

Phase 16 Step 4:
- Basic front-view dimensions
- Nozzle position dimensions
- Saddle position and width dimensions
- Nozzle callout leaders

Later cleanup:
- Improve spacing during Phase 18 edge-case rendering.
"""

from __future__ import annotations

from ezdxf.layouts import Modelspace

from src.parametric.vessel.dimstyle import DIMSTYLE_NAME
from src.parametric.vessel.geometry import (
    compute_head_depth,
    compute_nozzle_geometry,
    compute_shell_outline,
)
from src.parametric.vessel.parameters import NozzlePosition, VesselParameters


LAYER_DIMENSION = "DIMENSION"


def _render_dimension(dim) -> None:
    """Render ezdxf dimension geometry safely."""
    dim.render()


def _add_text(
    msp: Modelspace,
    text: str,
    x: float,
    y: float,
    height: float = 90.0,
) -> None:
    """Add dimension/callout text."""
    msp.add_text(
        text,
        dxfattribs={
            "height": height,
            "layer": LAYER_DIMENSION,
        },
    ).set_placement((x, y))


def _add_leader_line(
    msp: Modelspace,
    start: tuple[float, float],
    end: tuple[float, float],
) -> None:
    """Add a simple leader line."""
    msp.add_line(
        start,
        end,
        dxfattribs={"layer": LAYER_DIMENSION},
    )


def _format_nozzle_size(nominal_size_inches: float) -> str:
    """Format NPS size for callout text."""
    if float(nominal_size_inches).is_integer():
        return f'{int(nominal_size_inches)}"'
    return f'{nominal_size_inches:g}"'


def draw_front_view_basic_dimensions(
    msp: Modelspace,
    params: VesselParameters,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> None:
    """
    Draw front-view dimensions.

    Coordinate convention:
    - origin_x/origin_y is the front view origin.
    - left tangent line is x=0.
    - right tangent line is x=tangent_to_tangent_mm.
    """
    shell = compute_shell_outline(params)

    shell_outer_radius = float(shell["shell_outer_radius_mm"])
    tangent_length = float(params.tangent_to_tangent_mm)

    head_depth = compute_head_depth(params)

    left_overall_x = -head_depth
    right_overall_x = tangent_length + head_depth

    tangent_dim_y = -shell_outer_radius - 650.0
    overall_dim_y = -shell_outer_radius - 1150.0
    height_dim_x = tangent_length + 900.0

    # 1. Tangent-to-tangent length dimension.
    dim = msp.add_linear_dim(
        base=(origin_x + 0.0, origin_y + tangent_dim_y),
        p1=(origin_x + 0.0, origin_y - shell_outer_radius),
        p2=(origin_x + tangent_length, origin_y - shell_outer_radius),
        angle=0.0,
        dimstyle=DIMSTYLE_NAME,
        dxfattribs={"layer": LAYER_DIMENSION},
    )
    _render_dimension(dim)

    _add_text(
        msp,
        "TANGENT-TO-TANGENT",
        origin_x + 1300.0,
        origin_y + tangent_dim_y - 180.0,
    )

    # 2. Overall design length dimension.
    dim = msp.add_linear_dim(
        base=(origin_x + left_overall_x, origin_y + overall_dim_y),
        p1=(origin_x + left_overall_x, origin_y - shell_outer_radius),
        p2=(origin_x + right_overall_x, origin_y - shell_outer_radius),
        angle=0.0,
        dimstyle=DIMSTYLE_NAME,
        dxfattribs={"layer": LAYER_DIMENSION},
    )
    _render_dimension(dim)

    _add_text(
        msp,
        "OVERALL DESIGN LENGTH",
        origin_x + 1300.0,
        origin_y + overall_dim_y - 180.0,
    )

    # 3. Outside diameter / height dimension.
    dim = msp.add_linear_dim(
        base=(origin_x + height_dim_x, origin_y),
        p1=(origin_x + tangent_length, origin_y - shell_outer_radius),
        p2=(origin_x + tangent_length, origin_y + shell_outer_radius),
        angle=90.0,
        dimstyle=DIMSTYLE_NAME,
        dxfattribs={"layer": LAYER_DIMENSION},
    )
    _render_dimension(dim)

    _add_text(
        msp,
        "OUTSIDE DIA.",
        origin_x + height_dim_x + 180.0,
        origin_y - 100.0,
    )

    draw_front_view_nozzle_position_dimensions(
        msp=msp,
        params=params,
        origin_x=origin_x,
        origin_y=origin_y,
    )

    draw_front_view_saddle_dimensions(
        msp=msp,
        params=params,
        origin_x=origin_x,
        origin_y=origin_y,
    )

    draw_front_view_nozzle_callouts(
        msp=msp,
        params=params,
        origin_x=origin_x,
        origin_y=origin_y,
    )


def draw_front_view_nozzle_position_dimensions(
    msp: Modelspace,
    params: VesselParameters,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> None:
    """
    Draw nozzle position dimensions on front view.

    For this pilot:
    - TOP nozzle positions are dimensioned above the vessel.
    - BOTTOM nozzle positions are dimensioned below the vessel, above the main length dimensions.
    - SIDE_FRONT/SIDE_BACK nozzles are handled as callouts for now.
    """
    shell = compute_shell_outline(params)
    shell_outer_radius = float(shell["shell_outer_radius_mm"])

    top_nozzles = [
        nozzle
        for nozzle in params.nozzles
        if nozzle.position == NozzlePosition.TOP
    ]

    bottom_nozzles = [
        nozzle
        for nozzle in params.nozzles
        if nozzle.position == NozzlePosition.BOTTOM
    ]

    top_nozzles.sort(key=lambda n: n.axial_position_mm)
    bottom_nozzles.sort(key=lambda n: n.axial_position_mm)

    # TOP nozzle dimensions above shell.
    for index, nozzle in enumerate(top_nozzles):
        geom = compute_nozzle_geometry(params, nozzle)
        x = float(geom["insertion_point"][0])

        dim_y = shell_outer_radius + 450.0 + (index * 350.0)

        dim = msp.add_linear_dim(
            base=(origin_x + 0.0, origin_y + dim_y),
            p1=(origin_x + 0.0, origin_y + shell_outer_radius),
            p2=(origin_x + x, origin_y + shell_outer_radius),
            angle=0.0,
            dimstyle=DIMSTYLE_NAME,
            dxfattribs={"layer": LAYER_DIMENSION},
        )
        _render_dimension(dim)

        _add_text(
            msp=msp,
            text=f"{nozzle.tag} LOCATION",
            x=origin_x + x + 100.0,
            y=origin_y + dim_y + 80.0,
            height=80.0,
        )

    # BOTTOM nozzle dimensions below shell, but above T-T dimensions.
    for index, nozzle in enumerate(bottom_nozzles):
        geom = compute_nozzle_geometry(params, nozzle)
        x = float(geom["insertion_point"][0])

        dim_y = -shell_outer_radius - 300.0 - (index * 300.0)

        dim = msp.add_linear_dim(
            base=(origin_x + 0.0, origin_y + dim_y),
            p1=(origin_x + 0.0, origin_y - shell_outer_radius),
            p2=(origin_x + x, origin_y - shell_outer_radius),
            angle=0.0,
            dimstyle=DIMSTYLE_NAME,
            dxfattribs={"layer": LAYER_DIMENSION},
        )
        _render_dimension(dim)

        _add_text(
            msp=msp,
            text=f"{nozzle.tag} LOCATION",
            x=origin_x + x + 100.0,
            y=origin_y + dim_y - 150.0,
            height=80.0,
        )


def draw_front_view_saddle_dimensions(
    msp: Modelspace,
    params: VesselParameters,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> None:
    """
    Draw saddle position and width dimensions.

    For this pilot:
    - Saddle centerline positions are dimensioned from the left tangent.
    - Saddle widths are dimensioned directly below each saddle.
    """
    shell = compute_shell_outline(params)
    shell_outer_radius = float(shell["shell_outer_radius_mm"])

    saddles = list(params.saddles)
    saddles.sort(key=lambda s: s.axial_position_mm)

    if not saddles:
        return

    # Width dimensions below each saddle.
    saddle_width_dim_y = -shell_outer_radius - 1650.0

    for saddle in saddles:
        saddle_x = float(saddle.axial_position_mm)
        saddle_width = float(saddle.width_mm)

        left_x = saddle_x - saddle_width / 2.0
        right_x = saddle_x + saddle_width / 2.0

        dim = msp.add_linear_dim(
            base=(origin_x + left_x, origin_y + saddle_width_dim_y),
            p1=(origin_x + left_x, origin_y - shell_outer_radius),
            p2=(origin_x + right_x, origin_y - shell_outer_radius),
            angle=0.0,
            dimstyle=DIMSTYLE_NAME,
            dxfattribs={"layer": LAYER_DIMENSION},
        )
        _render_dimension(dim)

        _add_text(
            msp=msp,
            text="SADDLE WIDTH",
            x=origin_x + left_x - 60.0,
            y=origin_y + saddle_width_dim_y - 160.0,
            height=70.0,
        )

    # Saddle centerline position dimensions from left tangent.
    saddle_position_dim_y = -shell_outer_radius - 2450.0

    for index, saddle in enumerate(saddles):
        saddle_x = float(saddle.axial_position_mm)

        dim_y = saddle_position_dim_y - (index * 300.0)

        dim = msp.add_linear_dim(
            base=(origin_x + 0.0, origin_y + dim_y),
            p1=(origin_x + 0.0, origin_y - shell_outer_radius),
            p2=(origin_x + saddle_x, origin_y - shell_outer_radius),
            angle=0.0,
            dimstyle=DIMSTYLE_NAME,
            dxfattribs={"layer": LAYER_DIMENSION},
        )
        _render_dimension(dim)

        _add_text(
            msp=msp,
            text=f"SADDLE {index + 1} LOCATION",
            x=origin_x + saddle_x + 100.0,
            y=origin_y + dim_y - 150.0,
            height=75.0,
        )


def draw_front_view_nozzle_callouts(
    msp: Modelspace,
    params: VesselParameters,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> None:
    """
    Draw nozzle callouts with simple leader lines.

    These are not final production callouts yet. They are clear pilot labels
    showing nozzle tag, NPS size, and flange rating.
    """
    shell = compute_shell_outline(params)
    shell_outer_radius = float(shell["shell_outer_radius_mm"])

    for nozzle in params.nozzles:
        geom = compute_nozzle_geometry(params, nozzle)

        x, y, _z = geom["insertion_point"]
        tip_x, tip_y, _tip_z = geom["tip_point"]

        size_text = _format_nozzle_size(float(nozzle.nominal_size_inches))
        callout = f"{nozzle.tag} - {size_text} 150# RF"

        if nozzle.position == NozzlePosition.TOP:
            # Put top callouts above the vessel, staggered by x location.
            label_x = origin_x + x - 250.0
            label_y = origin_y + shell_outer_radius + 2300.0

            if x < 1000.0:
                label_y += 250.0

            leader_start = (origin_x + tip_x, origin_y + tip_y)
            leader_end = (label_x + 120.0, label_y - 40.0)

            _add_leader_line(msp, leader_start, leader_end)
            _add_text(msp, callout, label_x, label_y, height=85.0)

        elif nozzle.position == NozzlePosition.BOTTOM:
            # Put bottom callout below/right of the bottom nozzle but above saddle dims.
            label_x = origin_x + x + 250.0
            label_y = origin_y - shell_outer_radius - 950.0

            leader_start = (origin_x + tip_x, origin_y + tip_y)
            leader_end = (label_x - 80.0, label_y + 40.0)

            _add_leader_line(msp, leader_start, leader_end)
            _add_text(msp, callout, label_x, label_y, height=85.0)

        elif nozzle.position == NozzlePosition.SIDE_FRONT:
            # Put side/front nozzle callout inside the vessel clear space.
            label_x = origin_x + x + 450.0
            label_y = origin_y + 300.0

            leader_start = (origin_x + x, origin_y + y)
            leader_end = (label_x - 80.0, label_y + 20.0)

            _add_leader_line(msp, leader_start, leader_end)
            _add_text(msp, callout, label_x, label_y, height=85.0)

        elif nozzle.position == NozzlePosition.SIDE_BACK:
            # Hidden in front view for now.
            continue

        elif nozzle.position in {NozzlePosition.LEFT_END, NozzlePosition.RIGHT_END}:
            label_x = origin_x + x + 250.0
            label_y = origin_y + 500.0

            leader_start = (origin_x + tip_x, origin_y + tip_y)
            leader_end = (label_x - 80.0, label_y + 20.0)

            _add_leader_line(msp, leader_start, leader_end)
            _add_text(msp, callout, label_x, label_y, height=85.0)

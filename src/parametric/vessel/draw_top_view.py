"""
Top view DXF rendering for horizontal vessels.

Phase 15 incremental build:
- Step 1: top view only
- Step 2: side view only
- Step 3: front + top + side layout in one DXF

Coordinates in this view:
- X = vessel axial direction, positive right
- Y = plan/front-back direction on the sheet
- Origin = left tangent line on vessel centerline

This module does NOT touch AutoCAD COM.
It writes pure DXF files via ezdxf.
"""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

import ezdxf
from ezdxf.document import Drawing
from ezdxf.layouts import Modelspace

from src.parametric.vessel.geometry import (
    compute_head_arc,
    compute_head_depth,
    compute_nozzle_geometry,
    compute_shell_outline,
)
from src.parametric.vessel.parameters import (
    NozzlePosition,
    VesselParameters,
    validate_parameters,
)


LAYER_SHELL = "SHELL"
LAYER_NOZZLE = "NOZZLE"
LAYER_SADDLE = "SADDLE"
LAYER_CENTERLINE = "CENTERLINE"
LAYER_DIMENSION = "DIMENSION"
LAYER_VIEW_LABEL = "VIEW_LABEL"


def _ensure_layers(doc: Drawing) -> None:
    """Create standard vessel layers."""
    layers = doc.layers

    if "CENTER_VESSEL" not in doc.linetypes:
        try:
            doc.linetypes.add(
                name="CENTER_VESSEL",
                pattern="A,120,-30,30,-30",
                description="Vessel center ____ _ ____ _ ____",
                length=210.0,
            )
        except Exception:
            pass

    layer_specs = [
        (LAYER_SHELL, 7, "Continuous"),
        (LAYER_NOZZLE, 4, "Continuous"),
        (LAYER_SADDLE, 8, "Continuous"),
        (LAYER_CENTERLINE, 1, "CENTER_VESSEL"),
        (LAYER_DIMENSION, 2, "Continuous"),
        (LAYER_VIEW_LABEL, 3, "Continuous"),
    ]

    for name, color, linetype in layer_specs:
        if name not in layers:
            layer = layers.add(name)
            layer.color = color
            layer.dxf.linetype = linetype

    doc.header["$LTSCALE"] = 1.0
    doc.header["$PSLTSCALE"] = 1


def draw_top_view_shell(
    msp: Modelspace,
    params: VesselParameters,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> None:
    """
    Draw vessel outer shell in top view.

    For a horizontal vessel, the top-view outline is also capsule-shaped:
    straight cylindrical body plus two ellipsoidal heads.
    """
    shell = compute_shell_outline(params)

    top_a, top_b = shell["top_line"]
    bot_a, bot_b = shell["bottom_line"]

    msp.add_line(
        (origin_x + top_a[0], origin_y + top_a[1]),
        (origin_x + top_b[0], origin_y + top_b[1]),
        dxfattribs={"layer": LAYER_SHELL},
    )

    msp.add_line(
        (origin_x + bot_a[0], origin_y + bot_a[1]),
        (origin_x + bot_b[0], origin_y + bot_b[1]),
        dxfattribs={"layer": LAYER_SHELL},
    )


def draw_top_view_heads(
    msp: Modelspace,
    params: VesselParameters,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> None:
    """Draw left and right ellipsoidal heads in top view."""
    left = compute_head_arc(params, "left")
    right = compute_head_arc(params, "right")

    for head in [left, right]:
        center_x, center_y = head["center"]

        vessel_half_width = float(head["major_axis_mm"])
        head_depth = float(head["minor_axis_mm"])

        major_axis_vector = (0.0, vessel_half_width, 0.0)
        ratio = head_depth / vessel_half_width

        if head["side"] == "left":
            start_param = 0.0
            end_param = math.pi
        else:
            start_param = math.pi
            end_param = 2.0 * math.pi

        msp.add_ellipse(
            center=(origin_x + center_x, origin_y + center_y, 0.0),
            major_axis=major_axis_vector,
            ratio=ratio,
            start_param=start_param,
            end_param=end_param,
            dxfattribs={"layer": LAYER_SHELL},
        )


def _draw_circle_nozzle_face(
    msp: Modelspace,
    center_x: float,
    center_y: float,
    pipe_od: float,
    flange_od: float,
    origin_x: float,
    origin_y: float,
) -> None:
    """Draw nozzle/flange face as two concentric circles."""
    center = (origin_x + center_x, origin_y + center_y)

    msp.add_circle(
        center=center,
        radius=flange_od / 2.0,
        dxfattribs={"layer": LAYER_NOZZLE},
    )

    msp.add_circle(
        center=center,
        radius=pipe_od / 2.0,
        dxfattribs={"layer": LAYER_NOZZLE},
    )


def _draw_side_nozzle_in_top_view(
    msp: Modelspace,
    x: float,
    side: str,
    pipe_od: float,
    flange_od: float,
    projection_mm: float,
    shell_outer_radius: float,
    origin_x: float,
    origin_y: float,
) -> None:
    """
    Draw a SIDE_FRONT or SIDE_BACK nozzle in top view.

    SIDE_FRONT is drawn below the vessel centerline.
    SIDE_BACK is drawn above the vessel centerline.
    """
    direction = -1.0 if side == "front" else 1.0

    y_shell = direction * shell_outer_radius
    y_tip = direction * (shell_outer_radius + projection_mm)

    half_pipe = pipe_od / 2.0
    half_flange = flange_od / 2.0

    # Two nozzle body lines.
    msp.add_line(
        (origin_x + x - half_pipe, origin_y + y_shell),
        (origin_x + x - half_pipe, origin_y + y_tip),
        dxfattribs={"layer": LAYER_NOZZLE},
    )

    msp.add_line(
        (origin_x + x + half_pipe, origin_y + y_shell),
        (origin_x + x + half_pipe, origin_y + y_tip),
        dxfattribs={"layer": LAYER_NOZZLE},
    )

    # Flange face at tip.
    msp.add_line(
        (origin_x + x - half_flange, origin_y + y_tip),
        (origin_x + x + half_flange, origin_y + y_tip),
        dxfattribs={"layer": LAYER_NOZZLE},
    )


def draw_top_view_nozzles(
    msp: Modelspace,
    params: VesselParameters,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> None:
    """
    Draw nozzles visible in top view.

    Pilot convention:
    - TOP nozzles appear as circular flange faces on the vessel centerline.
    - BOTTOM nozzles are hidden in top view for now.
    - SIDE_FRONT/SIDE_BACK nozzles appear as stubs protruding from the vessel side.
    - LEFT_END/RIGHT_END nozzles appear as end stubs if present.
    """
    shell = compute_shell_outline(params)
    shell_outer_radius = float(shell["shell_outer_radius_mm"])

    for nozzle in params.nozzles:
        geom = compute_nozzle_geometry(params, nozzle)

        x, _y, _z = geom["insertion_point"]
        tip_x, _tip_y, _tip_z = geom["tip_point"]

        pipe_od = float(geom["pipe_od_mm"])
        flange_od = float(geom["flange_od_mm"])
        projection_mm = float(geom["projection_mm"])

        if nozzle.position == NozzlePosition.TOP:
            _draw_circle_nozzle_face(
                msp=msp,
                center_x=x,
                center_y=0.0,
                pipe_od=pipe_od,
                flange_od=flange_od,
                origin_x=origin_x,
                origin_y=origin_y,
            )

        elif nozzle.position == NozzlePosition.BOTTOM:
            # Hidden in top view for this pilot.
            continue

        elif nozzle.position == NozzlePosition.SIDE_FRONT:
            _draw_side_nozzle_in_top_view(
                msp=msp,
                x=x,
                side="front",
                pipe_od=pipe_od,
                flange_od=flange_od,
                projection_mm=projection_mm,
                shell_outer_radius=shell_outer_radius,
                origin_x=origin_x,
                origin_y=origin_y,
            )

        elif nozzle.position == NozzlePosition.SIDE_BACK:
            _draw_side_nozzle_in_top_view(
                msp=msp,
                x=x,
                side="back",
                pipe_od=pipe_od,
                flange_od=flange_od,
                projection_mm=projection_mm,
                shell_outer_radius=shell_outer_radius,
                origin_x=origin_x,
                origin_y=origin_y,
            )

        elif nozzle.position == NozzlePosition.LEFT_END:
            # End nozzle pointing left.
            y = 0.0
            half_pipe = pipe_od / 2.0
            half_flange = flange_od / 2.0

            msp.add_line(
                (origin_x + x, origin_y + y - half_pipe),
                (origin_x + tip_x, origin_y + y - half_pipe),
                dxfattribs={"layer": LAYER_NOZZLE},
            )
            msp.add_line(
                (origin_x + x, origin_y + y + half_pipe),
                (origin_x + tip_x, origin_y + y + half_pipe),
                dxfattribs={"layer": LAYER_NOZZLE},
            )
            msp.add_line(
                (origin_x + tip_x, origin_y + y - half_flange),
                (origin_x + tip_x, origin_y + y + half_flange),
                dxfattribs={"layer": LAYER_NOZZLE},
            )

        elif nozzle.position == NozzlePosition.RIGHT_END:
            # End nozzle pointing right.
            y = 0.0
            half_pipe = pipe_od / 2.0
            half_flange = flange_od / 2.0

            msp.add_line(
                (origin_x + x, origin_y + y - half_pipe),
                (origin_x + tip_x, origin_y + y - half_pipe),
                dxfattribs={"layer": LAYER_NOZZLE},
            )
            msp.add_line(
                (origin_x + x, origin_y + y + half_pipe),
                (origin_x + tip_x, origin_y + y + half_pipe),
                dxfattribs={"layer": LAYER_NOZZLE},
            )
            msp.add_line(
                (origin_x + tip_x, origin_y + y - half_flange),
                (origin_x + tip_x, origin_y + y + half_flange),
                dxfattribs={"layer": LAYER_NOZZLE},
            )


def draw_top_view_saddles(
    msp: Modelspace,
    params: VesselParameters,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> None:
    """
    Draw saddles as support bands in top view.

    This is a simplified top-view representation: each saddle is shown
    as a narrow rectangular band across the vessel width.
    """
    shell = compute_shell_outline(params)
    shell_outer_radius = float(shell["shell_outer_radius_mm"])

    for saddle in params.saddles:
        x1 = saddle.axial_position_mm - saddle.width_mm / 2.0
        x2 = saddle.axial_position_mm + saddle.width_mm / 2.0
        y1 = -shell_outer_radius
        y2 = shell_outer_radius

        points = [
            (origin_x + x1, origin_y + y1),
            (origin_x + x2, origin_y + y1),
            (origin_x + x2, origin_y + y2),
            (origin_x + x1, origin_y + y2),
        ]

        msp.add_lwpolyline(
            points,
            close=True,
            dxfattribs={"layer": LAYER_SADDLE},
        )


def draw_top_view_centerline(
    msp: Modelspace,
    params: VesselParameters,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> None:
    """Draw main top-view vessel centerline."""
    head_depth = compute_head_depth(params)
    start_x = -head_depth - 100.0
    end_x = params.tangent_to_tangent_mm + head_depth + 100.0

    msp.add_line(
        (origin_x + start_x, origin_y),
        (origin_x + end_x, origin_y),
        dxfattribs={
            "layer": LAYER_CENTERLINE,
            "linetype": "CENTER_VESSEL",
        },
    )


def draw_top_view(
    msp: Modelspace,
    params: VesselParameters,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
    include_label: bool = True,
) -> None:
    """Draw complete top view."""
    draw_top_view_shell(msp, params, origin_x, origin_y)
    draw_top_view_heads(msp, params, origin_x, origin_y)
    draw_top_view_nozzles(msp, params, origin_x, origin_y)
    draw_top_view_saddles(msp, params, origin_x, origin_y)
    draw_top_view_centerline(msp, params, origin_x, origin_y)

    if include_label:
        msp.add_text(
            "TOP VIEW",
            dxfattribs={
                "height": 120.0,
                "layer": LAYER_VIEW_LABEL,
            },
        ).set_placement((origin_x, origin_y - 1350.0))


def render_top_view(
    params: VesselParameters,
    output_path: str,
) -> None:
    """Render top view only to DXF."""
    validation_errors = validate_parameters(params)
    if validation_errors:
        raise ValueError("Invalid vessel parameters: " + "; ".join(validation_errors))

    doc = ezdxf.new(dxfversion="R2010", setup=True)
    _ensure_layers(doc)

    msp = doc.modelspace()
    draw_top_view(msp, params)

    doc.saveas(output_path)


def _cli_render_v201() -> None:
    """Manual test renderer for V-201 top view."""
    from src.parametric.vessel.examples import V201

    project_root = Path(__file__).resolve().parents[3]
    output_dir = project_root / "outputs" / "vessels"
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_path = output_dir / f"V201_top_phase15_step1_{timestamp}.dxf"

    render_top_view(V201, str(output_path))

    print(f"Wrote: {output_path}")
    print("Open this DXF in AutoCAD to verify the top view.")


if __name__ == "__main__":
    _cli_render_v201()

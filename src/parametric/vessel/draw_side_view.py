"""
Side view DXF rendering for horizontal vessels.

Phase 15 incremental build:
- Step 1: top view only
- Step 2: side view only      <-- current step
- Step 3: front + top + side layout in one DXF

Side view convention:
- We are looking at the vessel from one end.
- The vessel appears as a circular shell.
- Drawing X = front/back radial direction.
- Drawing Y = vertical direction.
- Origin = vessel center.

This module does NOT touch AutoCAD COM.
It writes pure DXF files via ezdxf.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import ezdxf
from ezdxf.document import Drawing
from ezdxf.layouts import Modelspace

from src.parametric.vessel.geometry import (
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


def draw_side_view_shell(
    msp: Modelspace,
    params: VesselParameters,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> None:
    """Draw the vessel shell as a circle in side view."""
    shell = compute_shell_outline(params)
    shell_outer_radius = float(shell["shell_outer_radius_mm"])

    msp.add_circle(
        center=(origin_x, origin_y),
        radius=shell_outer_radius,
        dxfattribs={"layer": LAYER_SHELL},
    )


def _draw_vertical_nozzle(
    msp: Modelspace,
    y_shell: float,
    y_tip: float,
    pipe_od: float,
    flange_od: float,
    origin_x: float,
    origin_y: float,
) -> None:
    """Draw top or bottom nozzle in side view."""
    half_pipe = pipe_od / 2.0
    half_flange = flange_od / 2.0

    msp.add_line(
        (origin_x - half_pipe, origin_y + y_shell),
        (origin_x - half_pipe, origin_y + y_tip),
        dxfattribs={"layer": LAYER_NOZZLE},
    )

    msp.add_line(
        (origin_x + half_pipe, origin_y + y_shell),
        (origin_x + half_pipe, origin_y + y_tip),
        dxfattribs={"layer": LAYER_NOZZLE},
    )

    msp.add_line(
        (origin_x - half_flange, origin_y + y_tip),
        (origin_x + half_flange, origin_y + y_tip),
        dxfattribs={"layer": LAYER_NOZZLE},
    )


def _draw_horizontal_nozzle(
    msp: Modelspace,
    x_shell: float,
    x_tip: float,
    pipe_od: float,
    flange_od: float,
    origin_x: float,
    origin_y: float,
) -> None:
    """Draw side/front or side/back nozzle in side view."""
    half_pipe = pipe_od / 2.0
    half_flange = flange_od / 2.0

    msp.add_line(
        (origin_x + x_shell, origin_y - half_pipe),
        (origin_x + x_tip, origin_y - half_pipe),
        dxfattribs={"layer": LAYER_NOZZLE},
    )

    msp.add_line(
        (origin_x + x_shell, origin_y + half_pipe),
        (origin_x + x_tip, origin_y + half_pipe),
        dxfattribs={"layer": LAYER_NOZZLE},
    )

    msp.add_line(
        (origin_x + x_tip, origin_y - half_flange),
        (origin_x + x_tip, origin_y + half_flange),
        dxfattribs={"layer": LAYER_NOZZLE},
    )


def draw_side_view_nozzles(
    msp: Modelspace,
    params: VesselParameters,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> None:
    """
    Draw nozzles in side/end view.

    Note:
    Multiple top nozzles with the same radial direction will overlap in side view.
    That is normal for an end projection because axial positions collapse.
    """
    shell = compute_shell_outline(params)
    shell_outer_radius = float(shell["shell_outer_radius_mm"])

    for nozzle in params.nozzles:
        geom = compute_nozzle_geometry(params, nozzle)

        pipe_od = float(geom["pipe_od_mm"])
        flange_od = float(geom["flange_od_mm"])
        projection_mm = float(geom["projection_mm"])

        if nozzle.position == NozzlePosition.TOP:
            _draw_vertical_nozzle(
                msp=msp,
                y_shell=shell_outer_radius,
                y_tip=shell_outer_radius + projection_mm,
                pipe_od=pipe_od,
                flange_od=flange_od,
                origin_x=origin_x,
                origin_y=origin_y,
            )

        elif nozzle.position == NozzlePosition.BOTTOM:
            _draw_vertical_nozzle(
                msp=msp,
                y_shell=-shell_outer_radius,
                y_tip=-(shell_outer_radius + projection_mm),
                pipe_od=pipe_od,
                flange_od=flange_od,
                origin_x=origin_x,
                origin_y=origin_y,
            )

        elif nozzle.position == NozzlePosition.SIDE_FRONT:
            _draw_horizontal_nozzle(
                msp=msp,
                x_shell=shell_outer_radius,
                x_tip=shell_outer_radius + projection_mm,
                pipe_od=pipe_od,
                flange_od=flange_od,
                origin_x=origin_x,
                origin_y=origin_y,
            )

        elif nozzle.position == NozzlePosition.SIDE_BACK:
            _draw_horizontal_nozzle(
                msp=msp,
                x_shell=-shell_outer_radius,
                x_tip=-(shell_outer_radius + projection_mm),
                pipe_od=pipe_od,
                flange_od=flange_od,
                origin_x=origin_x,
                origin_y=origin_y,
            )

        elif nozzle.position in {NozzlePosition.LEFT_END, NozzlePosition.RIGHT_END}:
            # End nozzles would point toward/away from the viewer in side view.
            # For this pilot, show them as a circular face at vessel center.
            msp.add_circle(
                center=(origin_x, origin_y),
                radius=flange_od / 2.0,
                dxfattribs={"layer": LAYER_NOZZLE},
            )
            msp.add_circle(
                center=(origin_x, origin_y),
                radius=pipe_od / 2.0,
                dxfattribs={"layer": LAYER_NOZZLE},
            )


def draw_side_view_saddle(
    msp: Modelspace,
    params: VesselParameters,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> None:
    """
    Draw simplified saddle support in side view.

    Since side view collapses both saddles into the same projection,
    we show one representative support under the shell.
    """
    shell = compute_shell_outline(params)
    shell_outer_radius = float(shell["shell_outer_radius_mm"])

    support_top_y = -shell_outer_radius
    support_bottom_y = -shell_outer_radius - (0.5 * params.internal_diameter_mm)
    half_width = 300.0

    points = [
        (origin_x - half_width, origin_y + support_top_y),
        (origin_x + half_width, origin_y + support_top_y),
        (origin_x + half_width * 0.75, origin_y + support_bottom_y),
        (origin_x - half_width * 0.75, origin_y + support_bottom_y),
    ]

    msp.add_lwpolyline(
        points,
        close=True,
        dxfattribs={"layer": LAYER_SADDLE},
    )


def draw_side_view_centerlines(
    msp: Modelspace,
    params: VesselParameters,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> None:
    """Draw horizontal and vertical centerlines through the circular end view."""
    shell = compute_shell_outline(params)
    shell_outer_radius = float(shell["shell_outer_radius_mm"])

    overhang = 250.0

    # Horizontal centerline.
    msp.add_line(
        (origin_x - shell_outer_radius - overhang, origin_y),
        (origin_x + shell_outer_radius + overhang, origin_y),
        dxfattribs={
            "layer": LAYER_CENTERLINE,
            "linetype": "CENTER_VESSEL",
        },
    )

    # Vertical centerline.
    msp.add_line(
        (origin_x, origin_y - shell_outer_radius - overhang),
        (origin_x, origin_y + shell_outer_radius + overhang),
        dxfattribs={
            "layer": LAYER_CENTERLINE,
            "linetype": "CENTER_VESSEL",
        },
    )


def draw_side_view(
    msp: Modelspace,
    params: VesselParameters,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
    include_label: bool = True,
) -> None:
    """Draw complete side/end view."""
    draw_side_view_shell(msp, params, origin_x, origin_y)
    draw_side_view_nozzles(msp, params, origin_x, origin_y)
    draw_side_view_saddle(msp, params, origin_x, origin_y)
    draw_side_view_centerlines(msp, params, origin_x, origin_y)

    if include_label:
        msp.add_text(
            "SIDE VIEW",
            dxfattribs={
                "height": 120.0,
                "layer": LAYER_VIEW_LABEL,
            },
        ).set_placement((origin_x - 500.0, origin_y - 2300.0))


def render_side_view(
    params: VesselParameters,
    output_path: str,
) -> None:
    """Render side view only to DXF."""
    validation_errors = validate_parameters(params)
    if validation_errors:
        raise ValueError("Invalid vessel parameters: " + "; ".join(validation_errors))

    doc = ezdxf.new(dxfversion="R2010", setup=True)
    _ensure_layers(doc)

    msp = doc.modelspace()
    draw_side_view(msp, params)

    doc.saveas(output_path)


def _cli_render_v201() -> None:
    """Manual test renderer for V-201 side view."""
    from src.parametric.vessel.examples import V201

    project_root = Path(__file__).resolve().parents[3]
    output_dir = project_root / "outputs" / "vessels"
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_path = output_dir / f"V201_side_phase15_step2_{timestamp}.dxf"

    render_side_view(V201, str(output_path))

    print(f"Wrote: {output_path}")
    print("Open this DXF in AutoCAD to verify the side view.")


if __name__ == "__main__":
    _cli_render_v201()
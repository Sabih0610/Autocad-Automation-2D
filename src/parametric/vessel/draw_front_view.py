"""
Front view DXF rendering for horizontal vessels.

Phase 14 incremental build:
- Step 1: shell only
- Step 2: add elliptical heads
- Step 3: add nozzles
- Step 4: add saddles
- Step 5: add centerlines        <-- current step

Coordinates are in vessel-local mm.
Origin: left tangent line on the vessel axis.
X = axial direction, positive right.
Y = vertical, positive up.

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
    compute_centerlines,
    compute_head_arc,
    compute_nozzle_geometry,
    compute_saddle_geometry,
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


def _ensure_layers(doc: Drawing) -> None:
    """Create standard vessel layers."""
    layers = doc.layers

    # Custom centerline linetype with visible dash pattern at vessel scale.
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
    ]

    for name, color, linetype in layer_specs:
        if name not in layers:
            layer = layers.add(name)
            layer.color = color
            layer.dxf.linetype = linetype

    # Helps AutoCAD display dashed linetypes clearly.
    doc.header["$LTSCALE"] = 1.0
    doc.header["$PSLTSCALE"] = 1


def draw_front_view_shell(
    msp: Modelspace,
    params: VesselParameters,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> None:
    """Draw the cylindrical shell as two horizontal lines."""
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


def draw_front_view_heads(
    msp: Modelspace,
    params: VesselParameters,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> None:
    """Draw left and right 2:1 ellipsoidal heads."""
    left = compute_head_arc(params, "left")
    right = compute_head_arc(params, "right")

    for head in [left, right]:
        center_x, center_y = head["center"]

        vertical_radius = float(head["major_axis_mm"])
        horizontal_depth = float(head["minor_axis_mm"])

        major_axis_vector = (0.0, vertical_radius, 0.0)
        ratio = horizontal_depth / vertical_radius

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


def _draw_vertical_nozzle(
    msp: Modelspace,
    x: float,
    shell_y: float,
    tip_y: float,
    pipe_od: float,
    flange_od: float,
    origin_x: float,
    origin_y: float,
) -> None:
    """Draw a top or bottom nozzle as two vertical lines plus flange face."""
    half_pipe = pipe_od / 2.0
    half_flange = flange_od / 2.0

    x_left = origin_x + x - half_pipe
    x_right = origin_x + x + half_pipe
    y_shell = origin_y + shell_y
    y_tip = origin_y + tip_y

    msp.add_line((x_left, y_shell), (x_left, y_tip), dxfattribs={"layer": LAYER_NOZZLE})
    msp.add_line((x_right, y_shell), (x_right, y_tip), dxfattribs={"layer": LAYER_NOZZLE})

    msp.add_line(
        (origin_x + x - half_flange, y_tip),
        (origin_x + x + half_flange, y_tip),
        dxfattribs={"layer": LAYER_NOZZLE},
    )


def _draw_horizontal_nozzle(
    msp: Modelspace,
    shell_x: float,
    tip_x: float,
    y: float,
    pipe_od: float,
    flange_od: float,
    origin_x: float,
    origin_y: float,
) -> None:
    """Draw a left-end or right-end nozzle."""
    half_pipe = pipe_od / 2.0
    half_flange = flange_od / 2.0

    x_shell = origin_x + shell_x
    x_tip = origin_x + tip_x
    y_mid = origin_y + y

    msp.add_line(
        (x_shell, y_mid - half_pipe),
        (x_tip, y_mid - half_pipe),
        dxfattribs={"layer": LAYER_NOZZLE},
    )
    msp.add_line(
        (x_shell, y_mid + half_pipe),
        (x_tip, y_mid + half_pipe),
        dxfattribs={"layer": LAYER_NOZZLE},
    )

    msp.add_line(
        (x_tip, y_mid - half_flange),
        (x_tip, y_mid + half_flange),
        dxfattribs={"layer": LAYER_NOZZLE},
    )


def _draw_front_side_nozzle(
    msp: Modelspace,
    x: float,
    y: float,
    pipe_od: float,
    flange_od: float,
    origin_x: float,
    origin_y: float,
) -> None:
    """Draw a SIDE_FRONT nozzle as a circular face in front view."""
    center = (origin_x + x, origin_y + y)

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


def draw_front_view_nozzles(
    msp: Modelspace,
    params: VesselParameters,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> None:
    """Draw visible nozzles in front view."""
    for nozzle in params.nozzles:
        geom = compute_nozzle_geometry(params, nozzle)

        x, y, _z = geom["insertion_point"]
        tip_x, tip_y, _tip_z = geom["tip_point"]

        pipe_od = float(geom["pipe_od_mm"])
        flange_od = float(geom["flange_od_mm"])

        if nozzle.position in {NozzlePosition.TOP, NozzlePosition.BOTTOM}:
            _draw_vertical_nozzle(
                msp=msp,
                x=x,
                shell_y=y,
                tip_y=tip_y,
                pipe_od=pipe_od,
                flange_od=flange_od,
                origin_x=origin_x,
                origin_y=origin_y,
            )

        elif nozzle.position in {NozzlePosition.LEFT_END, NozzlePosition.RIGHT_END}:
            _draw_horizontal_nozzle(
                msp=msp,
                shell_x=x,
                tip_x=tip_x,
                y=y,
                pipe_od=pipe_od,
                flange_od=flange_od,
                origin_x=origin_x,
                origin_y=origin_y,
            )

        elif nozzle.position == NozzlePosition.SIDE_FRONT:
            _draw_front_side_nozzle(
                msp=msp,
                x=x,
                y=y,
                pipe_od=pipe_od,
                flange_od=flange_od,
                origin_x=origin_x,
                origin_y=origin_y,
            )

        elif nozzle.position == NozzlePosition.SIDE_BACK:
            continue


def draw_front_view_saddles(
    msp: Modelspace,
    params: VesselParameters,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> None:
    """Draw vessel saddles below the shell."""
    for saddle in params.saddles:
        geom = compute_saddle_geometry(params, saddle)
        outline_points = geom.get("outline_points", [])

        if len(outline_points) < 3:
            continue

        translated_points = [
            (origin_x + float(x), origin_y + float(y))
            for x, y in outline_points
        ]

        msp.add_lwpolyline(
            translated_points,
            close=True,
            dxfattribs={"layer": LAYER_SADDLE},
        )

        saddle_x = float(geom.get("saddle_axial_position_mm", saddle.axial_position_mm))
        shell = compute_shell_outline(params)
        shell_or = float(shell["shell_outer_radius_mm"])

        msp.add_line(
            (origin_x + saddle_x, origin_y - shell_or),
            (origin_x + saddle_x, origin_y - shell_or - 120.0),
            dxfattribs={"layer": LAYER_SADDLE},
        )


def draw_front_view_centerlines(
    msp: Modelspace,
    params: VesselParameters,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> None:
    """Draw main vessel centerline and nozzle centerlines."""
    centerlines = compute_centerlines(params)

    main_a, main_b = centerlines["main_horizontal"]

    msp.add_line(
        (origin_x + main_a[0], origin_y + main_a[1]),
        (origin_x + main_b[0], origin_y + main_b[1]),
        dxfattribs={
            "layer": LAYER_CENTERLINE,
            "linetype": "CENTER_VESSEL",
        },
    )

    for item in centerlines.get("nozzle_centerlines", []):
        line_a, line_b = item["line"]

        msp.add_line(
            (origin_x + line_a[0], origin_y + line_a[1]),
            (origin_x + line_b[0], origin_y + line_b[1]),
            dxfattribs={
                "layer": LAYER_CENTERLINE,
                "linetype": "CENTER_VESSEL",
            },
        )


def render_front_view(
    params: VesselParameters,
    output_path: str,
) -> None:
    """Render the current Phase 14 front view to DXF."""
    validation_errors = validate_parameters(params)
    if validation_errors:
        raise ValueError("Invalid vessel parameters: " + "; ".join(validation_errors))

    doc = ezdxf.new(dxfversion="R2010", setup=True)
    _ensure_layers(doc)

    msp = doc.modelspace()

    draw_front_view_shell(msp, params)
    draw_front_view_heads(msp, params)
    draw_front_view_nozzles(msp, params)
    draw_front_view_saddles(msp, params)
    draw_front_view_centerlines(msp, params)

    doc.saveas(output_path)


def _cli_render_v201() -> None:
    """Manual test renderer for V-201 front view."""
    from src.parametric.vessel.examples import V201

    project_root = Path(__file__).resolve().parents[3]
    output_dir = project_root / "outputs" / "vessels"
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_path = output_dir / f"V201_front_step5_centerlines_{timestamp}.dxf"

    render_front_view(V201, str(output_path))

    print(f"Wrote: {output_path}")
    print("Open this DXF in AutoCAD to verify full Phase 14 front view.")


if __name__ == "__main__":
    _cli_render_v201()
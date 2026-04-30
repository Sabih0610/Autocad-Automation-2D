"""
Combined vessel DXF/DWG renderer.

Phase 19:
- Existing DXF rendering stays unchanged.
- New render_vessel() wrapper supports:
    output_format="dxf"
    output_format="dwg"

DWG output:
- First writes a DXF intermediate.
- Then AutoCAD COM converts DXF -> DWG.
- Keeps the intermediate DXF for debugging.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import ezdxf
from ezdxf.document import Drawing
from ezdxf.layouts import Modelspace

from src.parametric.vessel.dimstyle import setup_vessel_dimstyle
from src.parametric.vessel.draw_dimensions import draw_front_view_basic_dimensions
from src.parametric.vessel.draw_front_view import (
    draw_front_view_centerlines,
    draw_front_view_heads,
    draw_front_view_nozzles,
    draw_front_view_saddles,
    draw_front_view_shell,
)
from src.parametric.vessel.draw_side_view import draw_side_view
from src.parametric.vessel.draw_top_view import draw_top_view
from src.parametric.vessel.dwg_export import DWG_R2018, convert_dxf_to_dwg
from src.parametric.vessel.parameters import VesselParameters, validate_parameters
from src.parametric.vessel.sheet import (
    SheetLayout,
    choose_sheet_layout,
    draw_sheet_frame_and_tables,
)


LAYER_SHELL = "SHELL"
LAYER_NOZZLE = "NOZZLE"
LAYER_SADDLE = "SADDLE"
LAYER_CENTERLINE = "CENTERLINE"
LAYER_DIMENSION = "DIMENSION"
LAYER_VIEW_LABEL = "VIEW_LABEL"
LAYER_SHEET = "SHEET"


def ensure_vessel_layers(doc: Drawing) -> None:
    """Create all standard vessel drawing layers."""
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
        (LAYER_SHEET, 6, "Continuous"),
    ]

    for name, color, linetype in layer_specs:
        if name not in layers:
            layer = layers.add(name)
            layer.color = color
            layer.dxf.linetype = linetype

    doc.header["$LTSCALE"] = 1.0
    doc.header["$PSLTSCALE"] = 1

    setup_vessel_dimstyle(doc)


def add_view_label(
    msp: Modelspace,
    text: str,
    x: float,
    y: float,
    height: float = 120.0,
) -> None:
    """Add simple view label text."""
    msp.add_text(
        text,
        dxfattribs={
            "height": height,
            "layer": LAYER_VIEW_LABEL,
        },
    ).set_placement((x, y))


def draw_front_view(
    msp: Modelspace,
    params: VesselParameters,
    origin_x: float,
    origin_y: float,
    include_label: bool = True,
    include_dimensions: bool = True,
) -> None:
    """Draw complete front view using the Phase 14 front-view functions."""
    draw_front_view_shell(msp, params, origin_x, origin_y)
    draw_front_view_heads(msp, params, origin_x, origin_y)
    draw_front_view_nozzles(msp, params, origin_x, origin_y)
    draw_front_view_saddles(msp, params, origin_x, origin_y)
    draw_front_view_centerlines(msp, params, origin_x, origin_y)

    if include_dimensions:
        draw_front_view_basic_dimensions(msp, params, origin_x, origin_y)

    if include_label:
        add_view_label(
            msp=msp,
            text="FRONT VIEW",
            x=origin_x,
            y=origin_y - 4300.0,
        )


def draw_three_view_layout(
    msp: Modelspace,
    params: VesselParameters,
    layout: SheetLayout,
) -> None:
    """Draw front, top, and side views using computed layout origins."""
    draw_front_view(
        msp=msp,
        params=params,
        origin_x=layout.front_origin_x,
        origin_y=layout.front_origin_y,
        include_label=True,
        include_dimensions=True,
    )

    draw_top_view(
        msp=msp,
        params=params,
        origin_x=layout.top_origin_x,
        origin_y=layout.top_origin_y,
        include_label=True,
    )

    draw_side_view(
        msp=msp,
        params=params,
        origin_x=layout.side_origin_x,
        origin_y=layout.side_origin_y,
        include_label=True,
    )


def render_vessel_dxf(
    params: VesselParameters,
    output_path: str,
) -> SheetLayout:
    """
    Render the vessel as a combined sheet DXF.

    Returns:
        SheetLayout used for the drawing, including chosen scale.
    """
    validation_errors = validate_parameters(params)
    if validation_errors:
        raise ValueError("Invalid vessel parameters: " + "; ".join(validation_errors))

    layout = choose_sheet_layout(params)

    doc = ezdxf.new(dxfversion="R2010", setup=True)
    ensure_vessel_layers(doc)

    msp = doc.modelspace()

    draw_sheet_frame_and_tables(msp, params, layout)
    draw_three_view_layout(msp, params, layout)

    doc.saveas(output_path)

    return layout


def render_vessel(
    params: VesselParameters,
    output_path: str,
    output_format: str = "dxf",
    dwg_version: int = DWG_R2018,
) -> dict:
    """
    Render a vessel to DXF or DWG.

    For DXF:
        writes DXF directly with ezdxf.

    For DWG:
        writes a DXF intermediate first,
        then converts it to DWG using AutoCAD COM.
    """
    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    fmt = output_format.lower().strip()

    if fmt == "dxf":
        layout = render_vessel_dxf(params, str(output))

        return {
            "ok": True,
            "format": "dxf",
            "path": str(output),
            "scale": layout.scale_text,
            "sheet": layout.paper.name,
            "message": "DXF rendered successfully.",
        }

    if fmt == "dwg":
        if output.suffix.lower() != ".dwg":
            output = output.with_suffix(".dwg")

        dxf_intermediate = output.with_suffix(".dxf")

        layout = render_vessel_dxf(params, str(dxf_intermediate))

        dwg_result = convert_dxf_to_dwg(
            dxf_path=str(dxf_intermediate),
            dwg_path=str(output),
            dwg_version=dwg_version,
        )

        return {
            "ok": bool(dwg_result["ok"]),
            "format": "dwg",
            "path": str(output),
            "dxf_intermediate": str(dxf_intermediate),
            "dwg_version": dwg_version,
            "scale": layout.scale_text,
            "sheet": layout.paper.name,
            "message": "DWG rendered successfully via DXF intermediate.",
        }

    raise ValueError(f"Unsupported output_format: {output_format}")


def _cli_render_v201() -> None:
    """Manual test renderer for V-201 Phase 19."""
    from src.parametric.vessel.examples import V201

    project_root = Path(__file__).resolve().parents[3]
    output_dir = project_root / "outputs" / "vessels"
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_path = output_dir / f"V201_phase19_{timestamp}.dxf"

    result = render_vessel(
        params=V201,
        output_path=str(output_path),
        output_format="dxf",
    )

    print(result)


if __name__ == "__main__":
    _cli_render_v201()
"""
Sheet, title block, BOM, and layout helpers for vessel drawings.

Phase 17/18:
- Use real paper sheet definitions.
- Start with A1 landscape.
- Choose a real drawing scale from fixed options.
- Draw title block at bottom-right only.
- Draw nozzle BOM table at bottom-left.
- Keep Phase 2-compatible title block field names:
  REV, DATE, DRAWN_BY, DRAWING_NO.

Phase 18 update:
- Tightened view bounding boxes so V-201 can select 1:20 instead of 1:50.
- Added a fit tolerance because the view bounding box is an estimate, not exact geometry.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime

from ezdxf.layouts import Modelspace

from src.parametric.vessel.geometry import compute_shell_outline
from src.parametric.vessel.parameters import VesselParameters


LAYER_SHEET = "SHEET"


@dataclass(frozen=True)
class PaperSize:
    """Paper size in real paper millimeters."""
    name: str
    width_mm: float
    height_mm: float


@dataclass(frozen=True)
class SheetLayout:
    """Computed modelspace sheet layout."""
    paper: PaperSize
    scale_denominator: int
    scale_text: str

    sheet_width: float
    sheet_height: float

    border_left: float
    border_other: float

    inner_x1: float
    inner_y1: float
    inner_x2: float
    inner_y2: float

    title_x1: float
    title_y1: float
    title_x2: float
    title_y2: float

    bom_x1: float
    bom_y1: float
    bom_x2: float
    bom_y2: float

    drawing_area_x1: float
    drawing_area_y1: float
    drawing_area_x2: float
    drawing_area_y2: float

    front_origin_x: float
    front_origin_y: float
    top_origin_x: float
    top_origin_y: float
    side_origin_x: float
    side_origin_y: float


A1_LANDSCAPE = PaperSize("A1 LANDSCAPE", 841.0, 594.0)

# Try tight scales first, then fall back for long/crowded drawings.
SCALE_OPTIONS = [10, 20, 50, 100]

# The view extents are conservative estimates, not exact CAD extents.
# A small tolerance prevents a drawing from jumping from 1:20 to 1:50
# because of a few hundred millimeters of estimated callout padding.
FIT_TOLERANCE_MM = 500.0


def _add_text(
    msp: Modelspace,
    text: str,
    x: float,
    y: float,
    height: float,
    layer: str = LAYER_SHEET,
) -> None:
    """Add simple text."""
    msp.add_text(
        str(text),
        dxfattribs={
            "height": height,
            "layer": layer,
        },
    ).set_placement((x, y))


def _draw_rect(
    msp: Modelspace,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    layer: str = LAYER_SHEET,
) -> None:
    """Draw rectangle as closed lightweight polyline."""
    points = [
        (x1, y1),
        (x2, y1),
        (x2, y2),
        (x1, y2),
    ]

    msp.add_lwpolyline(
        points,
        close=True,
        dxfattribs={"layer": layer},
    )


def _draw_grid_line(
    msp: Modelspace,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    layer: str = LAYER_SHEET,
) -> None:
    """Draw one title/BOM grid line."""
    msp.add_line(
        (x1, y1),
        (x2, y2),
        dxfattribs={"layer": layer},
    )


def _model_value(paper_mm: float, scale_denominator: int) -> float:
    """Convert paper millimeters to modelspace millimeters."""
    return float(paper_mm) * float(scale_denominator)


def _safe_username() -> str:
    """Read current Windows username for DRAWN_BY."""
    return os.getenv("USERNAME") or os.getenv("USER") or "AUTO"


def _format_size_inches(value: float) -> str:
    """Format nozzle nominal size."""
    value = float(value)

    if value.is_integer():
        return f'{int(value)}"'

    return f'{value:g}"'


def _view_extents_for_current_dimensioned_views(
    params: VesselParameters,
) -> dict[str, tuple[float, float, float, float]]:
    """
    Approximate view bounding boxes in local coordinates.

    These extents include the current Phase 16 dimensions and callouts.

    Important:
    These are not exact entity extents. They are conservative layout estimates
    used only for picking sheet scale and centering the three-view layout.
    """
    shell = compute_shell_outline(params)

    shell_or = float(shell["shell_outer_radius_mm"])
    tangent_length = float(params.tangent_to_tangent_mm)
    head_depth = float(params.internal_diameter_mm) / 4.0

    # FRONT VIEW:
    # Includes:
    # - vessel body
    # - front dimensions
    # - saddle dimensions
    # - top/bottom nozzle callouts
    #
    # Tuned for Phase 18 so V-201 fits A1 at 1:20.
    front_x_min = -head_depth - 900.0
    front_x_max = tangent_length + head_depth + 1500.0
    front_y_min = -shell_or - 2550.0
    front_y_max = shell_or + 2100.0

    # TOP VIEW:
    # Top view has fewer dimensions and needs less padding.
    top_x_min = -head_depth - 250.0
    top_x_max = tangent_length + head_depth + 250.0
    top_y_min = -shell_or - 500.0
    top_y_max = shell_or + 300.0

    # SIDE VIEW:
    # Includes circle, nozzles, support, and label.
    side_x_min = -shell_or - 450.0
    side_x_max = shell_or + 650.0
    side_y_min = -shell_or - 1350.0
    side_y_max = shell_or + 500.0

    return {
        "front": (front_x_min, front_y_min, front_x_max, front_y_max),
        "top": (top_x_min, top_y_min, top_x_max, top_y_max),
        "side": (side_x_min, side_y_min, side_x_max, side_y_max),
    }


def _compute_raw_view_origins(
    params: VesselParameters,
) -> tuple[
    dict[str, tuple[float, float]],
    tuple[float, float, float, float],
]:
    """
    Compute raw local origins and union bounding box for the three views.

    Raw layout:
    - front view at local origin
    - top view above front
    - side view to the right of front
    """
    extents = _view_extents_for_current_dimensioned_views(params)

    front = extents["front"]
    top = extents["top"]
    side = extents["side"]

    gap_x = 300.0
    gap_y = 120.0

    front_origin = (0.0, 0.0)

    top_origin_y = front[3] - top[1] + gap_y
    top_origin = (0.0, top_origin_y)

    side_origin_x = front[2] - side[0] + gap_x
    side_origin = (side_origin_x, 0.0)

    all_boxes = [
        (
            front[0] + front_origin[0],
            front[1] + front_origin[1],
            front[2] + front_origin[0],
            front[3] + front_origin[1],
        ),
        (
            top[0] + top_origin[0],
            top[1] + top_origin[1],
            top[2] + top_origin[0],
            top[3] + top_origin[1],
        ),
        (
            side[0] + side_origin[0],
            side[1] + side_origin[1],
            side[2] + side_origin[0],
            side[3] + side_origin[1],
        ),
    ]

    union_x1 = min(box[0] for box in all_boxes)
    union_y1 = min(box[1] for box in all_boxes)
    union_x2 = max(box[2] for box in all_boxes)
    union_y2 = max(box[3] for box in all_boxes)

    return (
        {
            "front": front_origin,
            "top": top_origin,
            "side": side_origin,
        },
        (union_x1, union_y1, union_x2, union_y2),
    )


def _make_layout_for_scale(
    params: VesselParameters,
    scale_denominator: int,
    paper: PaperSize = A1_LANDSCAPE,
) -> SheetLayout:
    """Create a layout for one scale denominator."""
    sheet_width = _model_value(paper.width_mm, scale_denominator)
    sheet_height = _model_value(paper.height_mm, scale_denominator)

    border_left = _model_value(25.0, scale_denominator)
    border_other = _model_value(10.0, scale_denominator)

    inner_x1 = border_left
    inner_y1 = border_other
    inner_x2 = sheet_width - border_other
    inner_y2 = sheet_height - border_other

    # Title block bottom-right only: 200mm x 80mm at paper scale.
    title_width = _model_value(200.0, scale_denominator)
    title_height = _model_value(80.0, scale_denominator)

    title_x2 = inner_x2
    title_x1 = title_x2 - title_width
    title_y1 = inner_y1
    title_y2 = title_y1 + title_height

    # Nozzle BOM bottom-left: 320mm x 80mm at paper scale.
    bom_width = _model_value(320.0, scale_denominator)
    bom_height = title_height

    bom_x1 = inner_x1
    bom_y1 = inner_y1
    bom_x2 = bom_x1 + bom_width
    bom_y2 = bom_y1 + bom_height

    # Area available for views above the bottom tables.
    table_clearance = _model_value(6.0, scale_denominator)

    drawing_area_x1 = inner_x1 + _model_value(8.0, scale_denominator)
    drawing_area_x2 = inner_x2 - _model_value(8.0, scale_denominator)
    drawing_area_y1 = max(title_y2, bom_y2) + table_clearance
    drawing_area_y2 = inner_y2 - _model_value(8.0, scale_denominator)

    raw_origins, union = _compute_raw_view_origins(params)

    union_x1, union_y1, union_x2, union_y2 = union
    union_width = union_x2 - union_x1
    union_height = union_y2 - union_y1

    available_width = drawing_area_x2 - drawing_area_x1
    available_height = drawing_area_y2 - drawing_area_y1

    # Center the three-view union inside the drawing area.
    target_x1 = drawing_area_x1 + ((available_width - union_width) / 2.0)
    target_y1 = drawing_area_y1 + ((available_height - union_height) / 2.0)

    offset_x = target_x1 - union_x1
    offset_y = target_y1 - union_y1

    front_origin_x = raw_origins["front"][0] + offset_x
    front_origin_y = raw_origins["front"][1] + offset_y

    top_origin_x = raw_origins["top"][0] + offset_x
    top_origin_y = raw_origins["top"][1] + offset_y

    side_origin_x = raw_origins["side"][0] + offset_x
    side_origin_y = raw_origins["side"][1] + offset_y

    return SheetLayout(
        paper=paper,
        scale_denominator=scale_denominator,
        scale_text=f"1:{scale_denominator}",
        sheet_width=sheet_width,
        sheet_height=sheet_height,
        border_left=border_left,
        border_other=border_other,
        inner_x1=inner_x1,
        inner_y1=inner_y1,
        inner_x2=inner_x2,
        inner_y2=inner_y2,
        title_x1=title_x1,
        title_y1=title_y1,
        title_x2=title_x2,
        title_y2=title_y2,
        bom_x1=bom_x1,
        bom_y1=bom_y1,
        bom_x2=bom_x2,
        bom_y2=bom_y2,
        drawing_area_x1=drawing_area_x1,
        drawing_area_y1=drawing_area_y1,
        drawing_area_x2=drawing_area_x2,
        drawing_area_y2=drawing_area_y2,
        front_origin_x=front_origin_x,
        front_origin_y=front_origin_y,
        top_origin_x=top_origin_x,
        top_origin_y=top_origin_y,
        side_origin_x=side_origin_x,
        side_origin_y=side_origin_y,
    )


def choose_sheet_layout(params: VesselParameters) -> SheetLayout:
    """
    Choose the first A1 layout scale where the three views fit.

    Expected after Phase 18 Issue 1 fix:
    - V-201 should select 1:20
    - longer/crowded vessels can still select 1:50 if needed
    """
    _raw_origins, union = _compute_raw_view_origins(params)

    union_width = union[2] - union[0]
    union_height = union[3] - union[1]

    last_layout: SheetLayout | None = None

    for scale_denominator in SCALE_OPTIONS:
        layout = _make_layout_for_scale(params, scale_denominator)
        last_layout = layout

        available_width = layout.drawing_area_x2 - layout.drawing_area_x1
        available_height = layout.drawing_area_y2 - layout.drawing_area_y1

        fits_width = union_width <= available_width + FIT_TOLERANCE_MM
        fits_height = union_height <= available_height + FIT_TOLERANCE_MM

        if fits_width and fits_height:
            return layout

    assert last_layout is not None
    return last_layout


def draw_sheet_border(
    msp: Modelspace,
    layout: SheetLayout,
) -> None:
    """Draw outer and inner sheet borders."""
    _draw_rect(msp, 0.0, 0.0, layout.sheet_width, layout.sheet_height)

    _draw_rect(
        msp,
        layout.inner_x1,
        layout.inner_y1,
        layout.inner_x2,
        layout.inner_y2,
    )


def draw_title_block(
    msp: Modelspace,
    params: VesselParameters,
    layout: SheetLayout,
) -> None:
    """
    Draw bottom-right title block.

    Keeps Phase 2-compatible fields:
    REV, DATE, DRAWN_BY, DRAWING_NO.
    """
    x1 = layout.title_x1
    y1 = layout.title_y1
    x2 = layout.title_x2
    y2 = layout.title_y2

    scale = layout.scale_denominator

    _draw_rect(msp, x1, y1, x2, y2)

    row_h = (y2 - y1) / 4.0

    # Horizontal title block rows.
    for i in range(1, 4):
        y = y1 + (i * row_h)
        _draw_grid_line(msp, x1, y, x2, y)

    # Vertical title block columns.
    col1 = x1 + _model_value(90.0, scale)
    col2 = x1 + _model_value(145.0, scale)
    col3 = x1 + _model_value(170.0, scale)

    for x in [col1, col2, col3]:
        _draw_grid_line(msp, x, y1, x, y2)

    drawing_no = f"{params.tag}-GA-001"
    title = f"HORIZONTAL VESSEL - {params.tag}"
    size = (
        f"ID {int(params.internal_diameter_mm)}mm "
        f"x T/T {int(params.tangent_to_tangent_mm)}mm"
    )
    date_text = datetime.now().strftime("%Y-%m-%d")
    drawn_by = _safe_username()
    rev = "A"

    text_h_label = _model_value(2.8, scale)
    text_h_value = _model_value(3.8, scale)

    pad_x = _model_value(3.0, scale)
    pad_y_label = _model_value(2.0, scale)
    pad_y_value = _model_value(8.5, scale)

    def cell_text(label: str, value: str, cx: float, cy: float) -> None:
        _add_text(msp, label, cx + pad_x, cy + pad_y_label, text_h_label)
        _add_text(msp, value, cx + pad_x, cy + pad_y_value, text_h_value)

    r0 = y1
    r1 = y1 + row_h
    r2 = y1 + (2 * row_h)
    r3 = y1 + (3 * row_h)

    # Main left column.
    cell_text("TITLE", title, x1, r3)
    cell_text("DRAWING_NO", drawing_no, x1, r2)
    cell_text("SIZE", size, x1, r1)
    cell_text("PROJECT", "PARAMETRIC VESSEL PILOT", x1, r0)

    # Middle column.
    cell_text("SCALE", layout.scale_text, col1, r3)
    cell_text("PROJECTION", "THIRD ANGLE", col1, r2)
    cell_text("SHEET", "1 OF 1", col1, r1)
    cell_text("STATUS", "PRELIMINARY", col1, r0)

    # Right-middle column.
    cell_text("DATE", date_text, col2, r3)
    cell_text("DRAWN_BY", drawn_by, col2, r2)
    cell_text("CHECKED", "-", col2, r1)
    cell_text("APPROVED", "-", col2, r0)

    # Right narrow column.
    cell_text("REV", rev, col3, r3)
    cell_text("ZONE", "-", col3, r2)
    cell_text("CLIENT", "-", col3, r1)
    cell_text("PAGE", "1", col3, r0)


def draw_nozzle_bom(
    msp: Modelspace,
    params: VesselParameters,
    layout: SheetLayout,
) -> None:
    """Draw bottom-left nozzle BOM table."""
    x1 = layout.bom_x1
    y1 = layout.bom_y1
    x2 = layout.bom_x2
    y2 = layout.bom_y2

    scale = layout.scale_denominator

    _draw_rect(msp, x1, y1, x2, y2)

    title_h = _model_value(9.0, scale)
    header_h = _model_value(8.0, scale)

    title_y = y2 - title_h
    header_y = title_y - header_h

    _draw_grid_line(msp, x1, title_y, x2, title_y)
    _draw_grid_line(msp, x1, header_y, x2, header_y)

    # Columns: TAG, SIZE, RATING, POSITION, AXIAL POSITION
    col_widths_paper = [35.0, 35.0, 45.0, 90.0, 115.0]
    col_x = [x1]

    for width in col_widths_paper[:-1]:
        col_x.append(col_x[-1] + _model_value(width, scale))

    for x in col_x[1:]:
        _draw_grid_line(msp, x, title_y, x, y1)

    text_h_title = _model_value(3.8, scale)
    text_h = _model_value(3.2, scale)
    pad_x = _model_value(2.0, scale)
    pad_y = _model_value(2.4, scale)

    _add_text(
        msp,
        "NOZZLE SCHEDULE / BOM",
        x1 + pad_x,
        title_y + pad_y,
        text_h_title,
    )

    headers = ["TAG", "SIZE", "RATING", "POSITION", "AXIAL POSITION"]

    for index, header in enumerate(headers):
        _add_text(
            msp,
            header,
            col_x[index] + pad_x,
            header_y + pad_y,
            text_h,
        )

    max_rows = 12
    data_area_height = header_y - y1
    row_h = data_area_height / max_rows

    for i in range(1, max_rows):
        y = header_y - (i * row_h)
        _draw_grid_line(msp, x1, y, x2, y)

    sorted_nozzles = sorted(params.nozzles, key=lambda n: n.tag)

    for row_index, nozzle in enumerate(sorted_nozzles[:max_rows]):
        row_top = header_y - (row_index * row_h)
        text_y = row_top - row_h + pad_y

        values = [
            nozzle.tag,
            _format_size_inches(nozzle.nominal_size_inches),
            "150# RF",
            nozzle.position.value,
            f"{int(nozzle.axial_position_mm)} mm",
        ]

        for col_index, value in enumerate(values):
            _add_text(
                msp,
                value,
                col_x[col_index] + pad_x,
                text_y,
                text_h,
            )


def draw_sheet_frame_and_tables(
    msp: Modelspace,
    params: VesselParameters,
    layout: SheetLayout,
) -> None:
    """Draw all sheet elements."""
    draw_sheet_border(msp, layout)
    draw_nozzle_bom(msp, params, layout)
    draw_title_block(msp, params, layout)
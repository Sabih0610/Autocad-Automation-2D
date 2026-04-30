"""DXF preview renderer for structured Mode 2 command dictionaries.

This module renders command JSON into a DXF file using ezdxf only. It does not
call AI, AutoCAD COM, API routes, web UI code, or SVG rendering.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import ezdxf

from src.framework.commands.schema import validate_command_sequence


class PreviewRenderError(Exception):
    """Raised when preview rendering cannot create or save a DXF."""


def ensure_preview_layer(
    doc,
    layer_name: str,
    color: int | None = None,
    linetype: str | None = None,
) -> None:
    """Ensure a preview layer exists, applying color/linetype when possible."""
    if not layer_name or layer_name == "0":
        return

    if layer_name not in doc.layers:
        layer = doc.layers.add(layer_name)
    else:
        layer = doc.layers.get(layer_name)

    if color is not None:
        layer.color = int(color)

    if linetype:
        try:
            layer.dxf.linetype = linetype
        except Exception:
            pass


def _layer_for(command: dict, default: str = "0") -> str:
    layer = command.get("layer") or default
    return layer or "0"


def _attribs_for(command: dict, doc, default_layer: str = "0") -> dict[str, Any]:
    layer = _layer_for(command, default_layer)
    ensure_preview_layer(doc, layer)
    return {"layer": layer}


def _point2(value: list[float]) -> tuple[float, float]:
    return (float(value[0]), float(value[1]))


def _point3(value: list[float]) -> tuple[float, float, float]:
    return (float(value[0]), float(value[1]), 0.0)


def _add_text(
    msp,
    text: str,
    position: tuple[float, float],
    height: float,
    layer: str,
    rotation_degrees: float | None = None,
):
    entity = msp.add_text(
        text,
        dxfattribs={
            "height": float(height),
            "layer": layer,
        },
    )
    entity.set_placement(position)

    if rotation_degrees is not None:
        entity.dxf.rotation = float(rotation_degrees)

    return entity


def _add_preview_error_marker(doc, msp, command_index: int, command: dict, error: Exception) -> None:
    try:
        ensure_preview_layer(doc, "PREVIEW_ERROR", color=1)
        y = -100.0 * (command_index + 1)
        _add_text(
            msp=msp,
            text=f"PREVIEW ERROR command {command_index}: {type(error).__name__}",
            position=(0.0, y),
            height=50.0,
            layer="PREVIEW_ERROR",
        )
    except Exception:
        pass


def _render_layer(doc, _msp, command: dict) -> None:
    ensure_preview_layer(
        doc=doc,
        layer_name=command["layer_name"],
        color=command.get("color"),
        linetype=command.get("linetype"),
    )


def _render_line(doc, msp, command: dict) -> None:
    msp.add_line(
        _point2(command["from"]),
        _point2(command["to"]),
        dxfattribs=_attribs_for(command, doc),
    )


def _render_circle(doc, msp, command: dict) -> None:
    msp.add_circle(
        _point2(command["center"]),
        float(command["radius"]),
        dxfattribs=_attribs_for(command, doc),
    )


def _render_arc(doc, msp, command: dict) -> None:
    msp.add_arc(
        _point2(command["center"]),
        float(command["radius"]),
        float(command["start_angle_degrees"]),
        float(command["end_angle_degrees"]),
        dxfattribs=_attribs_for(command, doc),
    )


def _render_ellipse(doc, msp, command: dict) -> None:
    center = _point3(command["center"])
    endpoint = _point3(command["major_axis_endpoint"])
    major_axis = (
        endpoint[0] - center[0],
        endpoint[1] - center[1],
        endpoint[2] - center[2],
    )

    kwargs: dict[str, Any] = {
        "center": center,
        "major_axis": major_axis,
        "ratio": float(command["ratio"]),
        "dxfattribs": _attribs_for(command, doc),
    }

    if "start_angle_degrees" in command and "end_angle_degrees" in command:
        kwargs["start_param"] = math.radians(float(command["start_angle_degrees"]))
        kwargs["end_param"] = math.radians(float(command["end_angle_degrees"]))

    msp.add_ellipse(**kwargs)


def _render_polyline(doc, msp, command: dict) -> None:
    msp.add_lwpolyline(
        [_point2(point) for point in command["points"]],
        close=bool(command.get("closed", False)),
        dxfattribs=_attribs_for(command, doc),
    )


def _render_text(doc, msp, command: dict) -> None:
    layer = _layer_for(command)
    ensure_preview_layer(doc, layer)
    _add_text(
        msp=msp,
        text=command["text"],
        position=_point2(command["position"]),
        height=float(command.get("height", 100.0)),
        layer=layer,
        rotation_degrees=command.get("rotation_degrees"),
    )


def _render_insert_placeholder(doc, msp, command: dict) -> None:
    layer = _layer_for(command)
    ensure_preview_layer(doc, layer)
    position = _point2(command["position"])
    scale = float(command.get("scale", 1.0))
    radius = max(25.0 * scale, 10.0)

    msp.add_circle(position, radius, dxfattribs={"layer": layer})
    _add_text(
        msp=msp,
        text=f"BLOCK: {command['block_name']}",
        position=(position[0] + radius * 1.5, position[1]),
        height=max(35.0 * scale, 10.0),
        layer=layer,
        rotation_degrees=command.get("rotation_degrees"),
    )


def _render_dim_linear_preview(doc, msp, command: dict) -> None:
    layer = _layer_for(command, default="DIMENSION")
    ensure_preview_layer(doc, layer)
    start = _point2(command["from"])
    end = _point2(command["to"])
    dim_position = _point2(command["dim_line_position"])

    msp.add_line(start, end, dxfattribs={"layer": layer})
    msp.add_line(
        (start[0], dim_position[1]),
        (end[0], dim_position[1]),
        dxfattribs={"layer": layer},
    )
    _add_text(
        msp=msp,
        text=command.get("text_override") or "<dim>",
        position=dim_position,
        height=50.0,
        layer=layer,
    )


_RENDERERS = {
    "LAYER": _render_layer,
    "LINE": _render_line,
    "CIRCLE": _render_circle,
    "ARC": _render_arc,
    "ELLIPSE": _render_ellipse,
    "POLYLINE": _render_polyline,
    "TEXT": _render_text,
    "INSERT": _render_insert_placeholder,
    "DIM_LINEAR": _render_dim_linear_preview,
}


def _set_units_to_mm(doc) -> None:
    try:
        doc.units = ezdxf.units.MM
    except Exception:
        pass

    try:
        doc.header["$INSUNITS"] = 4
    except Exception:
        pass


def render_preview(
    commands: list[dict],
    output_path: str,
) -> str:
    """Render structured commands into a DXF preview file."""
    if not isinstance(commands, list) or not commands:
        raise PreviewRenderError("commands must be a non-empty list")

    try:
        doc = ezdxf.new(dxfversion="R2010", setup=True)
        _set_units_to_mm(doc)
        msp = doc.modelspace()
    except Exception as exc:
        raise PreviewRenderError(
            f"Failed to create preview DXF document: {type(exc).__name__}: {exc}"
        ) from exc

    for index, command in enumerate(commands):
        try:
            command_type = command.get("command")
            renderer = _RENDERERS.get(command_type)
            if renderer is None:
                raise PreviewRenderError(f"Unsupported command type: {command_type}")

            renderer(doc, msp, command)
        except Exception as exc:
            _add_preview_error_marker(doc, msp, index, command, exc)

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        doc.saveas(str(output))
    except Exception as exc:
        raise PreviewRenderError(
            f"Failed to save preview DXF: {type(exc).__name__}: {exc}"
        ) from exc

    return str(output)


def render_preview_sequence(
    command_sequence: dict,
    output_path: str,
) -> str:
    """Validate and render a full command sequence into a DXF preview."""
    validation_errors = validate_command_sequence(command_sequence)
    if validation_errors:
        joined_errors = "\n".join(f"- {error}" for error in validation_errors)
        raise PreviewRenderError(f"Invalid command sequence:\n{joined_errors}")

    return render_preview(command_sequence["commands"], output_path)

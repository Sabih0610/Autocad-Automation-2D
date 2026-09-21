"""Deterministic AutoCAD COM executor for basic 3D CAD scene primitives."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Callable

from src.backup import backup_file
from src.cad.session import (
    _same_document_identity,
    _snapshot_open_documents,
    close_document,
    open_document,
    summarize_bookkeeping_warnings,
)
from src.framework.cad3d.scene_schema import validate_cad3d_scene
from src.framework.cad3d.routing import (
    CAD3DRoutingError,
    count_pipe_connections,
    expand_pipe_connections,
)
from src.framework.commands.executor import (
    _activate_regen_zoom,
    _safe_get_document_name,
    _safe_get_dwg_path,
    _safe_modelspace_count,
    acad_point,
)
from src.parametric.vessel.dwg_export import _com_retry, _get_acad


class AutoCAD3DExecutionError(Exception):
    """Raised when a 3D CAD scene cannot be executed."""


# AutoCAD ACI color palette for demo/presentation 3D models.
# 1 red, 2 yellow, 3 green, 4 cyan, 5 blue, 6 magenta,
# 7 white/black foreground, 8 gray, 9 light gray, 30 orange-ish.
CAD3D_LAYER_TANKS = "CAD3D_TANKS"
CAD3D_LAYER_VESSELS = "CAD3D_VESSELS"
CAD3D_LAYER_PUMPS = "CAD3D_PUMPS"
CAD3D_LAYER_EXCHANGERS = "CAD3D_EXCHANGERS"
CAD3D_LAYER_PIPES = "CAD3D_PIPES"
CAD3D_LAYER_VALVES = "CAD3D_VALVES"
CAD3D_LAYER_FLANGES = "CAD3D_FLANGES"
CAD3D_LAYER_SUPPORTS = "CAD3D_SUPPORTS"
CAD3D_LAYER_SKID = "CAD3D_SKID"
CAD3D_LAYER_LABELS = "CAD3D_LABELS"
CAD3D_LAYER_GENERIC = "CAD3D_GENERIC"

CAD3D_PRESENTATION_LAYERS = {
    CAD3D_LAYER_TANKS: 5,       # blue
    CAD3D_LAYER_VESSELS: 4,     # cyan
    CAD3D_LAYER_PUMPS: 30,      # orange-ish
    CAD3D_LAYER_EXCHANGERS: 1,  # red
    CAD3D_LAYER_PIPES: 3,       # green
    CAD3D_LAYER_VALVES: 6,      # magenta
    CAD3D_LAYER_FLANGES: 2,     # yellow
    CAD3D_LAYER_SUPPORTS: 8,    # gray
    CAD3D_LAYER_SKID: 9,        # neutral gray
    CAD3D_LAYER_LABELS: 7,      # white / foreground
    CAD3D_LAYER_GENERIC: 9,
}


def _point3(point: list[float]) -> list[float]:
    if not isinstance(point, (list, tuple)) or len(point) != 3:
        raise ValueError("point must be [x, y, z]")

    try:
        return [float(point[0]), float(point[1]), float(point[2])]
    except (TypeError, ValueError) as exc:
        raise ValueError("point must contain numeric x, y, z values") from exc


def _distance3(a, b) -> float:
    pa = _point3(a)
    pb = _point3(b)
    return math.sqrt(sum((pb[index] - pa[index]) ** 2 for index in range(3)))


def _distance_3d(a, b) -> float:
    return _distance3(a, b)


def _midpoint3(a, b) -> list[float]:
    pa = _point3(a)
    pb = _point3(b)
    return [(pa[index] + pb[index]) / 2.0 for index in range(3)]


def _segment_midpoint(a, b) -> list[float]:
    return _midpoint3(a, b)


def _is_axis_aligned_segment(a, b, tolerance=1e-6) -> tuple[bool, str | None]:
    pa = _point3(a)
    pb = _point3(b)
    deltas = [abs(pb[index] - pa[index]) for index in range(3)]
    changing_axes = [index for index, delta in enumerate(deltas) if delta > tolerance]

    if len(changing_axes) != 1:
        return False, None

    return True, ["X", "Y", "Z"][changing_axes[0]]


def _acad_point3(point: list[float]):
    x, y, z = _point3(point)
    return acad_point(x, y, z)


def _active_document(acad: Any):
    try:
        doc = _com_retry(lambda: acad.ActiveDocument, "getting active document")
    except Exception as exc:
        raise AutoCAD3DExecutionError("No active AutoCAD document is available.") from exc

    if doc is None:
        raise AutoCAD3DExecutionError("No active AutoCAD document is available.")

    return doc


def _document_path(doc: Any, target_dwg_path: str | None) -> str | None:
    if target_dwg_path:
        return str(Path(target_dwg_path))

    return _safe_get_dwg_path(doc)


def _ensure_layer(doc: Any, layer_name: str, color: int | None = None):
    """Ensure a layer exists and optionally set its AutoCAD ACI color."""
    if not layer_name or layer_name == "0":
        return None

    layers = _com_retry(lambda: doc.Layers, "getting layers")

    try:
        layer = _com_retry(lambda: layers.Item(layer_name), f"getting layer {layer_name}")
    except Exception:
        layer = _com_retry(lambda: layers.Add(layer_name), f"creating layer {layer_name}")

    if color is not None:
        try:
            _com_retry(
                lambda: setattr(layer, "Color", int(color)),
                f"setting layer {layer_name} color",
            )
        except Exception:
            # Layer color is presentation polish. It should never block geometry.
            pass

    return layer


def _ensure_cad3d_presentation_layers(doc: Any) -> None:
    """Create/update standard CAD3D presentation layers."""
    for layer_name, color in CAD3D_PRESENTATION_LAYERS.items():
        _ensure_layer(doc, layer_name, color)


def _cad3d_layer_for_component(component: dict) -> str:
    component_type = component.get("component_type")

    if component_type == "vertical_tank_3d":
        return CAD3D_LAYER_TANKS

    if component_type == "horizontal_vessel_3d":
        return CAD3D_LAYER_VESSELS

    if component_type == "pump_placeholder_3d":
        return CAD3D_LAYER_PUMPS

    if component_type == "heat_exchanger_3d":
        return CAD3D_LAYER_EXCHANGERS

    if component_type == "pipe_run_3d":
        return CAD3D_LAYER_PIPES

    if component_type == "valve_placeholder_3d":
        return CAD3D_LAYER_VALVES

    if component_type == "flange_3d":
        return CAD3D_LAYER_FLANGES

    if component_type in {
        "support_leg_3d",
        "saddle_support_3d",
        "pipe_support_3d",
    }:
        return CAD3D_LAYER_SUPPORTS

    if component_type == "skid_base_3d":
        return CAD3D_LAYER_SKID

    if component_type == "label_3d":
        return CAD3D_LAYER_LABELS

    return CAD3D_LAYER_GENERIC


def _presentation_color_for_layer(layer_name: str | None) -> int | None:
    if not layer_name:
        return None
    return CAD3D_PRESENTATION_LAYERS.get(layer_name)


def _apply_presentation_style(entity: Any, component: dict) -> None:
    """Assign layer/color to a created AutoCAD entity.

    Explicit component ``layer`` and ``color`` values win. Otherwise the
    component type decides the presentation layer/color.
    """
    layer_name = component.get("layer") or _cad3d_layer_for_component(component)

    if "color" in component:
        color = component["color"]
    else:
        color = _presentation_color_for_layer(layer_name)

    if layer_name:
        try:
            _com_retry(
                lambda: setattr(entity, "Layer", layer_name),
                f"setting entity layer {layer_name}",
            )
        except Exception:
            # Presentation styling should not break geometry execution.
            pass

    if color is not None:
        try:
            _com_retry(lambda: setattr(entity, "Color", int(color)), "setting entity color")
        except Exception:
            # Presentation styling should not break geometry execution.
            pass


def _set_optional_color(entity: Any, component: dict) -> None:
    """Backward-compatible helper for older tests/callers."""
    if "color" not in component:
        return

    try:
        _com_retry(lambda: setattr(entity, "Color", int(component["color"])), "setting 3D entity color")
    except Exception:
        pass


def _set_optional_layer(entity: Any, layer: str | None = None) -> None:
    if not layer:
        return

    try:
        _com_retry(lambda: setattr(entity, "Layer", layer), "setting 3D entity layer")
    except Exception:
        pass


def _rotate_cylinder_to_orientation(entity: Any, center: list[float], orientation: str) -> None:
    if not hasattr(entity, "Rotate3D"):
        return

    cx, cy, cz = center

    if orientation == "Z":
        return
    if orientation == "X":
        axis_end = [cx, cy + 1.0, cz]
        angle = math.pi / 2.0
    elif orientation == "Y":
        axis_end = [cx + 1.0, cy, cz]
        angle = -math.pi / 2.0
    else:
        raise AutoCAD3DExecutionError(f"Unsupported 3D cylinder orientation: {orientation}")

    try:
        _com_retry(
            lambda: entity.Rotate3D(_acad_point3(center), _acad_point3(axis_end), angle),
            f"rotating cylinder to {orientation} orientation",
        )
    except Exception:
        # The vertical cylinder remains a usable placeholder if rotation is not supported.
        pass


def _execute_vertical_tank_3d(doc, component: dict) -> int:
    msp = _com_retry(lambda: doc.ModelSpace, "getting model space")
    center = _point3(component["center"])
    radius = float(component["diameter"]) / 2.0
    height = float(component["height"])
    entity = _com_retry(
        lambda: msp.AddCylinder(_acad_point3(center), radius, height),
        f"adding vertical tank {component.get('id')}",
    )
    _apply_presentation_style(entity, component)
    return 1


def _execute_horizontal_vessel_3d(doc, component: dict) -> int:
    msp = _com_retry(lambda: doc.ModelSpace, "getting model space")
    center = _point3(component["center"])
    radius = float(component["diameter"]) / 2.0
    length = float(component["length"])
    orientation = component["orientation"]
    entity = _com_retry(
        lambda: msp.AddCylinder(_acad_point3(center), radius, length),
        f"adding horizontal vessel {component.get('id')}",
    )
    _rotate_cylinder_to_orientation(entity, center, orientation)
    _apply_presentation_style(entity, component)
    return 1


def _execute_oriented_cylinder_3d(
    doc,
    component: dict,
    diameter_key: str,
    length_key: str,
    description: str,
) -> int:
    msp = _com_retry(lambda: doc.ModelSpace, "getting model space")
    center = _point3(component["center"])
    radius = float(component[diameter_key]) / 2.0
    length = float(component[length_key])
    orientation = component.get("orientation", "Z")
    entity = _com_retry(
        lambda: msp.AddCylinder(_acad_point3(center), radius, length),
        f"adding {description} {component.get('id')}",
    )
    _rotate_cylinder_to_orientation(entity, center, orientation)
    _apply_presentation_style(entity, component)
    return 1


def _execute_heat_exchanger_3d(doc, component: dict) -> int:
    return _execute_oriented_cylinder_3d(
        doc,
        component,
        diameter_key="diameter",
        length_key="length",
        description="heat exchanger",
    )


def _execute_box_3d(doc, component: dict) -> int:
    msp = _com_retry(lambda: doc.ModelSpace, "getting model space")
    entity = _com_retry(
        lambda: msp.AddBox(
            _acad_point3(component["center"]),
            float(component["length"]),
            float(component["width"]),
            float(component["height"]),
        ),
        f"adding box {component.get('id')}",
    )
    _apply_presentation_style(entity, component)
    return 1


def _execute_pump_placeholder_3d(doc, component: dict) -> int:
    return _execute_box_3d(doc, component)


def _execute_valve_placeholder_3d(doc, component: dict) -> int:
    return _execute_box_3d(doc, component)


def _execute_nozzle_3d(doc, component: dict) -> int:
    return _execute_oriented_cylinder_3d(
        doc,
        component,
        diameter_key="diameter",
        length_key="length",
        description="nozzle",
    )


def _execute_flange_3d(doc, component: dict) -> int:
    return _execute_oriented_cylinder_3d(
        doc,
        component,
        diameter_key="diameter",
        length_key="thickness",
        description="flange",
    )


def _execute_support_leg_3d(doc, component: dict) -> int:
    return _execute_oriented_cylinder_3d(
        doc,
        component,
        diameter_key="diameter",
        length_key="height",
        description="support leg",
    )


def _execute_saddle_support_3d(doc, component: dict) -> int:
    return _execute_box_3d(doc, component)


def _execute_pipe_support_3d(doc, component: dict) -> int:
    msp = _com_retry(lambda: doc.ModelSpace, "getting model space")
    entity = _com_retry(
        lambda: msp.AddBox(
            _acad_point3(component["center"]),
            float(component["width"]),
            float(component["depth"]),
            float(component["height"]),
        ),
        f"adding pipe support {component.get('id')}",
    )
    _apply_presentation_style(entity, component)
    return 1


def _execute_skid_base_3d(doc, component: dict) -> int:
    return _execute_box_3d(doc, component)


def _add_pipe_centerline_segment(
    modelspace,
    start,
    end,
    layer=None,
    component: dict | None = None,
):
    entity = _com_retry(
        lambda: modelspace.AddLine(_acad_point3(start), _acad_point3(end)),
        "adding 3D pipe centerline segment",
    )

    if component is not None:
        _apply_presentation_style(entity, component)
    else:
        _set_optional_layer(entity, layer)

    return entity


def _add_axis_aligned_pipe_cylinder(
    modelspace,
    start,
    end,
    diameter,
    layer=None,
    component: dict | None = None,
):
    clean_start = _point3(start)
    clean_end = _point3(end)
    length = _distance_3d(clean_start, clean_end)
    if length <= 0:
        return None

    is_axis_aligned, axis = _is_axis_aligned_segment(clean_start, clean_end)
    if not is_axis_aligned or axis is None:
        raise AutoCAD3DExecutionError("Pipe cylinder segments must be axis-aligned")

    clean_diameter = float(diameter)
    if clean_diameter <= 0:
        raise AutoCAD3DExecutionError("Pipe diameter must be positive")

    center = _segment_midpoint(clean_start, clean_end)
    entity = _com_retry(
        lambda: modelspace.AddCylinder(_acad_point3(center), clean_diameter / 2.0, length),
        "adding 3D pipe solid cylinder",
    )

    if component is not None:
        _apply_presentation_style(entity, component)
    else:
        _set_optional_layer(entity, layer)

    if axis == "Z":
        return entity

    if not hasattr(entity, "Rotate3D"):
        if hasattr(entity, "Delete"):
            try:
                _com_retry(lambda: entity.Delete(), "deleting unrotated pipe cylinder")
            except Exception:
                pass
        raise AutoCAD3DExecutionError("Pipe cylinder rotation is unavailable")

    cx, cy, cz = center
    if axis == "X":
        axis_end = [cx, cy + 1.0, cz]
        angle = math.pi / 2.0
    else:
        axis_end = [cx + 1.0, cy, cz]
        angle = -math.pi / 2.0

    try:
        _com_retry(
            lambda: entity.Rotate3D(_acad_point3(center), _acad_point3(axis_end), angle),
            f"rotating pipe cylinder to {axis} axis",
        )
    except Exception as exc:
        if hasattr(entity, "Delete"):
            try:
                _com_retry(lambda: entity.Delete(), "deleting unrotated pipe cylinder")
            except Exception:
                pass
        raise AutoCAD3DExecutionError(f"Pipe cylinder rotation failed for {axis} axis") from exc

    return entity


def _pipe_visual_options(component: dict) -> tuple[bool, bool]:
    visual_style = component.get("visual_style") or "solid_with_centerline"
    if visual_style not in {"centerline", "solid", "solid_with_centerline"}:
        raise AutoCAD3DExecutionError(f"Unsupported pipe visual_style: {visual_style}")

    draw_solid = visual_style in {"solid", "solid_with_centerline"}
    if "draw_centerline" in component:
        draw_centerline = bool(component["draw_centerline"])
    else:
        draw_centerline = visual_style in {"centerline", "solid_with_centerline"}

    return draw_solid, draw_centerline


def _execute_pipe_run_3d(doc, component: dict) -> int:
    msp = _com_retry(lambda: doc.ModelSpace, "getting model space")
    points = [_point3(point) for point in component["points"]]
    diameter = float(component["diameter"])

    # Preserve explicit pipe layer if provided; otherwise default to CAD3D_PIPES.
    layer = component.get("layer") or component.get("metadata", {}).get("layer")
    style_component = dict(component)
    if layer and "layer" not in style_component:
        style_component["layer"] = layer

    draw_solid, draw_centerline = _pipe_visual_options(component)
    created = 0

    for start, end in zip(points, points[1:]):
        if _distance_3d(start, end) <= 0:
            continue

        fallback_centerline_created = False

        if draw_solid:
            try:
                entity = _add_axis_aligned_pipe_cylinder(
                    msp,
                    start,
                    end,
                    diameter,
                    layer=layer,
                    component=style_component,
                )
                if entity is not None:
                    created += 1
            except Exception:
                _add_pipe_centerline_segment(
                    msp,
                    start,
                    end,
                    layer=layer,
                    component=style_component,
                )
                created += 1
                fallback_centerline_created = True

        if draw_centerline and not fallback_centerline_created:
            _add_pipe_centerline_segment(
                msp,
                start,
                end,
                layer=layer,
                component=style_component,
            )
            created += 1

    return created


def _execute_label_3d(doc, component: dict) -> int:
    msp = _com_retry(lambda: doc.ModelSpace, "getting model space")
    entity = _com_retry(
        lambda: msp.AddText(
            component["text"],
            _acad_point3(component["position"]),
            float(component["height"]),
        ),
        f"adding 3D label {component.get('id')}",
    )
    _apply_presentation_style(entity, component)
    return 1


_COMPONENT_HANDLERS: dict[str, Callable[[Any, dict], int]] = {
    "vertical_tank_3d": _execute_vertical_tank_3d,
    "horizontal_vessel_3d": _execute_horizontal_vessel_3d,
    "heat_exchanger_3d": _execute_heat_exchanger_3d,
    "pump_placeholder_3d": _execute_pump_placeholder_3d,
    "valve_placeholder_3d": _execute_valve_placeholder_3d,
    "nozzle_3d": _execute_nozzle_3d,
    "flange_3d": _execute_flange_3d,
    "support_leg_3d": _execute_support_leg_3d,
    "saddle_support_3d": _execute_saddle_support_3d,
    "pipe_support_3d": _execute_pipe_support_3d,
    "pipe_run_3d": _execute_pipe_run_3d,
    "skid_base_3d": _execute_skid_base_3d,
    "box_3d": _execute_box_3d,
    "label_3d": _execute_label_3d,
}


def _execute_component_3d(doc, component: dict) -> int:
    component_type = component.get("component_type")
    handler = _COMPONENT_HANDLERS.get(component_type)

    if handler is None:
        raise AutoCAD3DExecutionError(f"Unsupported 3D component type: {component_type}")

    return handler(doc, component)


def execute_cad3d_scene(
    scene: dict,
    target_dwg_path: str | None = None,
    save: bool = False,
    zoom_extents: bool = True,
) -> dict:
    """Execute a validated CAD3D scene into AutoCAD through COM."""
    validation_errors = validate_cad3d_scene(
        scene
    )

    if validation_errors:
        joined_errors = "\n".join(
            f"- {error}"
            for error in validation_errors
        )

        raise AutoCAD3DExecutionError(
            f"Invalid CAD3D scene:\n"
            f"{joined_errors}"
        )

    original_component_count = len(
        scene["components"]
    )

    pipe_connections_expanded = (
        count_pipe_connections(scene)
    )

    try:
        expanded_scene = expand_pipe_connections(
            scene
        )
    except CAD3DRoutingError as exc:
        raise AutoCAD3DExecutionError(
            "CAD3D pipe routing failed: "
            f"{exc}"
        ) from exc

    expanded_validation_errors = (
        validate_cad3d_scene(
            expanded_scene
        )
    )

    if expanded_validation_errors:
        joined_errors = "\n".join(
            f"- {error}"
            for error
            in expanded_validation_errors
        )

        raise AutoCAD3DExecutionError(
            "Invalid expanded CAD3D scene:\n"
            f"{joined_errors}"
        )

    acad = _get_acad()
    bookkeeping_warnings: list[str] = []
    result: dict | None = None

    opened_here = False

    # `is not None`, not truthiness: an explicitly-sent empty string
    # remains an explicit invalid target rather than silently falling
    # back to whatever drawing is currently focused.
    if target_dwg_path is not None:
        # Capture ownership BEFORE the complete retry sequence.
        #
        # A failed first open attempt may already have caused AutoCAD
        # to open the target drawing. If a later retry then sees that
        # drawing already open, its local opened_here flag is False.
        #
        # We therefore determine ownership relative to the state that
        # existed before any retry attempt occurred.
        open_before_retry = (
            _snapshot_open_documents(acad)
        )

        doc, _attempt_opened_here = _com_retry(
            lambda: open_document(
                acad,
                str(target_dwg_path),
                bookkeeping_warnings=bookkeeping_warnings,
            ),
            f"opening DWG {target_dwg_path}",
        )

        opened_here = not any(
            _same_document_identity(
                doc,
                existing_doc,
            )
            for existing_doc
            in open_before_retry
        )
    else:
        doc = _active_document(acad)

    try:
        document_name = (
            _safe_get_document_name(doc)
        )

        dwg_path = _document_path(
            doc,
            target_dwg_path,
        )

        backup_path = None
        backup_skipped_reason = None

        if save:
            if (
                dwg_path
                and Path(dwg_path).is_file()
            ):
                backup_path = str(
                    backup_file(
                        Path(dwg_path)
                    )
                )

            elif not dwg_path:
                backup_skipped_reason = (
                    "Backup skipped because the active document "
                    "is unsaved/untitled and has no file path."
                )

            else:
                backup_skipped_reason = (
                    "Backup skipped because the drawing path "
                    "is not an existing file: "
                    f"{dwg_path}"
                )

        # An untitled document has no prior on-disk drawing to
        # protect. It is safe to permit Save after successful
        # execution even though no backup can exist.
        #
        # Presentation layers are best-effort. They must never
        # block geometry.
        presentation_layers_created = False
        presentation_layer_error = None

        try:
            _ensure_cad3d_presentation_layers(
                doc
            )

            presentation_layers_created = True

        except Exception as exc:
            presentation_layer_error = (
                f"{type(exc).__name__}: "
                f"{exc}"
            )

        msp = _com_retry(
            lambda: doc.ModelSpace,
            "getting model space",
        )

        entity_count_before = (
            _safe_modelspace_count(msp)
        )

        executed_count = 0
        errors: list[dict[str, Any]] = []

        components = expanded_scene[
            "components"
        ]

        for index, component in enumerate(
            components
        ):
            try:
                created_entities = (
                    _execute_component_3d(
                        doc,
                        component,
                    )
                )

                if created_entities <= 0:
                    raise AutoCAD3DExecutionError(
                        "No entities were created "
                        "for component "
                        f"{component.get('id')}"
                    )

                executed_count += 1

            except Exception as exc:
                errors.append(
                    {
                        "component_index": index,
                        "component_id":
                            component.get("id"),
                        "component_type":
                            component.get(
                                "component_type"
                            ),
                        "error": (
                            f"{type(exc).__name__}: "
                            f"{exc}"
                        ),
                    }
                )

        if save and not errors:
            try:
                _com_retry(
                    lambda: doc.Save(),
                    "saving document",
                )

            except Exception as exc:
                errors.append(
                    {
                        "component_index": None,
                        "component_id": None,
                        "component_type": "SAVE",
                        "error": (
                            f"{type(exc).__name__}: "
                            f"{exc}"
                        ),
                    }
                )

        entity_count_after = (
            _safe_modelspace_count(msp)
        )

        zoom_extents_called = False
        zoom_error = None

        if zoom_extents:
            (
                zoom_extents_called,
                zoom_error,
            ) = _activate_regen_zoom(
                acad,
                doc,
            )

        result = {
            "ok": not errors,
            "executed_count": executed_count,
            "total_count": len(components),
            "pipe_connections_expanded":
                pipe_connections_expanded,
            "executable_component_count":
                len(components),
            "original_component_count":
                original_component_count,
            "errors": errors,
            "dwg_path": dwg_path,
            "document_name": document_name,
            "entity_count_before":
                entity_count_before,
            "entity_count_after":
                entity_count_after,
            "zoom_extents_called":
                zoom_extents_called,
            "zoom_error": zoom_error,
            "presentation_layers_created":
                presentation_layers_created,
            "presentation_layer_error":
                presentation_layer_error,
            "backup_path": backup_path,
            "backup_skipped_reason":
                backup_skipped_reason,
            "session_bookkeeping_skipped_reason":
                None,
        }

    finally:
        if opened_here:
            _safe_close_document(
                doc,
                str(target_dwg_path),
                bookkeeping_warnings,
            )

    if result is None:
        raise AutoCAD3DExecutionError(
            "CAD3D execution produced no result"
        )

    result[
        "session_bookkeeping_skipped_reason"
    ] = summarize_bookkeeping_warnings(
        bookkeeping_warnings
    )

    return result


def _safe_close_document(
    doc: Any,
    target_dwg_path: str,
    bookkeeping_warnings: list[str] | None = None,
) -> None:
    try:
        close_document(
            doc,
            target_dwg_path,
            bookkeeping_warnings=bookkeeping_warnings,
        )
    except Exception:
        pass

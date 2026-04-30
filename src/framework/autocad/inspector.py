"""Read-only AutoCAD drawing inspection helpers.

This module connects to the currently active AutoCAD drawing and extracts a
best-effort snapshot of ModelSpace entities. It does not modify, delete, move,
or create AutoCAD entities.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterator

from src.parametric.vessel.dwg_export import (
    AutoCADNotRunningError,
    _com_retry,
    _get_acad,
)


class DrawingInspectionError(Exception):
    """Raised when the active drawing cannot be inspected."""


def _safe_get(obj: Any, attr: str, default=None):
    """Best-effort COM property read."""
    try:
        return _com_retry(
            lambda: getattr(obj, attr, default),
            f"reading {attr}",
        )
    except Exception:
        return default


def _to_xyz(value) -> list[float] | None:
    """Convert a COM point-like value to a three-number list."""
    if value is None or isinstance(value, (str, bytes)):
        return None

    for attr in ("value", "Value"):
        try:
            nested = getattr(value, attr)
        except Exception:
            continue
        if nested is not None and nested is not value:
            value = nested
            break

    try:
        parts = list(value)
    except Exception:
        return None

    if len(parts) < 2:
        return None

    if len(parts) == 2:
        parts.append(0.0)

    try:
        return [float(parts[0]), float(parts[1]), float(parts[2])]
    except Exception:
        return None


def _safe_float(value) -> float | None:
    if value is None:
        return None

    try:
        return float(value)
    except Exception:
        return None


def _safe_int(value) -> int | None:
    if value is None:
        return None

    try:
        return int(value)
    except Exception:
        return None


def _safe_bbox(entity) -> dict | None:
    """Read an entity bounding box when AutoCAD exposes one."""
    get_bbox = _safe_get(entity, "GetBoundingBox")
    if get_bbox is None:
        return None

    try:
        result = _com_retry(
            lambda: get_bbox(),
            "reading entity bounding box",
        )
        if isinstance(result, (tuple, list)) and len(result) >= 2:
            min_point = _to_xyz(result[0])
            max_point = _to_xyz(result[1])
            if min_point is not None and max_point is not None:
                return {"min": min_point, "max": max_point}
    except Exception:
        pass

    try:
        import pythoncom
        import win32com.client

        min_point = win32com.client.VARIANT(
            pythoncom.VT_BYREF | pythoncom.VT_ARRAY | pythoncom.VT_R8,
            [0.0, 0.0, 0.0],
        )
        max_point = win32com.client.VARIANT(
            pythoncom.VT_BYREF | pythoncom.VT_ARRAY | pythoncom.VT_R8,
            [0.0, 0.0, 0.0],
        )
        _com_retry(
            lambda: get_bbox(min_point, max_point),
            "reading entity bounding box",
        )

        min_xyz = _to_xyz(min_point)
        max_xyz = _to_xyz(max_point)
        if min_xyz is not None and max_xyz is not None:
            return {"min": min_xyz, "max": max_xyz}
    except Exception:
        return None

    return None


def inspect_entity(entity, index: int) -> dict:
    """Return a best-effort read-only summary of a ModelSpace entity."""
    object_name = _safe_get(entity, "ObjectName")
    position = _to_xyz(_safe_get(entity, "Position"))

    if position is None:
        position = _to_xyz(_safe_get(entity, "InsertionPoint"))

    text = _safe_get(entity, "TextString")
    if text is None and object_name in {"AcDbBlockReference", "AcDbMInsertBlock"}:
        text = _safe_get(entity, "Name")

    return {
        "index": index,
        "handle": _safe_get(entity, "Handle"),
        "object_name": object_name,
        "entity_type": object_name,
        "layer": _safe_get(entity, "Layer"),
        "color": _safe_int(_safe_get(entity, "Color")),
        "linetype": _safe_get(entity, "Linetype"),
        "position": position,
        "center": _to_xyz(_safe_get(entity, "Center")),
        "radius": _safe_float(_safe_get(entity, "Radius")),
        "start_point": _to_xyz(_safe_get(entity, "StartPoint")),
        "end_point": _to_xyz(_safe_get(entity, "EndPoint")),
        "text": text,
        "bbox": _safe_bbox(entity),
    }


def _safe_modelspace_count(msp) -> int | None:
    try:
        return int(_com_retry(lambda: msp.Count, "reading modelspace count"))
    except Exception:
        pass

    try:
        return len(msp)
    except Exception:
        return None


def _iter_modelspace_entities(msp, max_entities: int) -> Iterator[tuple[int, Any]]:
    try:
        iterator = iter(msp)
    except Exception:
        iterator = None

    if iterator is not None:
        for index, entity in enumerate(iterator):
            if index >= max_entities:
                break
            yield index, entity
        return

    total_count = _safe_modelspace_count(msp)
    limit = max_entities if total_count is None else min(max_entities, total_count)

    for index in range(limit):
        try:
            entity = _com_retry(
                lambda index=index: msp.Item(index),
                f"reading modelspace entity {index}",
            )
        except Exception:
            continue

        yield index, entity


def inspect_active_drawing(max_entities: int = 500) -> dict:
    """Inspect the active AutoCAD drawing without changing it."""
    if max_entities < 1:
        raise DrawingInspectionError("max_entities must be at least 1")

    try:
        acad = _get_acad()
    except AutoCADNotRunningError:
        raise
    except Exception as exc:
        raise DrawingInspectionError(
            f"Failed to connect to AutoCAD: {type(exc).__name__}: {exc}"
        ) from exc

    try:
        doc = _com_retry(lambda: acad.ActiveDocument, "getting active document")
    except Exception as exc:
        raise DrawingInspectionError("No active AutoCAD document is available.") from exc

    if doc is None:
        raise DrawingInspectionError("No active AutoCAD document is available.")

    try:
        msp = _com_retry(lambda: doc.ModelSpace, "getting model space")
    except Exception as exc:
        raise DrawingInspectionError(
            f"Failed to read ModelSpace: {type(exc).__name__}: {exc}"
        ) from exc

    total_count = _safe_modelspace_count(msp)
    entities = [
        inspect_entity(entity, index)
        for index, entity in _iter_modelspace_entities(msp, max_entities)
    ]

    truncated = total_count is not None and total_count > max_entities

    return {
        "ok": True,
        "document_name": _safe_get(doc, "Name"),
        "dwg_path": _safe_get(doc, "FullName"),
        "entity_count_total": total_count,
        "entity_count_returned": len(entities),
        "truncated": truncated,
        "entities": entities,
    }


def summarize_drawing_state(inspection: dict) -> str:
    """Create a compact human-readable summary of an inspection result."""
    document_name = inspection.get("document_name") or "<unnamed drawing>"
    returned = inspection.get("entity_count_returned", 0)
    entities = inspection.get("entities") or []

    layers = sorted(
        {
            entity.get("layer")
            for entity in entities
            if entity.get("layer")
        }
    )
    type_counts = Counter(
        entity.get("entity_type") or entity.get("object_name") or "Unknown"
        for entity in entities
    )

    layers_text = ", ".join(layers) if layers else "none"
    types_text = (
        ", ".join(
            f"{entity_type}={count}"
            for entity_type, count in sorted(type_counts.items())
        )
        if type_counts
        else "none"
    )

    return (
        f"{document_name}: {returned} entities returned. "
        f"Layers: {layers_text}. Types: {types_text}."
    )

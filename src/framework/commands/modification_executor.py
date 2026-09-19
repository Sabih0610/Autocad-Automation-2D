"""Deterministic in-place edits. All coordinates are computed here, not by AI."""
from dataclasses import dataclass
import math
from pathlib import Path

from src.cad.geometry import resize_endpoint, box_for_points
from src.cad.session import CAD_LOCK, cad_session, canonical_path, get_document, point
from src.cad.units import from_mm
from src.cad.scanner import file_hash
from src.cad.relationships import related_entities
from src.storage.database import connection
from src.storage.entity_repository import get_entity
from src.storage.spatial import SpatialIndex, bounds_distance
from .operation_schema import validate_operation


@dataclass
class Assignment:
    obj: object
    property: str
    before: object
    after: object
    handle: str | None = None
    is_point: bool = False

    def summary(self):
        return dict(handle=self.handle, field=self.property, before=self.before, after=self.after)


def _assign(change, value):
    setattr(change.obj, change.property, point(value) if change.is_point else value)


def _indexed_record(path, handle, eid=None):
    if eid:
        record = get_entity(eid)
        if record["path"] != path or record["handle"] != handle:
            raise ValueError("Operation does not match the indexed entity")
        return record
    with connection() as conn:
        rows = conn.execute("""SELECT e.entity_id FROM entities e JOIN drawings d ON d.drawing_id=e.drawing_id
            WHERE d.path=? AND e.handle=?""", (path, handle)).fetchall()
    if len(rows) != 1:
        raise ValueError("Entity must be uniquely indexed before editing; scan and select a project")
    return get_entity(rows[0][0])


def _verify_index(record, path):
    if record["scan_status"] != "scanned":
        raise ValueError("Drawing index is stale; rescan before editing")
    with connection() as conn:
        expected = conn.execute("SELECT file_hash FROM drawings WHERE drawing_id=?", (record["drawing_id"],)).fetchone()[0]
    if file_hash(path) != expected:
        raise ValueError("Drawing changed since scanning; rescan before editing")


def _resize(doc, entity, op, record):
    units = int(doc.GetVariable("INSUNITS"))
    if units != record["units"]:
        raise ValueError("Live units differ from the index; save and rescan")
    delta = from_mm(op["delta_mm"], units) if "delta_mm" in op else None
    value = from_mm(op["value_mm"], units) if "value_mm" in op else None
    changes = []
    proposed = {}
    if op["dimension"] == "length":
        if entity.ObjectName != "AcDbLine" or record["entity_type"] != "LINE":
            raise ValueError("Length resizing currently supports LINE entities")
        start, end = tuple(entity.StartPoint), tuple(entity.EndPoint)
        indexed = record["geometry"]
        if not indexed or any(abs(indexed[f"{key}_{axis}"] - p[i]) > 1e-6
                              for key, p in (("start", start), ("end", end)) for i, axis in enumerate("xyz")):
            raise ValueError("Live geometry differs from the index; save and rescan")
        new_end = resize_endpoint(start, end, delta=delta, value=value)
        changes.append(Assignment(entity, "EndPoint", end, new_end, op["handle"], True))
        proposed[record["entity_id"]] = box_for_points(start, new_end)
        with connection() as conn:
            related = related_entities(conn, record["entity_id"])
            dependencies = conn.execute("""SELECT 1 FROM relationships WHERE relationship_type='depends_on'
                AND (source_entity_id=? OR target_entity_id=?)""", (record["entity_id"], record["entity_id"])).fetchall()
        if dependencies:
            raise ValueError("Explicit dependent/constraint entities require a supported dependency rule")
        offset = tuple(b - a for a, b in zip(end, new_end))
        for other in related:
            obj = doc.HandleToObject(other["handle"])
            other_record = get_entity(other["entity_id"])
            if other["drawing_id"] != record["drawing_id"]:
                raise ValueError("Spatial dependency crosses drawings")
            if obj.ObjectName == "AcDbBlockReference":
                before = tuple(obj.InsertionPoint)
                if math.dist(before, end) > from_mm(0.01, units):
                    continue  # connected at the fixed start end
                after = tuple(a + b for a, b in zip(before, offset))
                changes.append(Assignment(obj, "InsertionPoint", before, after, other["handle"], True))
                # Attribute coordinates are independent COM properties.
                if obj.HasAttributes:
                    for attr in obj.GetAttributes():
                        position = tuple(attr.InsertionPoint)
                        changes.append(Assignment(attr, "InsertionPoint", position,
                                                  tuple(a + b for a, b in zip(position, offset)), attr.Handle, True))
                proposed[other["entity_id"]] = {f"{kind}_{axis}": other_record["geometry"][f"{kind}_{axis}"] + offset[i]
                    for i, axis in enumerate("xyz") for kind in ("min", "max")}
            elif obj.ObjectName == "AcDbLine":
                a, b = tuple(obj.StartPoint), tuple(obj.EndPoint)
                field = "StartPoint" if math.dist(a, end) < from_mm(0.01, units) else "EndPoint" if math.dist(b, end) < from_mm(0.01, units) else None
                if field:
                    before = a if field == "StartPoint" else b
                    if math.dist(b if field == "StartPoint" else a, new_end) < 1e-9:
                        raise ValueError("Resize would collapse a connected line")
                    changes.append(Assignment(obj, field, before, new_end, other["handle"], True))
                    proposed[other["entity_id"]] = box_for_points(new_end if field == "StartPoint" else a, new_end if field == "EndPoint" else b)
            else:
                raise ValueError(f"Unsupported connected entity: {obj.ObjectName}")
    else:
        if entity.ObjectName not in {"AcDbCircle", "AcDbArc"}:
            raise ValueError("Radius resizing currently supports CIRCLE and ARC")
        before = float(entity.Radius)
        after = value if value is not None else before + delta
        if not math.isfinite(after) or after <= 0:
            raise ValueError("New radius must be positive and finite")
        changes.append(Assignment(entity, "Radius", before, after, op["handle"]))
        center = tuple(entity.Center)
        if tuple(entity.Normal) != (0.0, 0.0, 1.0):
            raise ValueError("Radius edits currently require a circle/arc in the XY plane")
        proposed[record["entity_id"]] = box_for_points((center[0]-after, center[1]-after, center[2]),
                                                       (center[0]+after, center[1]+after, center[2]))
    # Conservative bounds checks: reject newly introduced intersections with
    # unrelated entities. Existing touching/overlap is allowed to remain.
    index = SpatialIndex()
    for eid, new_box in proposed.items():
        old_box = get_entity(eid)["geometry"]
        reach = max(abs(new_box[key] - old_box[key]) for key in new_box) / from_mm(1, units) + 0.01
        for other in index.nearby(eid, reach):
            if other["entity_id"] in proposed:
                continue
            if bounds_distance(old_box, other) > 1e-8 and bounds_distance(new_box, other) <= 1e-8:
                raise ValueError(f"Resize introduces an overlap with handle {other['handle']}")
    return changes


def _prepare(doc, op, record):
    command = op["command"]
    if "handle" in op:
        obj = doc.HandleToObject(op["handle"])
        if obj.Handle.upper() != op["handle"].upper():
            raise ValueError("AutoCAD resolved a different handle")
    if command == "RESIZE_COMPONENT":
        return _resize(doc, obj, op, record)
    if command == "SET_ENTITY_PROPERTY":
        prop = {"color": "Color", "layer": "Layer", "linetype": "Linetype", "text": "TextString", "attribute": "TextString"}[op["property"]]
        if op["property"] == "attribute":
            matches = [a for a in obj.GetAttributes() if a.TagString.casefold() == op["attribute_tag"].casefold()]
            if len(matches) != 1:
                raise ValueError("Attribute tag is absent or ambiguous")
            obj = matches[0]
        if prop == "Layer":
            doc.Layers.Item(op["value"])
        if prop == "Linetype":
            doc.Linetypes.Item(op["value"])
        return [Assignment(obj, prop, getattr(obj, prop), op["value"], obj.Handle)]
    if command == "SET_LAYER_COLOR":
        obj = doc.Layers.Item(op["layer"])
        return [Assignment(obj, "Color", obj.Color, op["color"])]
    prop = {"title": "Title", "author": "Author", "subject": "Subject", "keywords": "Keywords",
            "comments": "Comments", "revision": "RevisionNumber"}.get(op["property"])
    if prop is None:
        return []  # Custom SummaryInfo uses methods, handled explicitly below.
    return [Assignment(doc.SummaryInfo, prop, getattr(doc.SummaryInfo, prop), op["value"])]


def rename_file(op):
    """Filesystem-only rename; session index and AutoCAD lock files gate it."""
    source = Path(canonical_path(op["target_dwg_path"]))
    destination = source.with_name(op["new_name"])
    if source.suffix.lower() != destination.suffix.lower() or destination.exists():
        raise ValueError("Rename must preserve the file type and may not overwrite a file")
    with connection() as conn:
        opened = conn.execute("SELECT is_open FROM drawing_sessions WHERE path=?", (str(source),)).fetchone()
        if (opened and opened[0]) or source.with_suffix(".dwl").exists() or source.with_suffix(".dwl2").exists():
            raise ValueError("Close the drawing in AutoCAD before renaming")
        source.rename(destination)
        try:
            conn.execute("UPDATE drawings SET path=?,filename=?,scan_status='pending' WHERE path=?", (str(destination), destination.name, str(source)))
            conn.execute("DELETE FROM drawing_sessions WHERE path=?", (str(source),))
        except Exception:
            destination.rename(source)
            raise
    return dict(path=str(destination), changes=[dict(handle=None, field="path", before=str(source), after=str(destination))])


def execute_operation(operation, *, acad=None, entity_id=None, verify_extractor=None):
    validate_operation(operation)
    path = canonical_path(operation["target_dwg_path"])
    with CAD_LOCK:
        if operation["command"] == "RENAME_FILE":
            return rename_file(operation)
        record = _indexed_record(path, operation["handle"], entity_id) if "handle" in operation else None
        if record:
            _verify_index(record, path)
        with cad_session(acad) as session:
            doc = get_document(session, path)
            if not doc.Saved:
                raise ValueError("Save or discard existing unsaved edits before modifying this drawing")
            changes = _prepare(doc, operation, record)
            applied = []
            custom = operation["command"] == "SET_DOCUMENT_PROPERTY" and operation["property"] == "custom"
            try:
                if custom:
                    info, key = doc.SummaryInfo, operation["key"]
                    try:
                        before = info.GetCustomByKey(key)
                    except Exception:
                        info.AddCustomInfo(key, operation["value"])
                        before = None
                    else:
                        info.SetCustomByKey(key, operation["value"])
                    summary = [dict(handle=None, field=f"custom:{key}", before=before, after=operation["value"])]
                else:
                    for change in changes:
                        applied.append(change)
                        _assign(change, change.after)
                    for change in changes:
                        actual = getattr(change.obj, change.property)
                        if change.is_point:
                            if math.dist(tuple(actual), change.after) > 1e-6:
                                raise ValueError("AutoCAD did not retain the assigned coordinate")
                        elif actual != change.after:
                            raise ValueError("AutoCAD did not retain the assigned property")
                    summary = [change.summary() for change in changes]
                doc.Save()
            except Exception:
                for change in reversed(applied):
                    _assign(change, change.before)
                if custom and 'before' in locals():
                    if before is None:
                        info.RemoveCustomByKey(key)
                    else:
                        info.SetCustomByKey(key, before)
                raise
        snapshot = verify_extractor.extract(path) if verify_extractor else None
        if snapshot and operation["command"] == "RESIZE_COMPONENT":
            handle = operation["handle"]
            props = snapshot.properties[handle]
            first = changes[0]
            actual = props["end"] if first.property == "EndPoint" else props["radius"]
            if first.is_point and math.dist(actual, first.after) > 1e-6 or not first.is_point and abs(actual - first.after) > 1e-6:
                raise ValueError("Saved-file re-extraction did not confirm the resize")
        return dict(path=path, changes=summary, verified_by_extraction=snapshot is not None)

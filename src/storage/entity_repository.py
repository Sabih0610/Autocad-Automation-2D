"""Atomic index replacement with stable drawing/handle IDs and indexed lookup."""
from dataclasses import asdict
import json
import math
from uuid import NAMESPACE_URL, uuid5

from .database import connection


def entity_id(drawing_id, handle):
    return uuid5(NAMESPACE_URL, f"{drawing_id}:{handle}").hex


def store_snapshot(conn, drawing_id, snapshot):
    handles = [e.handle for e in snapshot.entities]
    if len(set(handles)) != len(handles) or any(not h for h in handles):
        raise ValueError("Entity handles must be non-empty and unique within a drawing")
    ids = {h: entity_id(drawing_id, h) for h in handles}
    old_ids = {row[0] for row in conn.execute("SELECT entity_id FROM entities WHERE drawing_id=?", (drawing_id,))}
    # Preserve IDs referenced by history; remove stale property/geometry values atomically.
    for old_id in old_ids:
        conn.execute("DELETE FROM entity_properties WHERE entity_id=?", (old_id,))
        conn.execute("DELETE FROM entity_geometry WHERE entity_id=?", (old_id,))
        conn.execute("DELETE FROM relationships WHERE source_entity_id=? OR target_entity_id=?", (old_id, old_id))
        if old_id not in ids.values():
            conn.execute("UPDATE change_set_items SET entity_id=NULL WHERE entity_id=?", (old_id,))
            conn.execute("DELETE FROM entities WHERE entity_id=?", (old_id,))
    for entity in snapshot.entities:
        eid = ids[entity.handle]
        conn.execute("""INSERT INTO entities VALUES (?,?,?,?,?,?) ON CONFLICT(entity_id)
            DO UPDATE SET tag=excluded.tag,entity_type=excluded.entity_type,layer=excluded.layer""",
                     (eid, drawing_id, entity.handle, entity.tag, entity.entity_type, entity.layer))
        values = snapshot.properties.get(entity.handle, {})
        conn.executemany("INSERT INTO entity_properties VALUES (?,?,?)",
                         [(eid, key, json.dumps(value, allow_nan=False)) for key, value in values.items()])
    for box in snapshot.spatial_data:
        if box.handle not in ids:
            raise ValueError("Geometry references an unknown entity")
        bounds = tuple(value for pair in zip(box.minimum, box.maximum) for value in pair)
        if any(not math.isfinite(v) for v in bounds) or any(a > b for a, b in zip(box.minimum, box.maximum)):
            raise ValueError("Invalid bounding box")
        start, end = box.start or (None,) * 3, box.end or (None,) * 3
        conn.execute("INSERT INTO entity_geometry VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (ids[box.handle], *start, *end, *bounds))
    conn.execute("INSERT INTO drawing_metadata VALUES (?,?,?) ON CONFLICT(drawing_id) DO UPDATE SET units=excluded.units,payload=excluded.payload",
                 (drawing_id, snapshot.document.units, json.dumps(asdict(snapshot.document), allow_nan=False)))
    for relation in snapshot.relationships:
        conn.execute("""INSERT OR IGNORE INTO relationships
            (source_entity_id,relationship_type,target_entity_id) VALUES (?,?,?)""",
                     (ids[relation.source_handle], relation.relationship_type, ids[relation.target_handle]))
    for eid in ids.values():
        conn.execute("""INSERT OR IGNORE INTO relationships
            (source_entity_id,relationship_type,target_drawing_id)
            VALUES (?,'appears_in',?)""", (eid, drawing_id))
    # Same tag in another drawing is a representation, never spatial connectivity.
    for entity in snapshot.entities:
        if not entity.tag:
            continue
        others = conn.execute("""SELECT e.entity_id FROM entities e JOIN drawings d ON d.drawing_id=e.drawing_id
            WHERE e.tag=? COLLATE NOCASE AND e.drawing_id<>? AND d.scan_status='scanned'
            AND d.project_id=(SELECT project_id FROM drawings WHERE drawing_id=?)""",
                              (entity.tag, drawing_id, drawing_id)).fetchall()
        for other in others:
            for source, target in ((ids[entity.handle], other[0]), (other[0], ids[entity.handle])):
                conn.execute("""INSERT OR IGNORE INTO relationships
                    (source_entity_id,relationship_type,target_entity_id)
                    VALUES (?,'represented_in',?)""", (source, target))


TAG_QUERY = """SELECT e.*, d.path, d.project_id, d.file_hash, m.units,
    g.start_x,g.start_y,g.start_z,g.end_x,g.end_y,g.end_z,
    g.min_x,g.max_x,g.min_y,g.max_y,g.min_z,g.max_z
    FROM entities e JOIN drawings d ON d.drawing_id=e.drawing_id
    JOIN drawing_metadata m ON m.drawing_id=d.drawing_id
    LEFT JOIN entity_geometry g ON g.entity_id=e.entity_id
    WHERE e.tag=? COLLATE NOCASE AND d.project_id=? AND d.scan_status='scanned'
    ORDER BY d.path,e.handle"""


def find_by_tag(project_id, tag):
    with connection() as conn:
        return [dict(row) for row in conn.execute(TAG_QUERY, (tag, project_id))]


def get_entity(eid):
    with connection() as conn:
        row = conn.execute("""SELECT e.*,d.path,d.project_id,d.scan_status,m.units FROM entities e
            JOIN drawings d ON d.drawing_id=e.drawing_id
            JOIN drawing_metadata m ON m.drawing_id=d.drawing_id WHERE e.entity_id=?""", (eid,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown entity: {eid}")
        record = dict(row)
        record["properties"] = {r[0]: json.loads(r[1]) for r in conn.execute(
            "SELECT key,value FROM entity_properties WHERE entity_id=?", (eid,))}
        geometry = conn.execute("SELECT * FROM entity_geometry WHERE entity_id=?", (eid,)).fetchone()
        record["geometry"] = dict(geometry) if geometry else None
    return record

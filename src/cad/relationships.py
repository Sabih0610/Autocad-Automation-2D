"""Conservative endpoint/insertion-point heuristics, not CAD constraint semantics."""
from scipy.spatial import cKDTree
from src.cad.extractor.base import RelationshipRecord


def infer_connections(spatial_data, properties, tolerance=0.01):
    points, owners = [], []
    for box in spatial_data:
        for point in box.connection_points:
            points.append(point)
            owners.append(box.handle)
    if not points:
        return []
    pairs = set()
    for left, right in cKDTree(points).query_pairs(tolerance):
        a, b = owners[left], owners[right]
        if a != b and properties[a].get("layout") == properties[b].get("layout"):
            pairs.add((a, b))
            pairs.add((b, a))
    return [RelationshipRecord(a, "connected_to", b) for a, b in sorted(pairs)]


def related_entities(conn, eid, relationship_type="connected_to"):
    return [dict(row) for row in conn.execute("""SELECT e.*,r.relationship_type,d.path
        FROM relationships r JOIN entities e ON e.entity_id=r.target_entity_id
        JOIN drawings d ON d.drawing_id=e.drawing_id
        WHERE r.source_entity_id=? AND r.relationship_type=? AND d.scan_status='scanned'
        ORDER BY e.entity_id""", (eid, relationship_type))]


def related_drawings(conn, eid):
    return [dict(row) for row in conn.execute("""SELECT d.* FROM relationships r
        JOIN drawings d ON d.drawing_id=r.target_drawing_id
        WHERE r.source_entity_id=? AND r.relationship_type='appears_in'
        AND d.scan_status='scanned' ORDER BY d.drawing_id""", (eid,))]

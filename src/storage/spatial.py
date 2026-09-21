"""Persistent RTree with a versioned in-memory cKDTree fallback.

Queries use Euclidean distance between axis-aligned bounds, in one drawing.
This is a proximity index, not an exact solid-intersection/constraint solver.
"""
import math
import sqlite3
from scipy.spatial import cKDTree
from src.cad.units import from_mm
from src.logging import db


def rebuild_spatial_index(conn):
    """Fully repopulate `spatial_index` from the current `entities`/
    `entity_geometry` rows, discarding whatever it previously contained.

    `spatial_index.id` stores `entities.rowid`. `entities.entity_id` is a
    `TEXT PRIMARY KEY`, so `entities` has no explicit `INTEGER PRIMARY KEY`
    — per SQLite's own documentation, `VACUUM` may renumber the rowids of
    exactly this kind of table. Nothing in this codebase calls `VACUUM`
    today, but if anything ever does, every `id` value already stored in
    `spatial_index` would silently point at whatever entity now happens to
    have that rowid — wrong results, no error. Call this immediately after
    any `VACUUM` of this database (or if a mismatch is ever suspected for
    any other reason) to resync `spatial_index` to the current rowids.
    """
    has_rtree = conn.execute("SELECT 1 FROM sqlite_master WHERE name='spatial_index'").fetchone()
    if has_rtree:
        conn.execute("DELETE FROM spatial_index")
        conn.execute("""INSERT INTO spatial_index SELECT e.rowid,g.min_x,g.max_x,g.min_y,g.max_y,g.min_z,g.max_z
            FROM entities e JOIN entity_geometry g ON g.entity_id=e.entity_id""")
    # The cKDTree fallback is keyed by `spatial_version` and rebuilt lazily
    # from `entities`/`entity_geometry` directly (never from `spatial_index`
    # or a cached rowid), so it isn't affected by rowid renumbering at all —
    # bumping the version here only forces existing `SpatialIndex` instances
    # to drop their in-memory cache rather than because it's stale data.
    conn.execute("UPDATE spatial_version SET version=version+1 WHERE id=1")


def ensure_spatial(conn):
    existed = conn.execute("SELECT 1 FROM sqlite_master WHERE name='spatial_index'").fetchone()
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS spatial_index USING rtree(id,min_x,max_x,min_y,max_y,min_z,max_z)")
    except sqlite3.OperationalError as exc:
        if "no such module" not in str(exc).lower():
            raise
        return False
    # entity_geometry rows are always written via delete-then-insert, never
    # UPDATE (see entity_repository.store_snapshot), so an AFTER UPDATE
    # trigger here could never fire; it's intentionally not (re)created. A
    # database created before this was noticed may still have it on disk —
    # see database.py's connection(), which drops it unconditionally on
    # every call rather than only here, since ensure_spatial itself only
    # runs once per DB.
    conn.executescript("""
        CREATE TRIGGER IF NOT EXISTS spatial_insert AFTER INSERT ON entity_geometry BEGIN
            INSERT OR REPLACE INTO spatial_index SELECT e.rowid,new.min_x,new.max_x,new.min_y,new.max_y,new.min_z,new.max_z
            FROM entities e WHERE e.entity_id=new.entity_id;
        END;
        CREATE TRIGGER IF NOT EXISTS spatial_delete BEFORE DELETE ON entity_geometry BEGIN
            DELETE FROM spatial_index WHERE id=(SELECT rowid FROM entities WHERE entity_id=old.entity_id);
        END;
    """)
    if not existed:
        conn.execute("""INSERT INTO spatial_index SELECT e.rowid,g.min_x,g.max_x,g.min_y,g.max_y,g.min_z,g.max_z
            FROM entities e JOIN entity_geometry g ON g.entity_id=e.entity_id""")
    return True


def bounds(row):
    return ([row[f"min_{a}"] for a in "xyz"], [row[f"max_{a}"] for a in "xyz"])


def bounds_distance(a, b):
    amin, amax = bounds(a)
    bmin, bmax = bounds(b)
    return math.sqrt(sum(max(0, amin[i] - bmax[i], bmin[i] - amax[i]) ** 2 for i in range(3)))


RTREE_QUERY = """SELECT e.*,g.* FROM spatial_index s CROSS JOIN entities e ON e.rowid=s.id
    JOIN entity_geometry g ON g.entity_id=e.entity_id
    JOIN entity_properties p ON p.entity_id=e.entity_id AND p.key='layout'
    WHERE s.min_x<=? AND s.max_x>=? AND s.min_y<=? AND s.max_y>=? AND s.min_z<=? AND s.max_z>=?
    AND e.drawing_id=? AND e.entity_id<>? AND p.value=?"""


class SpatialIndex:
    def __init__(self, use_rtree=True):
        self.use_rtree = use_rtree
        self._key = None
        self._rows = []
        self._tree = None
        self._max_radius = 0

    def nearby(self, eid, radius_mm=100):
        from .database import connection
        if not math.isfinite(radius_mm) or radius_mm < 0:
            raise ValueError("Search radius must be finite and non-negative")
        with connection() as conn:
            target = conn.execute("""SELECT g.*,e.drawing_id,m.units,p.value AS layout FROM entity_geometry g
                JOIN entities e ON e.entity_id=g.entity_id JOIN drawings d ON d.drawing_id=e.drawing_id
                JOIN drawing_metadata m ON m.drawing_id=e.drawing_id
                LEFT JOIN entity_properties p ON p.entity_id=e.entity_id AND p.key='layout'
                WHERE e.entity_id=? AND d.scan_status='scanned'""", (eid,)).fetchone()
            if target is None:
                raise ValueError("No current indexed geometry for the selected entity")
            if target["layout"] is None:
                raise ValueError("Selected entity has no indexed 'layout' property; rescan the drawing")
            radius = from_mm(radius_mm, target["units"])
            low, high = bounds(target)
            has_rtree = conn.execute("SELECT 1 FROM sqlite_master WHERE name='spatial_index'").fetchone()
            if self.use_rtree and has_rtree:
                arguments = [value for i in range(3) for value in (high[i] + radius, low[i] - radius)]
                candidates = [dict(row) for row in conn.execute(RTREE_QUERY, (*arguments, target["drawing_id"], eid, target["layout"]))]
            else:
                version = conn.execute("SELECT version FROM spatial_version WHERE id=1").fetchone()[0]
                key = (str(db.DB_PATH), version, target["drawing_id"], target["layout"])
                if key != self._key:
                    self._rows = [dict(row) for row in conn.execute("""SELECT e.*,g.* FROM entities e
                        JOIN entity_geometry g ON e.entity_id=g.entity_id
                        JOIN entity_properties p ON p.entity_id=e.entity_id AND p.key='layout'
                        WHERE e.drawing_id=? AND p.value=?""", (target["drawing_id"], target["layout"]))]
                    boxes = [bounds(row) for row in self._rows]
                    centers = [[(a + b) / 2 for a, b in zip(lo, hi)] for lo, hi in boxes]
                    self._max_radius = max((math.dist(lo, hi) / 2 for lo, hi in boxes), default=0)
                    self._tree = cKDTree(centers) if centers else None
                    self._key = key
                center = [(a + b) / 2 for a, b in zip(low, high)]
                indices = self._tree.query_ball_point(center, radius + math.dist(low, high) / 2 + self._max_radius) if self._tree else []
                candidates = [self._rows[i] for i in indices if self._rows[i]["entity_id"] != eid]
            return sorted([dict(row, distance_mm=bounds_distance(target, row) / from_mm(1, target["units"]))
                           for row in candidates if bounds_distance(target, row) <= radius], key=lambda row: row["entity_id"])

import sqlite3
import ezdxf
import pytest
from src.cad.scanner import scan_project
from src.cad.relationships import related_entities
from src.storage.database import connection
from src.storage.entity_repository import find_by_tag
from src.storage.project_repository import register_project
from src.storage.spatial import SpatialIndex, ensure_spatial, RTREE_QUERY
from tests.project.test_extractor import make_dxf


@pytest.mark.parametrize("use_rtree", [True, False])
def test_nearby_100mm_and_rescan_invalidation(tmp_path, use_rtree):
    path = tmp_path / "a.dxf"
    make_dxf(path)
    doc = ezdxf.readfile(path)
    nearby = doc.modelspace().add_circle((500, 100, 0), 2)
    doc.modelspace().add_circle((500, 500, 0), 2)
    doc.saveas(path)
    project = register_project("Plant", str(tmp_path))
    scan_project(project, max_workers=1)
    pipe = find_by_tag(project, "P-101")[0]
    index = SpatialIndex(use_rtree=use_rtree)
    found = index.nearby(pipe["entity_id"], 100)
    assert nearby.dxf.handle in {row["handle"] for row in found}
    assert len(found) == 2  # valve and nearby circle; not paperspace text
    doc.modelspace().delete_entity(nearby)
    doc.saveas(path)
    scan_project(project, max_workers=1)
    assert len(index.nearby(pipe["entity_id"], 100)) == 1


def test_connections_and_cross_file_appearances_are_distinct(tmp_path):
    for name in ("a.dxf", "b.dxf"):
        make_dxf(tmp_path / name)
    project = register_project("Plant", str(tmp_path))
    scan_project(project, max_workers=1)
    pipe = find_by_tag(project, "P-101")[0]
    with connection() as conn:
        connected = related_entities(conn, pipe["entity_id"])
        appearances = related_entities(conn, pipe["entity_id"], "appears_in")
    assert len(connected) == 1 and connected[0]["tag"] == "V-101"
    assert len(appearances) == 1 and appearances[0]["tag"] == "P-101"
    assert all(row["drawing_id"] == pipe["drawing_id"] for row in SpatialIndex().nearby(pipe["entity_id"]))


def test_rtree_probe_falls_back_only_for_missing_extension():
    class NoRTree:
        def execute(self, sql):
            if sql.startswith("CREATE VIRTUAL"):
                raise sqlite3.OperationalError("no such module: rtree")
            return self
        def fetchone(self):
            return None
    assert ensure_spatial(NoRTree()) is False


def test_rtree_query_plan_uses_virtual_index(tmp_path):
    make_dxf(tmp_path / "a.dxf")
    project = register_project("Plant", str(tmp_path))
    scan_project(project, max_workers=1)
    pipe = find_by_tag(project, "P-101")[0]
    with connection() as conn:
        plan = conn.execute("EXPLAIN QUERY PLAN " + RTREE_QUERY, (1100,-100,100,-100,100,-100,pipe["drawing_id"],pipe["entity_id"], '"Model"')).fetchall()
        assert any("VIRTUAL TABLE INDEX" in row[3] for row in plan)

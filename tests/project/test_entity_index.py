import ezdxf
import pytest
from src.cad.scanner import scan_project, list_drawings
from src.cad.extractor import DXFExtractor
from src.storage.database import connection
from src.storage.entity_repository import find_by_tag, get_entity, TAG_QUERY, store_snapshot
from src.storage.project_repository import register_project
from tests.project.test_extractor import make_dxf


def test_tag_lookup_is_one_indexed_query_scoped_to_project(tmp_path, monkeypatch):
    ids = []
    for name in ("one", "two"):
        root = tmp_path / name
        root.mkdir()
        make_dxf(root / "a.dxf")
        ids.append(register_project(name, str(root))["project_id"])
        scan_project(ids[-1], max_workers=1)
    def forbidden(*args):
        pytest.fail("Lookup may not reopen drawings")
    monkeypatch.setattr(DXFExtractor, "extract", forbidden)
    result = find_by_tag(ids[0], "p-101")
    assert len(result) == 1 and result[0]["project_id"] == ids[0]
    assert result[0]["end_x"] == 1000
    record = get_entity(result[0]["entity_id"])
    assert record["properties"]["xdata"] and record["units"] == 4
    with connection() as conn:
        plan = list(conn.execute("EXPLAIN QUERY PLAN " + TAG_QUERY, ("P-101", ids[0])))
        assert any("idx_entity_tag_nocase" in row[3] for row in plan)


def test_rescan_keeps_ids_and_removes_deleted_entities(tmp_path):
    path = tmp_path / "a.dxf"
    handle = make_dxf(path)
    project = register_project("Plant", str(tmp_path))["project_id"]
    scan_project(project, max_workers=1)
    before = find_by_tag(project, "P-101")[0]
    doc = ezdxf.readfile(path)
    doc.entitydb[handle].dxf.end = (1050, 0, 0)
    doc.saveas(path)
    scan_project(project, max_workers=1)
    after = find_by_tag(project, "P-101")[0]
    assert after["entity_id"] == before["entity_id"]
    assert after["end_x"] == 1050
    doc.modelspace().delete_entity(doc.entitydb[handle])
    doc.saveas(path)
    scan_project(project, max_workers=1)
    assert find_by_tag(project, "P-101") == []


def test_bad_snapshot_rolls_back_and_scan_errors_hide_stale_index(tmp_path):
    path = tmp_path / "a.dxf"
    make_dxf(path)
    project = register_project("Plant", str(tmp_path))["project_id"]
    scan_project(project, max_workers=1)
    drawing = list_drawings(project)[0]
    snapshot = DXFExtractor().extract(path)
    snapshot.spatial_data[0].minimum = (float("nan"), 0, 0)
    with pytest.raises(ValueError, match="bounding"):
        with connection() as conn:
            store_snapshot(conn, drawing["drawing_id"], snapshot)
    assert len(find_by_tag(project, "P-101")) == 1
    path.write_text("corrupted")
    scan_project(project, max_workers=1)
    assert find_by_tag(project, "P-101") == []

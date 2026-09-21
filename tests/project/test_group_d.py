from __future__ import annotations

from pathlib import Path

import ezdxf
import pytest
from fastapi.testclient import TestClient

from src.api import main as main_module
from src.api.routes import projects as project_routes
from src.cad.extractor import DXFExtractor
from src.cad.extractor.oda import require_oda_converter
from src.cad.scanner import list_drawings, scan_project
from src.logging.jobs import list_recent_jobs
from src.storage.database import connection
from src.storage.entity_repository import (
    build_entity_list_query,
    find_by_tag,
    get_drawing_metadata,
    get_project_entity,
    list_entities,
)
from src.storage.project_repository import register_project


def _project_with_query_surface(tmp_path):
    path = tmp_path / "query.dxf"
    doc = ezdxf.new("R2010")
    doc.units = 4
    doc.appids.new("AUTOCAD_AI")
    doc.layers.add("PIPES", color=3)
    block = doc.blocks.new("PUMP_BLOCK")
    block.add_circle((0, 0), 5)
    ref = doc.modelspace().add_blockref(
        "PUMP_BLOCK",
        (100, 100),
        dxfattribs={"layer": "PIPES"},
    )
    ref.add_attrib("TAG", "P-101", (100, 100))
    doc.modelspace().add_line(
        (0, 0),
        (50, 0),
        dxfattribs={"layer": "PIPES"},
    )
    doc.saveas(path)
    project_id = register_project("Query", str(tmp_path))
    assert scan_project(project_id, max_workers=1)["errors"] == []
    drawing_id = list_drawings(project_id)[0]["drawing_id"]
    return project_id, drawing_id


def test_d1_query_surface_filters_details_and_metadata(tmp_path, monkeypatch):
    project_id, drawing_id = _project_with_query_surface(tmp_path)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Index query must not reopen a drawing")

    monkeypatch.setattr(DXFExtractor, "extract", forbidden)
    rows = list_entities(project_id, drawing_id=drawing_id)
    assert rows
    block_rows = list_entities(project_id, block="pump_block")
    assert len(block_rows) == 1
    assert block_rows[0]["block_name"] == "PUMP_BLOCK"
    assert list_entities(project_id, entity_type="block_ref")[0]["entity_id"] == block_rows[0]["entity_id"]
    assert list_entities(project_id, layer="pipes")
    search = list_entities(project_id, q="pump 101")
    assert search[0]["entity_id"] == block_rows[0]["entity_id"]
    detail = get_project_entity(project_id, block_rows[0]["entity_id"])
    assert detail["properties"]["name"] == "PUMP_BLOCK"
    assert detail["block"]["name"] == "PUMP_BLOCK"
    metadata = get_drawing_metadata(project_id, drawing_id)
    assert metadata["units"] == 4
    assert metadata["properties"]["_layers"]["PIPES"]["color"] == 3


def test_d1_added_query_shapes_use_indexes(tmp_path):
    project_id, drawing_id = _project_with_query_surface(tmp_path)
    cases = [
        ({"drawing_id": drawing_id}, "idx_entity_drawing"),
        (
            {"drawing_id": drawing_id, "entity_type": "BLOCK_REF"},
            "idx_entities_drawing_type",
        ),
        (
            {"drawing_id": drawing_id, "layer": "PIPES"},
            "idx_entities_drawing_layer",
        ),
        (
            {"drawing_id": drawing_id, "block": "PUMP_BLOCK"},
            "idx_entity_block_name",
        ),
    ]
    with connection() as conn:
        for kwargs, expected in cases:
            sql, params = build_entity_list_query(project_id, **kwargs)
            plan = list(conn.execute("EXPLAIN QUERY PLAN " + sql, params))
            text = "\n".join(row[3] for row in plan)
            assert expected in text, text
        sql, params = build_entity_list_query(project_id, q="pump 101")
        plan = list(conn.execute("EXPLAIN QUERY PLAN " + sql, params))
        assert any("VIRTUAL TABLE INDEX" in row[3] for row in plan)


def _save_proximity_scene(path, *, ambiguous=False, explicit=False, far=False):
    doc = ezdxf.new("R2010")
    doc.units = 4
    doc.appids.new("AUTOCAD_AI")
    msp = doc.modelspace()
    if ambiguous:
        left = msp.add_circle((-20, 0), 5)
        msp.add_circle((20, 0), 5)
        target = left
    else:
        target = msp.add_circle((0, 0), 5)
    if explicit:
        target.set_xdata("AUTOCAD_AI", [(1000, "TAG=EX-101")])
    label_x = 1000 if far else 12
    msp.add_text(
        "P-501",
        dxfattribs={"insert": (label_x, 0), "height": 2.5},
    )
    doc.saveas(path)
    return target.dxf.handle


def test_d2_unique_nearby_text_tag_is_associated_with_provenance(tmp_path):
    path = tmp_path / "near.dxf"
    handle = _save_proximity_scene(path)
    snapshot = DXFExtractor().extract(path)
    entity = next(item for item in snapshot.entities if item.handle == handle)
    assert entity.tag == "P-501"
    assert entity.tag_source == "proximity"
    project_id = register_project("Near", str(tmp_path))
    scan_project(project_id, max_workers=1)
    indexed = find_by_tag(project_id, "P-501")
    assert len(indexed) == 1
    assert indexed[0]["tag_source"] == "proximity"


def test_d2_explicit_tag_wins_and_ambiguous_nearby_label_is_refused(tmp_path):
    explicit_path = tmp_path / "explicit.dxf"
    explicit_handle = _save_proximity_scene(explicit_path, explicit=True)
    explicit_snapshot = DXFExtractor().extract(explicit_path)
    explicit_entity = next(
        item for item in explicit_snapshot.entities
        if item.handle == explicit_handle
    )
    assert explicit_entity.tag == "EX-101"
    assert explicit_entity.tag_source == "explicit"
    ambiguous_path = tmp_path / "ambiguous.dxf"
    _save_proximity_scene(ambiguous_path, ambiguous=True)
    ambiguous_snapshot = DXFExtractor(
        proximity_tag_ambiguity_mm=50,
    ).extract(ambiguous_path)
    circles = [
        item for item in ambiguous_snapshot.entities
        if item.entity_type == "CIRCLE"
    ]
    assert all(item.tag is None for item in circles)
    assert any(
        "ambiguous" in warning.lower()
        for warning in ambiguous_snapshot.document.warnings
    )


def test_d2_distance_threshold_is_configurable(tmp_path):
    path = tmp_path / "far.dxf"
    handle = _save_proximity_scene(path, far=True)
    snapshot = DXFExtractor(proximity_tag_distance_mm=100).extract(path)
    entity = next(item for item in snapshot.entities if item.handle == handle)
    assert entity.tag is None
    assert entity.tag_source == "none"


def test_d3_missing_oda_configuration_names_variable_and_install_source(monkeypatch):
    monkeypatch.delenv("ODA_FILE_CONVERTER", raising=False)
    with pytest.raises(RuntimeError) as excinfo:
        require_oda_converter()
    message = str(excinfo.value)
    assert "ODA_FILE_CONVERTER" in message
    assert "ODA File Converter" in message
    assert "opendesign.com" in message


def test_d3_env_example_documents_every_runtime_environment_variable():
    text = Path(".env.example").read_text(encoding="utf-8")
    expected = {
        "AI_PROVIDER",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL",
        "ODA_FILE_CONVERTER",
        "AUTOCAD_AI_DB_PATH",
        "AUTOCAD_AI_TAG_PROXIMITY_MM",
        "AUTOCAD_AI_TAG_AMBIGUITY_MM",
        "USERNAME",
        "USER",
    }
    keys = {
        line.split("=", 1)[0]
        for line in text.splitlines()
        if line and not line.startswith("#") and "=" in line
    }
    assert expected <= keys
    for line in text.splitlines():
        if line and not line.startswith("#") and "=" in line:
            assert "PLACEHOLDER" in line.split("=", 1)[1]


def test_d4_audit_route_map_is_method_aware():
    assert main_module.AUDIT_ROUTE_MAP[("GET", "/api/projects")] == "project_list"
    assert main_module.AUDIT_ROUTE_MAP[("POST", "/api/projects")] == "project_register"
    assert main_module.AUDIT_ROUTE_MAP[("GET", "/api/autocad/inspect")] == "autocad_inspect"
    assert "/api/projects" not in main_module.AUDIT_ROUTE_MAP


def test_d4_get_projects_audits_list_not_register(monkeypatch):
    monkeypatch.setattr(project_routes, "list_projects", lambda: [])
    response = TestClient(main_module.app).get("/api/projects")
    assert response.status_code == 200
    jobs = list_recent_jobs()
    assert len(jobs) == 1
    assert jobs[0]["use_case"] == "project_list"

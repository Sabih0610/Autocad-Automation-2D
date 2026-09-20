import math
import ezdxf
import pytest
from jsonschema import ValidationError
from src.cad.extractor import DXFExtractor
from src.cad.geometry import resize_endpoint
from src.cad.scanner import scan_project
from src.storage.project_repository import register_project
from src.storage.entity_repository import find_by_tag
from src.framework.commands.schema import validate_command_sequence
from src.framework.commands.operation_schema import validate_operation
from src.framework.commands import modification_executor as engine
from tests.project.fake_cad import Acad, Document
from tests.project.test_extractor import make_dxf


@pytest.fixture
def drawing(tmp_path, monkeypatch):
    path = tmp_path / "a.dxf"
    handle = make_dxf(path)
    project = register_project("Plant", str(tmp_path))
    scan_project(project, max_workers=1)
    monkeypatch.setattr(engine, "point", tuple)
    return path, handle, project


def resize(path, handle, **values):
    return dict(command="RESIZE_COMPONENT", target_dwg_path=str(path), handle=handle,
                dimension="length", **values)


def test_resize_preserves_handles_targets_file_and_reextracts(drawing, tmp_path):
    path, handle, project = drawing
    other_path = tmp_path / "other.dxf"
    make_dxf(other_path)
    other_before = other_path.read_bytes()
    acad = Acad([Document(other_path)])
    before = DXFExtractor().extract(path)
    result = engine.execute_operation(resize(path, handle, delta_mm=50), acad=acad, verify_extractor=DXFExtractor())
    after = DXFExtractor().extract(path)
    assert result["verified_by_extraction"] is True
    assert after.properties[handle]["end"] == [1050, 0, 0]
    assert {e.handle for e in after.entities} == {e.handle for e in before.entities}
    valve = next(e for e in after.entities if e.tag == "V-101")
    assert after.properties[valve.handle]["insert"] == [1050, 0, 0]
    assert other_path.read_bytes() == other_before
    assert acad.Documents.opened == [str(path)]
    assert handle in acad.Documents.documents[-1].lookups


def test_geometry_uses_direction_units_and_rejects_invalid_lengths():
    assert resize_endpoint((0, 0, 0), (3, 4, 0), delta=5) == (6, 8, 0)
    for start, end, delta in [((0,0,0),(0,0,0),1), ((0,0,0),(1,0,0),-2), ((0,0,0),(math.nan,0,0),1)]:
        with pytest.raises(ValueError):
            resize_endpoint(start, end, delta=delta)


@pytest.mark.parametrize("operation", [
    {"command": "RESIZE_COMPONENT", "handle": "AA", "dimension": "length", "delta_mm": 1, "value_mm": 2},
    {"command": "SET_ENTITY_PROPERTY", "handle": "AA", "property": "Delete", "value": 1},
    {"command": "SET_LAYER_COLOR", "layer": "0", "color": 999},
    {"command": "RENAME_FILE", "new_name": "../evil.dwg"},
])
def test_operation_schema_rejects_unsafe_or_ambiguous_fields(operation):
    with pytest.raises(ValidationError):
        validate_operation(dict(operation, target_dwg_path="C:/a.dwg"))


def test_command_schema_accepts_structured_operation_and_requires_target(drawing):
    path, handle, _ = drawing
    op = resize(path, handle, delta_mm=50)
    envelope = dict(schema_version="1.0", summary="Resize", assumptions=[], commands=[op])
    assert validate_command_sequence(envelope) == []
    del op["target_dwg_path"]
    assert validate_command_sequence(envelope)


def test_negative_resize_unsaved_and_stale_drawing_are_rejected(drawing):
    path, handle, _ = drawing
    original = path.read_bytes()
    doc = Document(path)
    acad = Acad([doc])
    with pytest.raises(ValueError, match="positive"):
        engine.execute_operation(resize(path, handle, delta_mm=-2000), acad=acad)
    doc.Saved = False
    with pytest.raises(ValueError, match="unsaved"):
        engine.execute_operation(resize(path, handle, delta_mm=50), acad=acad)
    doc.Saved = True
    path.write_bytes(original + b"\n")
    with pytest.raises(ValueError, match="changed since"):
        engine.execute_operation(resize(path, handle, delta_mm=50), acad=acad)
    assert doc.save_calls == 0


def test_property_layer_document_and_attribute_edits(drawing):
    path, handle, project = drawing
    acad = Acad()
    def apply(**fields):
        result = engine.execute_operation(dict(fields, target_dwg_path=str(path)), acad=acad)
        scan_project(project, max_workers=1)
        return result
    apply(command="SET_ENTITY_PROPERTY", handle=handle, property="color", value=3)
    assert DXFExtractor().extract_properties(path)[handle]["color"] == 3
    apply(command="SET_LAYER_COLOR", layer="0", color=2)
    assert ezdxf.readfile(path).layers.get("0").dxf.color == 2
    apply(command="SET_DOCUMENT_PROPERTY", property="title", value="Plant")
    assert acad.Documents.documents[0].SummaryInfo.Title == "Plant"
    valve = find_by_tag(project, "V-101")[0]
    apply(command="SET_ENTITY_PROPERTY", handle=valve["handle"], property="attribute", attribute_tag="TAG", value="V-102")
    assert len(find_by_tag(project, "V-102")) == 1


def test_rename_is_filesystem_only_and_rejects_open_file(drawing, monkeypatch):
    path, handle, project = drawing
    def forbidden(*args):
        pytest.fail("Rename may not contact AutoCAD")
    monkeypatch.setattr(engine, "cad_session", forbidden)
    op = dict(command="RENAME_FILE", target_dwg_path=str(path), new_name="renamed.dxf")
    from src.cad.session import mark_open
    mark_open(str(path), True)
    with pytest.raises(ValueError, match="Close"):
        engine.execute_operation(op)
    mark_open(str(path), False)
    original = path.read_bytes()
    result = engine.execute_operation(op)
    assert not path.exists()
    assert (path.parent / "renamed.dxf").read_bytes() == original
    assert result["changes"][0]["field"] == "path"


def test_inspector_resolves_explicit_document(drawing, monkeypatch):
    from src.framework.autocad import inspector
    path, _, _ = drawing
    acad = Acad()
    monkeypatch.setattr(inspector, "_get_acad", lambda: acad)
    result = inspector.inspect_active_drawing(target_dwg_path=str(path))
    assert result["dwg_path"] == str(path)
    assert acad.Documents.opened == [str(path)]


def test_new_overlap_is_rejected_before_mutation(drawing):
    path, handle, project = drawing
    doc = ezdxf.readfile(path)
    doc.modelspace().add_circle((1100, 0), 10)
    doc.saveas(path)
    scan_project(project, max_workers=1)
    original = path.read_bytes()
    with pytest.raises(ValueError, match="overlap"):
        engine.execute_operation(resize(path, handle, delta_mm=120), acad=Acad())
    assert path.read_bytes() == original


def test_radius_resize_converts_mm_to_inches(drawing):
    path, _, project = drawing
    doc = ezdxf.readfile(path)
    doc.units = 1
    circle = doc.modelspace().add_circle((500, 500), 1)
    doc.saveas(path)
    scan_project(project, max_workers=1)
    engine.execute_operation(dict(command="RESIZE_COMPONENT", target_dwg_path=str(path),
        handle=circle.dxf.handle, dimension="radius", delta_mm=25.4), acad=Acad(), verify_extractor=DXFExtractor())
    assert DXFExtractor().extract_properties(path)[circle.dxf.handle]["radius"] == pytest.approx(2)


def test_failed_save_rolls_back_live_assignments(drawing, monkeypatch):
    path, handle, _ = drawing
    doc = Document(path)
    original = path.read_bytes()
    def fail():
        raise RuntimeError("save failed")
    monkeypatch.setattr(doc, "Save", fail)
    with pytest.raises(RuntimeError, match="save failed"):
        engine.execute_operation(resize(path, handle, delta_mm=50), acad=Acad([doc]))
    assert tuple(doc.data.entitydb[handle].dxf.end) == (1000, 0, 0)
    assert path.read_bytes() == original


def test_missing_target_and_nonfinite_values_rejected_before_com(drawing):
    path, handle, _ = drawing
    with pytest.raises(ValueError, match="absolute"):
        engine.execute_operation(resize("relative.dwg", handle, delta_mm=1), acad=Acad())
    with pytest.raises(ValueError):
        engine.execute_operation(resize(path, handle, delta_mm=float("inf")), acad=Acad())

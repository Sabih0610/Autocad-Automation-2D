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
from tests.project import fake_cad
from tests.project.fake_cad import Acad, Document
from tests.project.test_extractor import make_dxf


@pytest.fixture
def drawing(tmp_path, monkeypatch):
    path = tmp_path / "a.dxf"
    handle = make_dxf(path)
    project = register_project("Plant", str(tmp_path))
    scan_project(project, max_workers=1)
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


def test_legacy_command_schema_rejects_structured_operations(drawing):
    """The legacy creation/edit command schema must stay independent of the new
    structured-operation schema. RESIZE_COMPONENT and friends are validated only
    through `validate_operation`/`OPERATION_SCHEMA`, dispatched via
    `modification_executor`; they must never be accepted inside a Mode 2
    `commands` envelope (validated via `validate_command_sequence`), since the
    legacy executor has no handler for them. This previously regressed because
    `schema.py` mutated the shared `COMMAND_SCHEMA`/`_COMMAND_TYPES` objects at
    import time to splice the operation types in — see schema.py's module
    docstring/comment for the fix.
    """
    path, handle, _ = drawing
    op = resize(path, handle, delta_mm=50)
    envelope = dict(schema_version="1.0", summary="Resize", assumptions=[], commands=[op])
    assert validate_command_sequence(envelope) != []

    # The operation itself must still validate correctly through the proper,
    # separate structured-operation path, with or without an explicit target.
    assert validate_operation(op) == op
    del op["target_dwg_path"]
    with pytest.raises(ValidationError):
        validate_operation(op)


@pytest.mark.parametrize("operation", [
    {"command": "RESIZE_COMPONENT", "handle": "AA", "dimension": "length", "delta_mm": 50},
    {"command": "SET_ENTITY_PROPERTY", "handle": "AA", "property": "color", "value": 3},
    {"command": "SET_DOCUMENT_PROPERTY", "property": "author", "value": "Engineer"},
    {"command": "SET_LAYER_COLOR", "layer": "0", "color": 2},
    {"command": "RENAME_FILE", "new_name": "renamed.dwg"},
])
def test_every_structured_command_requires_an_explicit_target(operation):
    with pytest.raises(ValidationError):
        validate_operation(operation)


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
    data = ezdxf.readfile(path)
    data.layers.new("PIPES")
    data.saveas(path)
    scan_project(project, max_workers=1)
    acad = Acad()
    def apply(**fields):
        result = engine.execute_operation(dict(fields, target_dwg_path=str(path)), acad=acad)
        scan_project(project, max_workers=1)
        return result
    apply(command="SET_ENTITY_PROPERTY", handle=handle, property="color", value=3)
    assert DXFExtractor().extract_properties(path)[handle]["color"] == 3
    apply(command="SET_ENTITY_PROPERTY", handle=handle, property="layer", value="PIPES")
    assert DXFExtractor().extract_properties(path)[handle]["layer"] == "PIPES"
    apply(command="SET_ENTITY_PROPERTY", handle=handle, property="linetype", value="CONTINUOUS")
    assert DXFExtractor().extract_properties(path)[handle]["linetype"] == "CONTINUOUS"
    text_handle = next(e.handle for e in DXFExtractor().extract_entities(path) if e.entity_type == "TEXT")
    apply(command="SET_ENTITY_PROPERTY", handle=text_handle, property="text", value="Revised Header")
    assert DXFExtractor().extract_properties(path)[text_handle]["text"] == "Revised Header"
    apply(command="SET_LAYER_COLOR", layer="0", color=2)
    assert ezdxf.readfile(path).layers.get("0").dxf.color == 2
    apply(command="SET_DOCUMENT_PROPERTY", property="title", value="Plant")
    assert acad.Documents.documents[0].SummaryInfo.Title == "Plant"
    apply(command="SET_DOCUMENT_PROPERTY", property="author", value="Engineer")
    assert acad.Documents.documents[0].SummaryInfo.Author == "Engineer"
    valve = find_by_tag(project, "V-101")[0]
    apply(command="SET_ENTITY_PROPERTY", handle=valve["handle"], property="attribute", attribute_tag="TAG", value="V-102")
    assert len(find_by_tag(project, "V-102")) == 1


def test_rename_is_filesystem_only_and_rejects_genuinely_open_file(drawing, monkeypatch):
    path, handle, project = drawing
    def forbidden(*args):
        pytest.fail("Rename may not contact AutoCAD")
    monkeypatch.setattr(engine, "cad_session", forbidden)
    op = dict(command="RENAME_FILE", target_dwg_path=str(path), new_name="renamed.dxf")
    from src.cad.session import mark_open
    mark_open(str(path), True)
    # A real `.dwl` lock file is what makes this "genuinely open" rather than
    # just our own bookkeeping flag — see
    # test_rename_reconciles_stale_open_flag_when_no_lock_file_exists for the
    # case where the flag is stale (no lock file at all) and must not block.
    path.with_suffix(".dwl").write_bytes(b"")
    with pytest.raises(ValueError, match="Close"):
        engine.execute_operation(op)
    path.with_suffix(".dwl").unlink()
    mark_open(str(path), False)
    original = path.read_bytes()
    result = engine.execute_operation(op)
    assert not path.exists()
    assert (path.parent / "renamed.dxf").read_bytes() == original
    assert result["changes"][0]["field"] == "path"


def test_rename_reconciles_stale_open_flag_when_no_lock_file_exists(drawing):
    """`is_open` only ever gets cleared by a changeset revert (or manually,
    as the sibling test does) — a normal successful edit leaves the drawing
    open in AutoCAD by design, and an external close (the user closing it
    directly in AutoCAD) has no way to notify this app at all. Without
    reconciliation, `is_open` could get stuck at 1 forever, permanently
    blocking every future rename. This proves it self-heals using AutoCAD's
    own `.dwl`/`.dwl2` lock files as the more reliable signal, without
    anyone having to call `mark_open(path, False)` manually."""
    path, handle, _ = drawing
    from src.cad.session import mark_open
    mark_open(str(path), True)
    assert not path.with_suffix(".dwl").exists()
    assert not path.with_suffix(".dwl2").exists()

    op = dict(command="RENAME_FILE", target_dwg_path=str(path), new_name="renamed.dxf")
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


def test_transient_com_busy_error_is_retried_not_fatal(drawing, monkeypatch):
    """The legacy executor (executor.py) already retries transient "AutoCAD
    busy" COM errors; this module previously had none at all, so a purely
    transient failure (one that would have succeeded on the very next
    attempt) aborted the whole operation and triggered a full rollback
    instead of just trying again."""
    path, handle, _ = drawing
    doc = Document(path)

    real_setattr = fake_cad.Entity.__setattr__
    state = {"end_point_attempts": 0}

    def flaky_setattr(self, name, value):
        if name == "EndPoint":
            state["end_point_attempts"] += 1
            if state["end_point_attempts"] == 1:
                raise AttributeError("simulated transient AutoCAD-busy error")
        real_setattr(self, name, value)

    monkeypatch.setattr(fake_cad.Entity, "__setattr__", flaky_setattr)

    result = engine.execute_operation(resize(path, handle, delta_mm=50), acad=Acad([doc]))
    assert state["end_point_attempts"] == 2
    assert result["changes"][0]["after"] == (1050, 0, 0)


def test_missing_target_and_nonfinite_values_rejected_before_com(drawing):
    path, handle, _ = drawing
    with pytest.raises(ValueError, match="absolute"):
        engine.execute_operation(resize("relative.dwg", handle, delta_mm=1), acad=Acad())


def test_set_entity_property_save_lie_is_caught_by_reextraction(drawing):
    """Previously, only RESIZE_COMPONENT re-verified the saved file against
    what was intended — every other operation only checked that extraction
    *succeeded*, not that the value actually persisted. Simulate a COM
    `Save()` that reports success without writing anything (a real failure
    mode this project's own docs already flag as possible) and confirm a
    color edit is now caught the same way a bad resize already was."""
    path, handle, _ = drawing
    doc = Document(path)
    original_save = doc.Save
    doc.Save = lambda: None  # "succeeds" without calling self.data.saveas(...)
    try:
        with pytest.raises(ValueError, match="did not confirm the property change"):
            engine.execute_operation(
                dict(command="SET_ENTITY_PROPERTY", target_dwg_path=str(path), handle=handle,
                     property="color", value=3),
                acad=Acad([doc]), verify_extractor=DXFExtractor(),
            )
    finally:
        doc.Save = original_save


def test_set_entity_property_verified_when_save_genuinely_persists(drawing):
    path, handle, _ = drawing
    result = engine.execute_operation(
        dict(command="SET_ENTITY_PROPERTY", target_dwg_path=str(path), handle=handle,
             property="color", value=3),
        acad=Acad([Document(path)]), verify_extractor=DXFExtractor(),
    )
    assert result["verified_by_extraction"] is True
    assert DXFExtractor().extract_properties(path)[handle]["color"] == 3


def test_layer_property_verification_tolerates_autocad_case_normalization(drawing, monkeypatch):
    """AutoCAD layer/linetype names are case-insensitive but case-preserving.
    If AutoCAD echoes back an existing layer's own stored casing rather than
    the exact casing an assignment happened to send, that must not be
    mistaken for AutoCAD having silently dropped the edit."""
    path, handle, project = drawing
    data = ezdxf.readfile(path)
    data.layers.new("Pipes")
    data.saveas(path)
    scan_project(project, max_workers=1)
    doc = Document(path)

    real_getattr = fake_cad.Entity.__getattr__

    def case_flipping_getattr(self, name):
        if name == "Layer":
            return "Pipes"  # different case than the "PIPES" this test assigns
        return real_getattr(self, name)

    monkeypatch.setattr(fake_cad.Entity, "__getattr__", case_flipping_getattr)

    result = engine.execute_operation(
        dict(command="SET_ENTITY_PROPERTY", target_dwg_path=str(path), handle=handle,
             property="layer", value="PIPES"),
        acad=Acad([doc]),
    )
    assert result["changes"][0]["after"] == "PIPES"


def test_radius_resize_tolerates_com_normal_floating_point_noise(drawing, monkeypatch):
    """A legitimate XY-plane circle/arc must not be spuriously rejected
    because COM returned a Normal vector like (0.0, 0.0, 0.9999999999999998)
    instead of exactly (0.0, 0.0, 1.0) — a real, observed floating-point
    representation, not a hypothetical one."""
    path, _, project = drawing
    doc = ezdxf.readfile(path)
    circle = doc.modelspace().add_circle((500, 500), 10)
    doc.saveas(path)
    scan_project(project, max_workers=1)

    real_getattr = fake_cad.Entity.__getattr__

    def noisy_normal_getattr(self, name):
        if name == "Normal":
            return (0.0, 0.0, 0.9999999999999998)
        return real_getattr(self, name)

    monkeypatch.setattr(fake_cad.Entity, "__getattr__", noisy_normal_getattr)

    result = engine.execute_operation(
        dict(command="RESIZE_COMPONENT", target_dwg_path=str(path), handle=circle.dxf.handle,
             dimension="radius", delta_mm=5),
        acad=Acad([Document(path)]),
    )
    assert result["changes"][0]["after"] == 15


def test_rollback_failure_does_not_mask_original_error_or_abort_remaining_rollback(drawing, monkeypatch):
    """If a second, unrelated COM failure happens while rolling back a
    multi-assignment edit (e.g. rolling back a connected valve's position
    after the pipe's own resize+save failed), the rollback must still
    attempt every other change, and the caller must still learn about BOTH
    the original failure and the rollback failure — not have the rollback
    failure silently swallow or replace the original one, and not abort
    partway through rolling back the rest, leaving other changes live in
    the unsaved document."""
    path, handle, _ = drawing
    doc = Document(path)

    state = {"save_failed": False, "rollback_already_failed_once": False}

    def fail_save():
        state["save_failed"] = True
        raise RuntimeError("save failed")
    monkeypatch.setattr(doc, "Save", fail_save)

    real_setattr = fake_cad.Entity.__setattr__

    def flaky_setattr(self, name, value):
        # Fail exactly once, and only on an InsertionPoint assignment made
        # AFTER Save() has already failed — i.e. during rollback, regardless
        # of how many InsertionPoint assignments (valve + its attribute, if
        # any) happen during the forward pass first.
        if name == "InsertionPoint" and state["save_failed"] and not state["rollback_already_failed_once"]:
            state["rollback_already_failed_once"] = True
            raise RuntimeError("rollback also failed")
        real_setattr(self, name, value)

    monkeypatch.setattr(fake_cad.Entity, "__setattr__", flaky_setattr)

    with pytest.raises(RuntimeError) as excinfo:
        engine.execute_operation(resize(path, handle, delta_mm=50), acad=Acad([doc]))

    message = str(excinfo.value)
    assert "save failed" in message
    assert "rollback also failed" in message
    assert excinfo.value.__cause__ is not None
    assert "save failed" in str(excinfo.value.__cause__)
    # The pipe's own EndPoint rollback (reversed(applied) processes it AFTER
    # the valve's InsertionPoint) must still have run despite the valve
    # rollback failing first — proving one rollback failure doesn't abort
    # the rest.
    assert tuple(doc.data.entitydb[handle].dxf.end) == (1000, 0, 0)
    with pytest.raises(ValueError):
        engine.execute_operation(resize(path, handle, delta_mm=float("inf")), acad=Acad())

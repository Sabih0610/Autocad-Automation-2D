"""`execute_edit_plan` must keep deletions and additions in one document.

Every test in tests/framework/test_edit_executor.py monkeypatches the
delegation away, which is exactly why this bug survived: the additions were
delegated with `target_dwg_path=None`, so they resolved `ActiveDocument`
independently of the document the edit plan had already opened. With a
different drawing focused, deletions landed in the target and new geometry
landed elsewhere, while only the target was saved.

These tests exercise the real delegation. `fake_cad.Acad.ActiveDocument`
raises, so any code path that falls back to it fails loudly here rather than
silently writing to the wrong file.
"""
import ezdxf
import pytest

from src.framework.commands import edit_executor
from src.framework.commands.edit_executor import execute_edit_plan
from tests.project.fake_cad import Acad, Document


def _drawing(path, *, with_line=True):
    doc = ezdxf.new()
    doc.units = 4
    handle = None
    if with_line:
        line = doc.modelspace().add_line((0, 0, 0), (10, 0, 0))
        handle = line.dxf.handle
    doc.saveas(path)
    return handle


@pytest.fixture
def two_drawings(tmp_path):
    target_path = tmp_path / "target.dxf"
    other_path = tmp_path / "other.dxf"
    handle = _drawing(target_path)
    _drawing(other_path, with_line=False)
    return target_path, other_path, handle


def test_additions_and_deletions_both_land_in_the_target_document(two_drawings, monkeypatch):
    target_path, other_path, handle = two_drawings

    target_doc = Document(target_path)
    other_doc = Document(other_path)
    # `other_doc` is listed first so a naive "first open document" resolution
    # would pick the wrong one, and Acad.ActiveDocument raises outright.
    acad = Acad([other_doc, target_doc])
    monkeypatch.setattr(edit_executor, "_get_acad", lambda: acad)

    plan = {
        "schema_version": "1.0",
        "edit_intent": "Replace the line with a circle.",
        "summary": "Replace the line with a circle.",
        "assumptions": [],
        "delete_handles": [handle],
        "commands": [{"command": "CIRCLE", "center": [5, 5], "radius": 3}],
    }

    result = execute_edit_plan(
        plan,
        target_dwg_path=str(target_path),
        save=False,
        zoom_extents=False,
    )

    assert result["errors"] == []
    assert result["ok"] is True

    opened = acad.Documents.documents[-1]
    types = sorted(entity.dxftype() for entity in opened.data.modelspace())
    assert types == ["CIRCLE"], "the addition did not land in the target document"

    # The untouched drawing must remain empty — this is the assertion that
    # fails if additions leak into a separately-resolved document.
    assert len(list(other_doc.data.modelspace())) == 0


def test_reported_counts_describe_the_document_actually_written(two_drawings, monkeypatch):
    """`entity_count_after` is read from the target's modelspace, so when the
    additions went elsewhere the returned counts described neither file."""
    target_path, other_path, handle = two_drawings

    acad = Acad([Document(other_path), Document(target_path)])
    monkeypatch.setattr(edit_executor, "_get_acad", lambda: acad)

    plan = {
        "schema_version": "1.0",
        "edit_intent": "Add two circles.",
        "summary": "Add two circles.",
        "assumptions": [],
        "delete_handles": [],
        "commands": [
            {"command": "CIRCLE", "center": [0, 0], "radius": 1},
            {"command": "CIRCLE", "center": [5, 5], "radius": 2},
        ],
    }

    result = execute_edit_plan(
        plan,
        target_dwg_path=str(target_path),
        save=False,
        zoom_extents=False,
    )

    opened = acad.Documents.documents[-1]
    actual = len(list(opened.data.modelspace()))

    assert result["errors"] == []
    assert result["added_executed_count"] == 2
    assert result["entity_count_after"] == actual
    assert actual == result["entity_count_before"] + 2

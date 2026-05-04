from __future__ import annotations

import pytest

from src.framework.autocad import inspector
from src.framework.autocad.inspector import (
    DrawingInspectionError,
    _to_xyz,
    get_model_space_block,
    inspect_active_drawing,
    inspect_entity,
    summarize_drawing_state,
)
from src.parametric.vessel.dwg_export import AutoCADNotRunningError


class FakeEntity:
    def __init__(self, **properties):
        self.__dict__.update(properties)
        self._bbox = properties.get("bbox")

    def GetBoundingBox(self):
        if self._bbox is None:
            raise RuntimeError("no bounding box")
        return self._bbox


class BadEntity:
    def __getattr__(self, _name):
        raise RuntimeError("bad property")


class FakeModelSpace:
    def __init__(self, entities):
        self.entities = list(entities)

    @property
    def Count(self):
        return len(self.entities)

    def __iter__(self):
        return iter(self.entities)

    def Item(self, index):
        return self.entities[index]


class FakeBlocks:
    def __init__(self, modelspace=None, error: Exception | None = None):
        self.modelspace = modelspace
        self.error = error
        self.item_calls = []

    def Item(self, name):
        self.item_calls.append(name)
        if self.error is not None:
            raise self.error
        if name != "*Model_Space":
            raise KeyError(name)
        return self.modelspace


class FakeDocument:
    def __init__(self, entities):
        self.Name = "Drawing10.dwg"
        self.FullName = r"C:\Drawings\Drawing10.dwg"
        self.ModelSpace = FakeModelSpace(entities)
        self.Blocks = FakeBlocks(self.ModelSpace)


class FakeDocumentModelSpaceFails:
    def __init__(self, entities, blocks_error: Exception | None = None):
        self.Name = "Drawing10.dwg"
        self.FullName = r"C:\Drawings\Drawing10.dwg"
        self.fallback_modelspace = FakeModelSpace(entities)
        self.Blocks = FakeBlocks(self.fallback_modelspace, error=blocks_error)

    @property
    def ModelSpace(self):
        raise AttributeError("<unknown>.ModelSpace")


class FakeAcad:
    def __init__(self, doc):
        self.ActiveDocument = doc


@pytest.fixture
def fake_com(monkeypatch):
    entities = [
        FakeEntity(
            Handle="10",
            ObjectName="AcDbLine",
            Layer="GEOMETRY",
            Color=1,
            Linetype="Continuous",
            StartPoint=(0, 0, 0),
            EndPoint=(100, 0, 0),
            bbox=((0, 0, 0), (100, 0, 0)),
        ),
        FakeEntity(
            Handle="11",
            ObjectName="AcDbCircle",
            Layer="GEOMETRY",
            Color=2,
            Linetype="Continuous",
            Center=(50, 50, 0),
            Radius=25,
            bbox=((25, 25, 0), (75, 75, 0)),
        ),
        FakeEntity(
            Handle="12",
            ObjectName="AcDbText",
            Layer="TEXT",
            Color=3,
            Linetype="Continuous",
            InsertionPoint=(0, 120, 0),
            TextString="Title",
            bbox=((0, 120, 0), (100, 140, 0)),
        ),
    ]
    doc = FakeDocument(entities)
    acad = FakeAcad(doc)

    monkeypatch.setattr(inspector, "_get_acad", lambda: acad)
    monkeypatch.setattr(
        inspector,
        "_com_retry",
        lambda operation, description, attempts=5, delay_seconds=0.5: operation(),
    )

    return doc


def test_to_xyz_converts_tuples_and_lists() -> None:
    assert _to_xyz((1, 2, 3)) == [1.0, 2.0, 3.0]
    assert _to_xyz([4, 5]) == [4.0, 5.0, 0.0]


def test_to_xyz_returns_none_for_invalid_values() -> None:
    assert _to_xyz(None) is None
    assert _to_xyz("1,2,3") is None
    assert _to_xyz([1]) is None
    assert _to_xyz(["x", 2, 3]) is None


def test_inspect_entity_extracts_common_fields() -> None:
    entity = FakeEntity(
        Handle="AA",
        ObjectName="AcDbLine",
        Layer="GEOMETRY",
        Color="4",
        Linetype="Hidden",
    )

    result = inspect_entity(entity, 7)

    assert result["index"] == 7
    assert result["handle"] == "AA"
    assert result["object_name"] == "AcDbLine"
    assert result["entity_type"] == "AcDbLine"
    assert result["layer"] == "GEOMETRY"
    assert result["color"] == 4
    assert result["linetype"] == "Hidden"


def test_inspect_entity_extracts_line_start_and_end_points() -> None:
    entity = FakeEntity(
        ObjectName="AcDbLine",
        StartPoint=(0, 0, 0),
        EndPoint=(10, 20, 0),
    )

    result = inspect_entity(entity, 0)

    assert result["start_point"] == [0.0, 0.0, 0.0]
    assert result["end_point"] == [10.0, 20.0, 0.0]


def test_inspect_entity_extracts_circle_center_and_radius() -> None:
    entity = FakeEntity(
        ObjectName="AcDbCircle",
        Center=(5, 6, 0),
        Radius="12.5",
    )

    result = inspect_entity(entity, 0)

    assert result["center"] == [5.0, 6.0, 0.0]
    assert result["radius"] == 12.5


def test_inspect_entity_extracts_text_position_and_text_string() -> None:
    entity = FakeEntity(
        ObjectName="AcDbText",
        InsertionPoint=(1, 2, 0),
        TextString="Pump A",
    )

    result = inspect_entity(entity, 0)

    assert result["position"] == [1.0, 2.0, 0.0]
    assert result["text"] == "Pump A"


def test_inspect_entity_handles_missing_properties_safely() -> None:
    result = inspect_entity(BadEntity(), 3)

    assert result["index"] == 3
    assert result["handle"] is None
    assert result["object_name"] is None
    assert result["layer"] is None
    assert result["bbox"] is None


def test_inspect_active_drawing_returns_document_metadata(fake_com) -> None:
    result = inspect_active_drawing()

    assert result["ok"] is True
    assert result["document_name"] == "Drawing10.dwg"
    assert result["dwg_path"] == r"C:\Drawings\Drawing10.dwg"
    assert result["entity_count_total"] == 3
    assert result["entity_count_returned"] == 3
    assert result["truncated"] is False


def test_get_model_space_block_uses_doc_modelspace_when_available(fake_com) -> None:
    assert get_model_space_block(fake_com) is fake_com.ModelSpace


def test_inspector_falls_back_to_blocks_model_space_when_doc_modelspace_fails(monkeypatch) -> None:
    entities = [
        FakeEntity(
            Handle="20",
            ObjectName="AcDbText",
            Layer="TEXT",
            TextString="Fallback Title",
            InsertionPoint=(0, 0, 0),
        )
    ]
    doc = FakeDocumentModelSpaceFails(entities)
    monkeypatch.setattr(inspector, "_get_acad", lambda: FakeAcad(doc))
    monkeypatch.setattr(
        inspector,
        "_com_retry",
        lambda operation, description, attempts=5, delay_seconds=0.5: operation(),
    )

    result = inspect_active_drawing()

    assert doc.Blocks.item_calls == ["*Model_Space"]
    assert result["entity_count_total"] == 1
    assert result["entities"][0]["text"] == "Fallback Title"


def test_get_model_space_block_raises_when_both_paths_fail(monkeypatch) -> None:
    doc = FakeDocumentModelSpaceFails([], blocks_error=AttributeError("Blocks.Item failed"))
    monkeypatch.setattr(
        inspector,
        "_com_retry",
        lambda operation, description, attempts=5, delay_seconds=0.5: operation(),
    )

    with pytest.raises(DrawingInspectionError) as exc_info:
        get_model_space_block(doc)

    message = str(exc_info.value)
    assert "doc.ModelSpace failed with AttributeError" in message
    assert 'doc.Blocks.Item("*Model_Space") failed with AttributeError' in message


def test_inspect_active_drawing_respects_max_entities(fake_com) -> None:
    result = inspect_active_drawing(max_entities=2)

    assert result["entity_count_returned"] == 2
    assert [entity["index"] for entity in result["entities"]] == [0, 1]


def test_inspect_active_drawing_sets_truncated_when_total_exceeds_max(fake_com) -> None:
    result = inspect_active_drawing(max_entities=2)

    assert result["entity_count_total"] == 3
    assert result["truncated"] is True


def test_summarize_drawing_state_includes_metadata_layers_and_type_counts(fake_com) -> None:
    result = inspect_active_drawing()

    summary = summarize_drawing_state(result)

    assert "Drawing10.dwg" in summary
    assert "3 entities returned" in summary
    assert "GEOMETRY" in summary
    assert "TEXT" in summary
    assert "AcDbLine=1" in summary
    assert "AcDbCircle=1" in summary
    assert "AcDbText=1" in summary


def test_autocad_connection_errors_are_surfaced_cleanly(monkeypatch) -> None:
    monkeypatch.setattr(
        inspector,
        "_get_acad",
        lambda: (_ for _ in ()).throw(AutoCADNotRunningError("AutoCAD unavailable")),
    )

    with pytest.raises(AutoCADNotRunningError, match="AutoCAD unavailable"):
        inspect_active_drawing()


def test_no_active_document_raises_inspection_error(monkeypatch) -> None:
    monkeypatch.setattr(inspector, "_get_acad", lambda: FakeAcad(None))
    monkeypatch.setattr(
        inspector,
        "_com_retry",
        lambda operation, description, attempts=5, delay_seconds=0.5: operation(),
    )

    with pytest.raises(DrawingInspectionError, match="No active AutoCAD document"):
        inspect_active_drawing()

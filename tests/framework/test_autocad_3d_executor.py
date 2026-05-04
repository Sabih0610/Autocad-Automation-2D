from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from src.framework.cad3d import autocad_3d_executor as executor
from src.framework.cad3d.autocad_3d_executor import (
    AutoCAD3DExecutionError,
    _distance_3d,
    _distance3,
    _execute_box_3d,
    _execute_component_3d,
    _execute_pipe_run_3d,
    _execute_skid_base_3d,
    _execute_vertical_tank_3d,
    _is_axis_aligned_segment,
    _midpoint3,
    _point3,
    _segment_midpoint,
    execute_cad3d_scene,
)
from src.framework.cad3d.component_examples import routed_tank_pump_separator_scene_data
from src.framework.cad3d.scene_examples import simple_3d_equipment_layout_scene


class FakeEntity:
    def __init__(self, kind: str):
        self.kind = kind
        self.rotations = []
        self.Color = None
        self.Layer = None

    def Rotate3D(self, point1, point2, angle):
        self.rotations.append((point1, point2, angle))


class FakeModelSpace:
    def __init__(self, fail_cylinder: bool = False):
        self.entities = []
        self.fail_cylinder = fail_cylinder

    @property
    def Count(self):
        return len(self.entities)

    def AddCylinder(self, center, radius, height):
        if self.fail_cylinder:
            raise RuntimeError("cylinder failed")
        entity = FakeEntity("CYLINDER")
        self.entities.append(("CYLINDER", center, radius, height, entity))
        return entity

    def AddBox(self, center, length, width, height):
        entity = FakeEntity("BOX")
        self.entities.append(("BOX", center, length, width, height, entity))
        return entity

    def AddLine(self, start, end):
        entity = FakeEntity("LINE")
        self.entities.append(("LINE", start, end, entity))
        return entity

    def AddText(self, text, position, height):
        entity = FakeEntity("TEXT")
        self.entities.append(("TEXT", text, position, height, entity))
        return entity


class FakeDoc:
    def __init__(self, fail_cylinder: bool = False):
        self.ModelSpace = FakeModelSpace(fail_cylinder=fail_cylinder)
        self.Name = "Drawing1.dwg"
        self.FullName = ""
        self.saved = False
        self.activated = False
        self.regen_count = 0

    def Save(self):
        self.saved = True

    def Activate(self):
        self.activated = True

    def Regen(self, mode):
        self.regen_count += 1


class FakeDocuments:
    def __init__(self, doc: FakeDoc):
        self.doc = doc
        self.opened_paths = []

    def Open(self, path: str):
        self.opened_paths.append(path)
        return self.doc


class FakeAcad:
    def __init__(self, doc: FakeDoc | None = None):
        self.ActiveDocument = doc or FakeDoc()
        self.Documents = FakeDocuments(self.ActiveDocument)
        self.zoomed = False

    def ZoomExtents(self):
        self.zoomed = True


def _patch_acad(monkeypatch, acad: FakeAcad):
    monkeypatch.setattr(executor, "_get_acad", lambda: acad)
    return acad


def test_invalid_scene_raises_execution_error() -> None:
    with pytest.raises(AutoCAD3DExecutionError):
        execute_cad3d_scene({"bad": "scene"})


def test_vector_helpers_work() -> None:
    assert _point3([1, 2, 3]) == [1.0, 2.0, 3.0]
    assert _distance3([0, 0, 0], [3, 4, 12]) == 13.0
    assert _distance_3d([0, 0, 0], [3, 4, 12]) == 13.0
    assert _midpoint3([0, 0, 0], [2, 4, 6]) == [1.0, 2.0, 3.0]


def test_is_axis_aligned_segment_detects_x_segment() -> None:
    assert _is_axis_aligned_segment([0, 0, 0], [100, 0, 0]) == (True, "X")


def test_is_axis_aligned_segment_detects_y_segment() -> None:
    assert _is_axis_aligned_segment([0, 0, 0], [0, 100, 0]) == (True, "Y")


def test_is_axis_aligned_segment_detects_z_segment() -> None:
    assert _is_axis_aligned_segment([0, 0, 0], [0, 0, 100]) == (True, "Z")


def test_is_axis_aligned_segment_rejects_diagonal_segment() -> None:
    assert _is_axis_aligned_segment([0, 0, 0], [100, 100, 0]) == (False, None)


def test_segment_midpoint_returns_expected_midpoint() -> None:
    assert _segment_midpoint([0, 0, 0], [100, 200, 300]) == [50.0, 100.0, 150.0]


def test_executor_dispatches_supported_component_types() -> None:
    doc = FakeDoc()
    component = {
        "component_type": "label_3d",
        "id": "LBL1",
        "text": "Test",
        "position": [0, 0, 0],
        "height": 100,
    }

    assert _execute_component_3d(doc, component) == 1
    assert doc.ModelSpace.entities[0][0] == "TEXT"


@pytest.mark.parametrize(
    ("component", "expected_entity"),
    [
        (
            {
                "component_type": "heat_exchanger_3d",
                "id": "E101",
                "tag": "E-101",
                "center": [0, 0, 600],
                "length": 2200,
                "diameter": 600,
                "orientation": "X",
            },
            "CYLINDER",
        ),
        (
            {
                "component_type": "valve_placeholder_3d",
                "id": "XV101",
                "center": [0, 0, 500],
                "length": 400,
                "width": 300,
                "height": 300,
                "orientation": "X",
                "valve_type": "gate",
            },
            "BOX",
        ),
        (
            {
                "component_type": "nozzle_3d",
                "id": "N101",
                "center": [0, 0, 500],
                "diameter": 150,
                "length": 400,
                "orientation": "Y",
            },
            "CYLINDER",
        ),
        (
            {
                "component_type": "flange_3d",
                "id": "FLG101",
                "center": [0, 0, 500],
                "diameter": 250,
                "thickness": 80,
                "orientation": "Z",
            },
            "CYLINDER",
        ),
        (
            {
                "component_type": "support_leg_3d",
                "id": "LEG101",
                "center": [0, 0, 500],
                "diameter": 120,
                "height": 1000,
            },
            "CYLINDER",
        ),
        (
            {
                "component_type": "saddle_support_3d",
                "id": "SAD101",
                "center": [0, 0, 250],
                "length": 700,
                "width": 350,
                "height": 500,
            },
            "BOX",
        ),
        (
            {
                "component_type": "pipe_support_3d",
                "id": "PS101",
                "center": [0, 0, 400],
                "height": 800,
                "width": 300,
                "depth": 300,
            },
            "BOX",
        ),
    ],
)
def test_executor_dispatches_expanded_component_types(component: dict, expected_entity: str) -> None:
    doc = FakeDoc()

    assert _execute_component_3d(doc, component) == 1
    assert doc.ModelSpace.entities[0][0] == expected_entity


def test_unknown_component_type_in_executor_raises() -> None:
    with pytest.raises(AutoCAD3DExecutionError):
        _execute_component_3d(FakeDoc(), {"component_type": "sphere_3d", "id": "S1"})


def test_vertical_tank_helper_calls_modelspace_add_cylinder() -> None:
    doc = FakeDoc()
    component = {
        "component_type": "vertical_tank_3d",
        "id": "T101",
        "tag": "T-101",
        "center": [0, 0, 900],
        "diameter": 900,
        "height": 1800,
    }

    assert _execute_vertical_tank_3d(doc, component) == 1
    assert doc.ModelSpace.entities[0][0] == "CYLINDER"


def test_box_and_skid_helpers_call_modelspace_add_box() -> None:
    doc = FakeDoc()
    component = {
        "component_type": "box_3d",
        "id": "B1",
        "center": [0, 0, 0],
        "length": 100,
        "width": 50,
        "height": 25,
    }

    assert _execute_box_3d(doc, component) == 1
    assert _execute_skid_base_3d(doc, {**component, "component_type": "skid_base_3d"}) == 1
    assert [entity[0] for entity in doc.ModelSpace.entities] == ["BOX", "BOX"]


def test_pipe_run_helper_creates_line_segments() -> None:
    doc = FakeDoc()
    component = {
        "component_type": "pipe_run_3d",
        "id": "P1",
        "points": [[0, 0, 0], [100, 0, 0], [100, 100, 0]],
        "diameter": 50,
        "visual_style": "centerline",
    }

    assert _execute_pipe_run_3d(doc, component) == 2
    assert [entity[0] for entity in doc.ModelSpace.entities] == ["LINE", "LINE"]


def test_pipe_run_centerline_visual_style_calls_add_line_only() -> None:
    doc = FakeDoc()
    component = {
        "component_type": "pipe_run_3d",
        "id": "P_CENTER",
        "points": [[0, 0, 0], [100, 0, 0]],
        "diameter": 50,
        "visual_style": "centerline",
    }

    assert _execute_pipe_run_3d(doc, component) == 1
    assert [entity[0] for entity in doc.ModelSpace.entities] == ["LINE"]


def test_pipe_run_solid_visual_style_calls_add_cylinder_for_axis_aligned_segment() -> None:
    doc = FakeDoc()
    component = {
        "component_type": "pipe_run_3d",
        "id": "P_SOLID",
        "points": [[0, 0, 0], [100, 0, 0]],
        "diameter": 50,
        "visual_style": "solid",
    }

    assert _execute_pipe_run_3d(doc, component) == 1
    assert [entity[0] for entity in doc.ModelSpace.entities] == ["CYLINDER"]
    assert doc.ModelSpace.entities[0][-1].rotations


def test_pipe_run_solid_with_centerline_calls_add_cylinder_and_add_line() -> None:
    doc = FakeDoc()
    component = {
        "component_type": "pipe_run_3d",
        "id": "P_SOLID_CENTER",
        "points": [[0, 0, 0], [0, 100, 0]],
        "diameter": 50,
        "visual_style": "solid_with_centerline",
    }

    assert _execute_pipe_run_3d(doc, component) == 2
    assert [entity[0] for entity in doc.ModelSpace.entities] == ["CYLINDER", "LINE"]


def test_pipe_run_diagonal_segment_falls_back_to_add_line() -> None:
    doc = FakeDoc()
    component = {
        "component_type": "pipe_run_3d",
        "id": "P_DIAGONAL",
        "points": [[0, 0, 0], [100, 100, 0]],
        "diameter": 50,
        "visual_style": "solid",
    }

    assert _execute_pipe_run_3d(doc, component) == 1
    assert [entity[0] for entity in doc.ModelSpace.entities] == ["LINE"]


def test_pipe_run_multiple_orthogonal_points_create_multiple_solid_segments() -> None:
    doc = FakeDoc()
    component = {
        "component_type": "pipe_run_3d",
        "id": "P_MULTI",
        "points": [[0, 0, 0], [100, 0, 0], [100, 100, 0], [100, 100, 100]],
        "diameter": 50,
        "visual_style": "solid",
    }

    assert _execute_pipe_run_3d(doc, component) == 3
    assert [entity[0] for entity in doc.ModelSpace.entities] == ["CYLINDER", "CYLINDER", "CYLINDER"]


def test_pipe_run_zero_length_segment_is_skipped_without_crashing() -> None:
    doc = FakeDoc()
    component = {
        "component_type": "pipe_run_3d",
        "id": "P_ZERO",
        "points": [[0, 0, 0], [0, 0, 0]],
        "diameter": 50,
        "visual_style": "solid",
    }

    assert _execute_pipe_run_3d(doc, component) == 0
    assert doc.ModelSpace.entities == []


def test_full_fake_execution_returns_ok_and_counts(monkeypatch) -> None:
    acad = _patch_acad(monkeypatch, FakeAcad())
    scene = simple_3d_equipment_layout_scene()

    result = execute_cad3d_scene(scene, save=True, zoom_extents=True)

    assert result["ok"] is True
    assert result["total_count"] == len(scene["components"])
    assert result["executed_count"] == len(scene["components"])
    assert result["document_name"] == "Drawing1.dwg"
    assert result["entity_count_before"] == 0
    assert result["entity_count_after"] == acad.ActiveDocument.ModelSpace.Count
    assert result["zoom_extents_called"] is True
    assert acad.ActiveDocument.saved is True
    assert acad.zoomed is True


def test_execute_cad3d_scene_expands_pipe_connection_before_execution(monkeypatch) -> None:
    _patch_acad(monkeypatch, FakeAcad())
    scene = routed_tank_pump_separator_scene_data()
    received_component_types = []

    def fake_execute_component(doc, component):
        received_component_types.append(component["component_type"])
        assert component["component_type"] != "pipe_connection_3d"
        return 1

    monkeypatch.setattr(executor, "_execute_component_3d", fake_execute_component)

    result = execute_cad3d_scene(scene, save=False, zoom_extents=False)

    assert result["ok"] is True
    assert "pipe_connection_3d" not in received_component_types
    assert received_component_types.count("pipe_run_3d") == 2
    assert result["pipe_connections_expanded"] == 2


def test_execute_cad3d_scene_result_includes_routing_counts(monkeypatch) -> None:
    _patch_acad(monkeypatch, FakeAcad())
    scene = routed_tank_pump_separator_scene_data()

    result = execute_cad3d_scene(scene, save=False, zoom_extents=False)

    assert result["pipe_connections_expanded"] == 2
    assert result["original_component_count"] == len(scene["components"])
    assert result["executable_component_count"] == result["total_count"]


def test_routed_pipe_connection_scene_creates_solid_pipe_segments_after_expansion(monkeypatch) -> None:
    acad = _patch_acad(monkeypatch, FakeAcad())
    scene = routed_tank_pump_separator_scene_data()

    result = execute_cad3d_scene(scene, save=False, zoom_extents=False)
    cylinder_entities = [
        entity
        for entity in acad.ActiveDocument.ModelSpace.entities
        if entity[0] == "CYLINDER"
    ]

    assert result["ok"] is True
    assert result["pipe_connections_expanded"] == 2
    assert len(cylinder_entities) > 2


def test_existing_pipe_run_scene_still_executes_with_same_counts(monkeypatch) -> None:
    _patch_acad(monkeypatch, FakeAcad())
    scene = simple_3d_equipment_layout_scene()

    result = execute_cad3d_scene(scene, save=False, zoom_extents=False)

    assert result["ok"] is True
    assert result["pipe_connections_expanded"] == 0
    assert result["total_count"] == len(scene["components"])
    assert result["executed_count"] == len(scene["components"])


def test_invalid_pipe_connection_raises_execution_error() -> None:
    scene = routed_tank_pump_separator_scene_data()
    for component in scene["components"]:
        if component["component_type"] == "pipe_connection_3d":
            component["from_port"] = "MISSING.side_right"
            break

    with pytest.raises(AutoCAD3DExecutionError, match="pipe routing"):
        execute_cad3d_scene(scene, save=False, zoom_extents=False)


def test_component_failure_records_error_and_returns_not_ok(monkeypatch) -> None:
    acad = _patch_acad(monkeypatch, FakeAcad(FakeDoc(fail_cylinder=True)))
    scene = simple_3d_equipment_layout_scene()
    scene["components"] = [
        component
        for component in scene["components"]
        if component["component_type"] in {"vertical_tank_3d", "label_3d"}
    ]

    result = execute_cad3d_scene(scene, save=False, zoom_extents=False)

    assert result["ok"] is False
    assert result["errors"]
    assert result["errors"][0]["component_id"] == "T101"
    assert result["executed_count"] >= 1


def test_target_dwg_path_opens_document(monkeypatch) -> None:
    acad = _patch_acad(monkeypatch, FakeAcad())
    scene = deepcopy(simple_3d_equipment_layout_scene())
    scene["components"] = [
        {
            "component_type": "label_3d",
            "id": "LBL1",
            "text": "Test",
            "position": [0, 0, 0],
            "height": 100,
        }
    ]

    result = execute_cad3d_scene(scene, target_dwg_path="C:/Temp/test.dwg", zoom_extents=False)

    assert acad.Documents.opened_paths == ["C:/Temp/test.dwg"]
    assert result["dwg_path"] == str(Path("C:/Temp/test.dwg"))

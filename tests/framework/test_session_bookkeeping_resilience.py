from __future__ import annotations

from copy import deepcopy

from src.cad import session
from src.framework.cad3d import (
    autocad_3d_executor,
)
from src.framework.cad3d.scene_examples import (
    simple_3d_equipment_layout_scene,
)
from src.framework.commands import (
    edit_executor,
    executor,
)
from tests.project.fake_cad import Acad
from tests.project.test_extractor import (
    make_dxf,
)


def _locked_database(
    *_args,
    **_kwargs,
):
    raise RuntimeError(
        "database is locked"
    )


def test_command_write_survives_session_bookkeeping_failure(
    tmp_path,
    monkeypatch,
):
    drawing = tmp_path / "command.dxf"
    make_dxf(drawing)

    acad = Acad()

    monkeypatch.setattr(
        executor,
        "_get_acad",
        lambda: acad,
    )

    monkeypatch.setattr(
        session,
        "mark_open",
        _locked_database,
    )

    result = executor.execute_commands(
        [
            {
                "command": "LINE",
                "from": [0, 0],
                "to": [10, 0],
            }
        ],
        target_dwg_path=str(drawing),
        save=False,
        zoom_extents=False,
    )

    assert result["ok"] is True
    assert (
        acad.Documents.documents[-1].closed
        is True
    )

    reason = result[
        "session_bookkeeping_skipped_reason"
    ]

    assert reason is not None
    assert "database is locked" in reason
    assert "as open" in reason
    assert "as closed" in reason


def test_edit_write_survives_session_bookkeeping_failure(
    tmp_path,
    monkeypatch,
):
    drawing = tmp_path / "edit.dxf"
    make_dxf(drawing)

    acad = Acad()

    monkeypatch.setattr(
        edit_executor,
        "_get_acad",
        lambda: acad,
    )

    monkeypatch.setattr(
        session,
        "mark_open",
        _locked_database,
    )

    plan = {
        "schema_version": "1.0",
        "edit_intent": "Add a line.",
        "summary":
            "Add a line while bookkeeping is unavailable.",
        "assumptions": [],
        "delete_handles": [],
        "commands": [
            {
                "command": "LINE",
                "from": [0, 0],
                "to": [10, 0],
            }
        ],
    }

    result = (
        edit_executor.execute_edit_plan(
            plan,
            target_dwg_path=str(drawing),
            save=False,
            zoom_extents=False,
        )
    )

    assert result["ok"] is True
    assert (
        acad.Documents.documents[-1].closed
        is True
    )

    reason = result[
        "session_bookkeeping_skipped_reason"
    ]

    assert reason is not None
    assert "database is locked" in reason
    assert "as open" in reason
    assert "as closed" in reason


def test_cad3d_write_survives_session_bookkeeping_failure(
    tmp_path,
    monkeypatch,
):
    drawing = tmp_path / "cad3d.dxf"
    make_dxf(drawing)

    acad = Acad()

    monkeypatch.setattr(
        autocad_3d_executor,
        "_get_acad",
        lambda: acad,
    )

    monkeypatch.setattr(
        session,
        "mark_open",
        _locked_database,
    )

    monkeypatch.setattr(
        autocad_3d_executor,
        "_ensure_cad3d_presentation_layers",
        lambda _doc: None,
    )

    monkeypatch.setattr(
        autocad_3d_executor,
        "_execute_component_3d",
        lambda _doc, _component: 1,
    )

    scene = deepcopy(
        simple_3d_equipment_layout_scene()
    )

    scene["components"] = [
        {
            "component_type": "label_3d",
            "id": "LBL_BOOKKEEPING",
            "text": "Bookkeeping test",
            "position": [0, 0, 0],
            "height": 100,
        }
    ]

    result = (
        autocad_3d_executor
        .execute_cad3d_scene(
            scene,
            target_dwg_path=str(drawing),
            save=False,
            zoom_extents=False,
        )
    )

    assert result["ok"] is True
    assert (
        acad.Documents.documents[-1].closed
        is True
    )

    reason = result[
        "session_bookkeeping_skipped_reason"
    ]

    assert reason is not None
    assert "database is locked" in reason
    assert "as open" in reason
    assert "as closed" in reason
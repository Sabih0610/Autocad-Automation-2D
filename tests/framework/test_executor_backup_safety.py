from __future__ import annotations

import hashlib
from pathlib import Path

from src import backup
from src.framework.cad3d import autocad_3d_executor
from src.framework.cad3d.autocad_3d_executor import execute_cad3d_scene
from src.framework.cad3d.scene_examples import simple_3d_equipment_layout_scene
from src.framework.commands import edit_executor, executor
from src.framework.commands.edit_executor import execute_edit_plan
from src.framework.commands.executor import execute_commands
from tests.project.fake_cad import Acad, Document
from tests.project.test_extractor import make_dxf


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _line_command() -> dict:
    return {"command": "LINE", "from": [0, 0], "to": [25, 25]}


def _patch_command_acad(monkeypatch, acad: Acad) -> None:
    monkeypatch.setattr(executor, "_get_acad", lambda: acad)
    monkeypatch.setattr(executor, "acad_point", lambda x, y, z=0.0: (x, y, z))


def test_failed_command_is_not_saved_and_drawing_bytes_are_unchanged(
    tmp_path, monkeypatch
) -> None:
    drawing = tmp_path / "drawing.dxf"
    make_dxf(drawing)
    original = drawing.read_bytes()
    monkeypatch.setattr(backup, "BACKUP_ROOT", tmp_path / "backups")
    acad = Acad()
    _patch_command_acad(monkeypatch, acad)

    result = execute_commands(
        [_line_command(), {"command": "UNSUPPORTED"}],
        target_dwg_path=str(drawing),
        save=True,
        zoom_extents=False,
    )

    doc = acad.Documents.documents[-1]
    assert result["ok"] is False
    assert doc.save_calls == 0
    assert drawing.read_bytes() == original
    assert Path(result["backup_path"]).read_bytes() == original
    assert result["backup_skipped_reason"] is None


def test_successful_commands_create_verified_pre_edit_backup(
    tmp_path, monkeypatch
) -> None:
    drawing = tmp_path / "drawing.dxf"
    make_dxf(drawing)
    original = drawing.read_bytes()
    monkeypatch.setattr(backup, "BACKUP_ROOT", tmp_path / "backups")
    acad = Acad()
    _patch_command_acad(monkeypatch, acad)

    result = execute_commands(
        [_line_command()],
        target_dwg_path=str(drawing),
        save=True,
        zoom_extents=False,
    )

    backup_path = Path(result["backup_path"])
    assert result["ok"] is True
    assert acad.Documents.documents[-1].save_calls == 1
    assert backup_path.is_file()
    assert _sha256_bytes(backup_path.read_bytes()) == _sha256_bytes(original)
    assert result["backup_skipped_reason"] is None


def test_unsaved_active_document_executes_and_reports_backup_skip(
    tmp_path, monkeypatch
) -> None:
    seed = tmp_path / "seed.dxf"
    make_dxf(seed)
    doc = Document(seed)
    doc.FullName = ""
    doc.Name = "Drawing1.dwg"

    def save_unsaved_document():
        doc.save_calls += 1
        doc.Saved = True

    doc.Save = save_unsaved_document

    class ActiveAcad:
        ActiveDocument = doc

    monkeypatch.setattr(executor, "_get_acad", lambda: ActiveAcad())
    monkeypatch.setattr(executor, "acad_point", lambda x, y, z=0.0: (x, y, z))
    monkeypatch.setattr(backup, "BACKUP_ROOT", tmp_path / "backups")

    result = execute_commands([_line_command()], save=True, zoom_extents=False)

    assert result["ok"] is True
    assert doc.save_calls == 1
    assert result["backup_path"] is None
    assert "unsaved/untitled" in result["backup_skipped_reason"]


def test_save_false_creates_no_backup_and_does_not_save(tmp_path, monkeypatch) -> None:
    drawing = tmp_path / "drawing.dxf"
    make_dxf(drawing)
    backup_root = tmp_path / "backups"
    monkeypatch.setattr(backup, "BACKUP_ROOT", backup_root)
    acad = Acad()
    _patch_command_acad(monkeypatch, acad)

    result = execute_commands(
        [_line_command()],
        target_dwg_path=str(drawing),
        save=False,
        zoom_extents=False,
    )

    assert acad.Documents.documents[-1].save_calls == 0
    assert result["backup_path"] is None
    assert result["backup_skipped_reason"] is None
    assert not backup_root.exists()


def test_edit_delete_success_add_failure_is_not_saved(tmp_path, monkeypatch) -> None:
    drawing = tmp_path / "drawing.dxf"
    handle = make_dxf(drawing)
    original = drawing.read_bytes()
    monkeypatch.setattr(backup, "BACKUP_ROOT", tmp_path / "backups")
    acad = Acad()
    monkeypatch.setattr(edit_executor, "_get_acad", lambda: acad)
    monkeypatch.setattr(
        edit_executor,
        "execute_commands_in_document",
        lambda *args, **kwargs: {
            "ok": False,
            "executed_count": 0,
            "total_count": 1,
            "errors": [{"command_index": 0, "error": "RuntimeError: add failed"}],
        },
    )
    plan = {
        "schema_version": "1.0",
        "edit_intent": "Replace a line.",
        "summary": "Delete then add.",
        "assumptions": [],
        "delete_handles": [handle],
        "commands": [_line_command()],
    }

    result = execute_edit_plan(
        plan,
        target_dwg_path=str(drawing),
        save=True,
        zoom_extents=False,
    )

    doc = acad.Documents.documents[-1]
    assert result["deleted_count"] == 1
    assert result["ok"] is False
    assert doc.save_calls == 0
    assert drawing.read_bytes() == original
    assert Path(result["backup_path"]).read_bytes() == original


def test_cad3d_component_failure_is_not_saved(tmp_path, monkeypatch) -> None:
    drawing = tmp_path / "drawing.dxf"
    make_dxf(drawing)
    original = drawing.read_bytes()
    monkeypatch.setattr(backup, "BACKUP_ROOT", tmp_path / "backups")
    acad = Acad()
    monkeypatch.setattr(autocad_3d_executor, "_get_acad", lambda: acad)
    monkeypatch.setattr(
        autocad_3d_executor, "_ensure_cad3d_presentation_layers", lambda doc: None
    )
    calls = 0

    def fail_second_component(doc, component):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("component failed")
        return 1

    monkeypatch.setattr(
        autocad_3d_executor, "_execute_component_3d", fail_second_component
    )
    scene = simple_3d_equipment_layout_scene()

    result = execute_cad3d_scene(
        scene,
        target_dwg_path=str(drawing),
        save=True,
        zoom_extents=False,
    )

    doc = acad.Documents.documents[-1]
    assert result["ok"] is False
    assert doc.save_calls == 0
    assert drawing.read_bytes() == original
    assert Path(result["backup_path"]).read_bytes() == original

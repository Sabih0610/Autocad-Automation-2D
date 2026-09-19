from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src import backup
from src.cad.changes import ChangeManager, get_change_set
from src.cad.scanner import scan_project
from src.storage.entity_repository import find_by_tag
from src.storage.project_repository import register_project
from src.framework.commands import modification_executor as engine
from tests.project.fake_cad import Acad
from tests.project.test_extractor import make_dxf
from tests.project.test_modification import resize


@pytest.fixture
def managed(tmp_path, monkeypatch):
    path = tmp_path / "a.dxf"
    handle = make_dxf(path)
    project = register_project("Plant", str(tmp_path))["project_id"]
    scan_project(project, max_workers=1)
    monkeypatch.setattr(engine, "point", tuple)
    acad = Acad()
    return path, handle, project, ChangeManager(acad=acad), acad


def test_backup_names_do_not_collide_for_same_named_drawings(tmp_path):
    paths = []
    for folder in ("one", "two"):
        path = tmp_path / folder / "a.dwg"
        path.parent.mkdir()
        path.write_text(folder)
        paths.append(backup.backup_file(path))
    assert paths[0] != paths[1]
    assert [p.read_text() for p in paths] == ["one", "two"]


def test_revert_restores_exact_bytes_and_index_in_one_action(managed):
    path, handle, project, manager, acad = managed
    original = path.read_bytes()
    change = manager.apply(project, [resize(path, handle, delta_mm=50)], "Increase P-101")
    assert change["status"] == "pending"
    assert find_by_tag(project, "P-101")[0]["end_x"] == 1050
    assert change["items"][0]["before_value"] == [1000, 0, 0]
    restored = manager.revert(change["change_set_id"])
    assert restored["status"] == "reverted"
    assert path.read_bytes() == original
    assert find_by_tag(project, "P-101")[0]["end_x"] == 1000
    assert manager.revert(change["change_set_id"])["status"] == "reverted"
    assert acad.Documents.documents[0].closed


def test_keep_is_persistent_idempotent_and_prevents_revert(managed):
    path, handle, project, manager, acad = managed
    change = manager.apply(project, [resize(path, handle, delta_mm=50)], "Resize")
    new_manager = ChangeManager(acad=acad)
    assert new_manager.keep(change["change_set_id"])["status"] == "kept"
    assert new_manager.keep(change["change_set_id"])["status"] == "kept"
    with pytest.raises(ValueError, match="finalized"):
        new_manager.revert(change["change_set_id"])


def test_pending_changeset_blocks_overlapping_edits(managed):
    path, handle, project, manager, _ = managed
    manager.apply(project, [resize(path, handle, delta_mm=50)], "First")
    with pytest.raises(ValueError, match="pending changeset"):
        manager.apply(project, [resize(path, handle, delta_mm=50)], "Second")


def test_later_disk_or_unsaved_edits_are_not_overwritten(managed):
    path, handle, project, manager, acad = managed
    change = manager.apply(project, [resize(path, handle, delta_mm=50)], "Resize")
    changed = path.read_bytes()
    acad.Documents.documents[0].Saved = False
    with pytest.raises(ValueError, match="unsaved"):
        manager.revert(change["change_set_id"])
    acad.Documents.documents[0].Saved = True
    path.write_bytes(changed + b"later")
    with pytest.raises(ValueError, match="later work"):
        manager.revert(change["change_set_id"])
    assert path.read_bytes().endswith(b"later")


def test_partial_failure_can_revert_every_file(managed, tmp_path):
    path, handle, project, manager, _ = managed
    second = tmp_path / "b.dxf"
    handle2 = make_dxf(second)
    scan_project(project, max_workers=1)
    originals = {p: p.read_bytes() for p in (path, second)}
    change = manager.apply(project, [resize(path, handle, delta_mm=50), resize(second, handle2, delta_mm=-2000)], "Two files")
    assert change["status"] == "error"
    assert not change["validation"][0]["passed"]
    with pytest.raises(ValueError):
        manager.keep(change["change_set_id"])
    assert manager.revert(change["change_set_id"])["status"] == "reverted"
    assert all(p.read_bytes() == data for p, data in originals.items())


def test_rename_can_revert_without_autocad(managed, monkeypatch):
    path, handle, project, manager, _ = managed
    import src.cad.changes as module
    def forbidden(*args):
        pytest.fail("Rename and its revert are filesystem-only")
    monkeypatch.setattr(module, "cad_session", forbidden)
    original = path.read_bytes()
    change = manager.apply(project, [dict(command="RENAME_FILE", target_dwg_path=str(path), new_name="b.dxf")], "Rename")
    assert change["status"] == "pending"
    assert not path.exists()
    manager.revert(change["change_set_id"])
    assert path.read_bytes() == original
    assert not path.with_name("b.dxf").exists()


def test_changeset_api_apply_detail_and_revert(managed, monkeypatch):
    from src.api.routes import changes
    path, handle, project, manager, _ = managed
    monkeypatch.setattr(changes, "manager", lambda: manager)
    app = FastAPI()
    app.include_router(changes.router)
    client = TestClient(app)
    response = client.post("/api/change-sets", json=dict(project_id=project, summary="Resize", operations=[resize(path, handle, delta_mm=50)]))
    assert response.status_code == 200
    change_id = response.json()["change_set_id"]
    assert client.get(f"/api/change-sets/{change_id}").json()["status"] == "pending"
    assert client.post(f"/api/change-sets/{change_id}/revert").json()["status"] == "reverted"
    assert client.post(f"/api/change-sets/{change_id}/keep").status_code == 409

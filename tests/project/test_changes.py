from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src import backup
from src.cad.changes import ChangeManager, get_change_set
from src.cad.extractor import DXFExtractor
from src.cad.scanner import scan_project
from src.storage.entity_repository import find_by_tag
from src.storage.project_repository import register_project
from src.framework.commands import modification_executor as engine
from tests.project.fake_cad import Acad, Document
from tests.project.test_extractor import make_dxf
from tests.project.test_modification import resize


@pytest.fixture
def managed(tmp_path, monkeypatch):
    path = tmp_path / "a.dxf"
    handle = make_dxf(path)
    project = register_project("Plant", str(tmp_path))
    scan_project(project, max_workers=1)
    monkeypatch.setattr(engine, "point", tuple)
    acad = Acad()
    return path, handle, project, ChangeManager(acad=acad), acad


def test_overlapping_project_roots_do_not_block_editing(tmp_path, monkeypatch):
    """Registering a parent folder and one of its own subfolders as two
    separate projects, then scanning both, previously broke every edit
    inside the overlapping subfolder: the same physical file gets indexed
    under two different `drawing_id`s (one per project), so a path+handle
    lookup with no project scope always matched both rows and refused to
    edit, reporting "not uniquely indexed" even though the caller
    unambiguously selected one specific project."""
    parent_root = tmp_path / "plant"
    child_root = parent_root / "unit_a"
    child_root.mkdir(parents=True)
    path = child_root / "a.dxf"
    handle = make_dxf(path)

    parent_project = register_project("Plant", str(parent_root))
    child_project = register_project("Unit A", str(child_root))
    scan_project(parent_project, max_workers=1)
    scan_project(child_project, max_workers=1)

    monkeypatch.setattr(engine, "point", tuple)
    manager = ChangeManager(acad=Acad())
    change = manager.apply(child_project, [resize(path, handle, delta_mm=50)], "Resize via child project")
    assert change["status"] == "pending"
    assert change["validation"][0]["passed"] == 1


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
    before = DXFExtractor().extract(path)
    change = manager.apply(project, [resize(path, handle, delta_mm=50)], "Increase P-101")
    assert change["status"] == "pending"
    assert find_by_tag(project, "P-101")[0]["end_x"] == 1050
    assert change["items"][0]["before_value"] == [1000, 0, 0]
    assert change["items"][0]["after_value"] == [1050, 0, 0]
    assert change["validation"][0]["passed"] == 1
    assert Path(change["files"][0]["backup_path"]).read_bytes() == original
    restored = manager.revert(change["change_set_id"])
    assert restored["status"] == "reverted"
    assert path.read_bytes() == original
    after = DXFExtractor().extract(path)
    assert after.entities == before.entities
    assert after.properties == before.properties
    assert after.spatial_data == before.spatial_data
    assert find_by_tag(project, "P-101")[0]["end_x"] == 1000
    assert manager.revert(change["change_set_id"])["status"] == "reverted"
    assert acad.Documents.documents[0].closed


def test_keep_is_persistent_idempotent_and_prevents_revert(managed):
    path, handle, project, manager, acad = managed
    change = manager.apply(project, [resize(path, handle, delta_mm=50)], "Resize")
    saved = path.read_bytes()
    new_manager = ChangeManager(acad=acad)
    assert new_manager.keep(change["change_set_id"])["status"] == "kept"
    assert path.read_bytes() == saved
    assert new_manager.keep(change["change_set_id"])["status"] == "kept"
    with pytest.raises(ValueError, match="finalized"):
        new_manager.revert(change["change_set_id"])


@pytest.mark.parametrize("kind", ["resize", "entity", "document", "custom", "layer", "rename"])
def test_direct_edits_back_up_before_the_first_mutation(managed, monkeypatch, kind):
    path, handle, _, _, _ = managed
    original = path.read_bytes()
    document = Document(path)
    acad = Acad([document])
    operations = {
        "resize": resize(path, handle, delta_mm=50),
        "entity": dict(command="SET_ENTITY_PROPERTY", target_dwg_path=str(path), handle=handle,
                       property="color", value=3),
        "document": dict(command="SET_DOCUMENT_PROPERTY", target_dwg_path=str(path),
                         property="author", value="Engineer"),
        "custom": dict(command="SET_DOCUMENT_PROPERTY", target_dwg_path=str(path),
                       property="custom", key="PROJECT", value="Plant"),
        "layer": dict(command="SET_LAYER_COLOR", target_dwg_path=str(path), layer="0", color=2),
        "rename": dict(command="RENAME_FILE", target_dwg_path=str(path), new_name="renamed.dxf"),
    }
    backups = []
    original_backup = backup.backup_file

    def checked_backup(source):
        copy = original_backup(source)
        assert copy.read_bytes() == original
        backups.append(copy)
        return copy

    monkeypatch.setattr(backup, "backup_file", checked_backup)
    if kind == "custom":
        def add_custom(key, value):
            assert backups and backups[0].read_bytes() == original
            document.SummaryInfo.custom = (key, value)
        document.SummaryInfo.GetCustomByKey = lambda key: (_ for _ in ()).throw(KeyError(key))
        document.SummaryInfo.AddCustomInfo = add_custom
    elif kind == "rename":
        original_rename = Path.rename
        def checked_rename(self, target):
            assert backups and backups[0].read_bytes() == original
            return original_rename(self, target)
        monkeypatch.setattr(Path, "rename", checked_rename)
    else:
        original_assign = engine._assign
        def checked_assign(change, value):
            assert backups and backups[0].read_bytes() == original
            return original_assign(change, value)
        monkeypatch.setattr(engine, "_assign", checked_assign)

    result = engine.execute_operation(operations[kind], acad=acad)
    assert result["backup_path"] == str(backups[0])
    assert len(backups) == 1


def test_preexisting_backup_must_be_a_separate_file(managed):
    path, handle, _, _, _ = managed
    original = path.read_bytes()
    with pytest.raises(ValueError, match="separate"):
        engine.execute_operation(resize(path, handle, delta_mm=50), acad=Acad([Document(path)]),
                                 _preexisting_backup_path=path)
    assert path.read_bytes() == original


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


def test_rename_with_forward_slash_path_does_not_crash(managed):
    """A rename operation whose `target_dwg_path` uses forward slashes (as
    `Path.as_posix()` would produce, or any caller that doesn't happen to
    use the native OS separator) previously wasn't recognized as matching
    its own entry in `targets` (whose keys are canonicalized), so the
    "already covered by a rename" check treated it as a normal COM-needing
    operation with no session available — crashing with
    "'NoneType' object has no attribute 'Documents'" instead of renaming
    the file."""
    path, handle, project, manager, _ = managed
    posix_path = path.as_posix()
    change = manager.apply(project, [dict(command="RENAME_FILE", target_dwg_path=posix_path, new_name="c.dxf")], "Rename")
    assert change["status"] == "pending"
    assert not path.exists()
    assert path.with_name("c.dxf").exists()


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


def test_rename_revert_resumes_after_transient_failure_removing_renamed_file(managed, monkeypatch):
    """Reproduces, and fixes, a real stuck-state bug: if `revert()` restores
    `original_path` from the backup but then hits a transient failure (e.g. a
    locked file) removing the now-superfluous renamed file, `original_path`
    is left existing. A naive retry's own conflict guard
    ("Original rename destination now exists") would previously see that
    already-correct restoration and refuse to proceed forever — the very
    state the first attempt's partial success left behind permanently
    blocked every future retry, with no way to recover short of manual
    intervention. See `ChangeManager._check_files`/`revert`."""
    path, handle, project, manager, _ = managed
    import src.cad.changes as module
    original = path.read_bytes()

    change = manager.apply(project, [dict(command="RENAME_FILE", target_dwg_path=str(path), new_name="b.dxf")], "Rename")
    renamed_path = path.with_name("b.dxf")
    assert not path.exists()
    assert renamed_path.exists()

    real_unlink = Path.unlink
    def failing_unlink(self, *args, **kwargs):
        if self == renamed_path:
            raise PermissionError("simulated: file locked by another process")
        return real_unlink(self, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", failing_unlink)

    with pytest.raises(PermissionError):
        manager.revert(change["change_set_id"])

    # The partial-failure state this bug is about: original restored,
    # renamed file NOT yet removed because the injected fault blocked it.
    assert path.read_bytes() == original
    assert renamed_path.exists()
    assert get_change_set(change["change_set_id"])["status"] == "reverting"

    monkeypatch.setattr(Path, "unlink", real_unlink)
    result = manager.revert(change["change_set_id"])
    assert result["status"] == "reverted"
    assert path.read_bytes() == original
    assert not renamed_path.exists()


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

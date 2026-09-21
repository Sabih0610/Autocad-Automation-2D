"""A changeset must never take a drawing permanently out of service.

`apply` refuses to touch a drawing that already has a changeset in
'applying', 'pending', 'error' or 'reverting'. That guard is correct, but it
means any changeset that can no longer be kept or reverted locks its drawing
out of every future edit. Three separate paths used to reach that state, and
the only way out was editing the database by hand.
"""
import shutil
from pathlib import Path

import ezdxf
import pytest

from src.ai import project_planner
from src.cad.changes import ChangeManager, get_change_set
from src.cad.orchestrator import ProjectOrchestrator
from src.cad.scanner import file_hash, scan_project
from src.storage.database import connection
from src.storage.project_repository import register_project
from tests.project.fake_cad import Acad
from tests.project.test_extractor import make_dxf


@pytest.fixture
def applied(tmp_path, monkeypatch):
    """A drawing with one successfully-applied, still-pending changeset."""
    path = tmp_path / "a.dxf"
    make_dxf(path)
    project_id = register_project("Plant", str(tmp_path))
    scan_project(project_id, max_workers=1)

    monkeypatch.setattr(
        project_planner,
        "ask_ai",
        lambda *args, **kwargs: {"command": "RESIZE_COMPONENT", "dimension": "length", "delta_mm": 50},
    )

    manager = ChangeManager(acad=Acad())
    orchestrator = ProjectOrchestrator(manager=manager)
    job = orchestrator.plan(project_id, "increase P-101 by 50mm")
    done = orchestrator.execute(job["job_id"])
    change_id = done["change_set"]["change_set_id"]

    assert get_change_set(change_id)["status"] == "pending"
    return manager, orchestrator, project_id, path, change_id


def _externally_edit(path):
    """Simulate the engineer opening the drawing and saving an unrelated note."""
    doc = ezdxf.readfile(path)
    doc.modelspace().add_text("later note").dxf.insert = (0, 500)
    doc.saveas(path)


def test_keep_succeeds_after_an_unrelated_external_edit(applied):
    """`keep` writes nothing, so a later edit cannot be something it clobbers.

    It used to share `revert`'s freshness check, so saving any unrelated edit
    in AutoCAD made keep AND revert refuse forever."""
    manager, orchestrator, project_id, path, change_id = applied
    _externally_edit(path)

    kept = manager.keep(change_id)
    assert kept["status"] == "kept"

    # And the drawing is usable again afterwards.
    scan_project(project_id, max_workers=1)
    assert orchestrator.plan(project_id, "increase P-101 by 25mm")["items"]


def test_revert_still_refuses_to_overwrite_genuinely_later_work(applied):
    """The safety property this guard exists for must survive the fix."""
    manager, _orchestrator, _project_id, path, change_id = applied
    _externally_edit(path)

    with pytest.raises(ValueError, match="refusing to overwrite later work"):
        manager.revert(change_id)


def test_discard_releases_a_changeset_that_can_no_longer_be_reverted(applied):
    manager, orchestrator, project_id, path, change_id = applied
    _externally_edit(path)
    with pytest.raises(ValueError):
        manager.revert(change_id)

    discarded = manager.discard(change_id)
    assert discarded["status"] == "discarded"

    # The whole point: the drawing is editable again.
    scan_project(project_id, max_workers=1)
    assert orchestrator.plan(project_id, "increase P-101 by 25mm")["items"]

    # Discard leaves the file and its backup alone.
    assert path.exists()
    for item in discarded["files"]:
        assert Path(item["backup_path"]).exists()


def test_discard_is_idempotent(applied):
    manager, _orchestrator, _project_id, _path, change_id = applied
    assert manager.discard(change_id)["status"] == "discarded"
    assert manager.discard(change_id)["status"] == "discarded"


def test_revert_resumes_when_the_file_was_already_restored_in_place(applied):
    """An in-place revert interrupted after `os.replace` leaves the file
    already correct but the changeset stuck at 'reverting'.

    The resume logic only ever covered the RENAME case — it required
    `not current.exists()`, and for an in-place edit the file obviously still
    exists. So the retry compared the (already restored) file against
    `after_hash`, saw a mismatch, and refused forever."""
    manager, orchestrator, project_id, path, change_id = applied

    change = get_change_set(change_id)
    item = change["files"][0]

    # Reproduce the exact on-disk/database state a crash in that window leaves:
    # the backup has been restored over the file, but the changeset still says
    # 'reverting' and still records the post-edit hash.
    shutil.copy2(item["backup_path"], path)
    assert file_hash(path) == item["before_hash"]
    with connection() as conn:
        conn.execute(
            "UPDATE change_sets SET status='reverting' WHERE change_set_id=?", (change_id,)
        )

    reverted = manager.revert(change_id)
    assert reverted["status"] == "reverted"
    assert file_hash(path) == item["before_hash"]

    scan_project(project_id, max_workers=1)
    assert orchestrator.plan(project_id, "increase P-101 by 25mm")["items"]


def test_revert_works_when_apply_was_interrupted_before_recording_after_hash(applied):
    """`after_hash` is written only after `execute_operation` has already
    saved the file, so a hard kill in that window leaves it NULL.

    The old `after_hash or before_hash` fallback then compared the PRE-edit
    hash against the POST-edit file and refused the revert — in exactly the
    situation revert exists for."""
    manager, orchestrator, project_id, path, change_id = applied

    with connection() as conn:
        conn.execute(
            "UPDATE change_set_files SET after_hash=NULL WHERE change_set_id=?", (change_id,)
        )
        conn.execute(
            "UPDATE change_sets SET status='applying' WHERE change_set_id=?", (change_id,)
        )

    before_hash = get_change_set(change_id)["files"][0]["before_hash"]
    reverted = manager.revert(change_id)

    assert reverted["status"] == "reverted"
    assert file_hash(path) == before_hash

    scan_project(project_id, max_workers=1)
    assert orchestrator.plan(project_id, "increase P-101 by 25mm")["items"]

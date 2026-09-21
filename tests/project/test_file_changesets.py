"""Every mutating workflow must be revertible through one mechanism.

The project route already produced a ChangeSet. The older workflows (sketch,
P&ID, CAD3D, place-symbol, autocad/edit) wrote straight to the drawing with no
backup and no undo, which made seven of eight mutating workflows
unrecoverable. They now wrap their write in a file-level changeset: back up,
execute, record the hash, and revert by restoring the backup.
"""
from pathlib import Path

import pytest

from src.api.routes._revertible import run_revertible
from src.cad.changes import ChangeManager, get_change_set
from src.cad.scanner import file_hash
from tests.project.test_extractor import make_dxf


@pytest.fixture
def drawing(tmp_path):
    path = tmp_path / "live.dxf"
    make_dxf(path)
    return path


def _corrupt(path, marker=b"EDITED-BY-THE-WRITE"):
    """Stand in for whatever the executor would have written."""
    path.write_bytes(path.read_bytes() + marker)


def test_revert_restores_the_file_byte_for_byte(drawing):
    original = drawing.read_bytes()
    manager = ChangeManager()

    result, change_id = manager.apply_file_edit(
        [str(drawing)], "sketch write", lambda: (_corrupt(drawing), {"ok": True})[1]
    )

    assert result == {"ok": True}
    assert drawing.read_bytes() != original, "the write did not actually happen"

    reverted = manager.revert(change_id)
    assert reverted["status"] == "reverted"
    assert drawing.read_bytes() == original


def test_keep_leaves_the_written_file_in_place(drawing):
    manager = ChangeManager()
    _, change_id = manager.apply_file_edit(
        [str(drawing)], "sketch write", lambda: (_corrupt(drawing), {"ok": True})[1]
    )
    written = drawing.read_bytes()

    assert manager.keep(change_id)["status"] == "kept"
    assert drawing.read_bytes() == written


def test_reverting_twice_is_rejected_cleanly(drawing):
    manager = ChangeManager()
    _, change_id = manager.apply_file_edit(
        [str(drawing)], "sketch write", lambda: (_corrupt(drawing), {"ok": True})[1]
    )

    assert manager.revert(change_id)["status"] == "reverted"
    # Idempotent, not a crash.
    assert manager.revert(change_id)["status"] == "reverted"


def test_a_failing_write_still_leaves_a_revertible_changeset(drawing):
    """The write may have partially landed before raising, so the changeset
    has to survive — the backup is the only way back."""
    original = drawing.read_bytes()
    manager = ChangeManager()

    def boom():
        _corrupt(drawing)
        raise RuntimeError("executor blew up midway")

    with pytest.raises(RuntimeError, match="blew up"):
        manager.apply_file_edit([str(drawing)], "sketch write", boom)

    with_error = [c for c in _all_change_sets() if c["status"] == "error"]
    assert len(with_error) == 1

    manager.revert(with_error[0]["change_set_id"])
    assert drawing.read_bytes() == original


def _all_change_sets():
    from src.storage.database import connection

    with connection() as conn:
        ids = [row[0] for row in conn.execute("SELECT change_set_id FROM change_sets")]
    return [get_change_set(change_id) for change_id in ids]


def test_a_second_changeset_on_the_same_drawing_is_refused_while_one_is_pending(drawing):
    manager = ChangeManager()
    manager.apply_file_edit([str(drawing)], "first write", lambda: {"ok": True})

    with pytest.raises(ValueError, match="Resolve the existing pending changeset"):
        manager.apply_file_edit([str(drawing)], "second write", lambda: {"ok": True})


def test_backup_is_verified_against_the_pre_edit_file(drawing):
    manager = ChangeManager()
    before = file_hash(drawing)
    _, change_id = manager.apply_file_edit(
        [str(drawing)], "sketch write", lambda: (_corrupt(drawing), {"ok": True})[1]
    )

    item = get_change_set(change_id)["files"][0]
    assert item["before_hash"] == before
    assert file_hash(item["backup_path"]) == before
    assert item["drawing_id"] is None, "a file-level changeset has no indexed drawing"


def test_a_missing_target_cannot_be_backed_up(tmp_path):
    manager = ChangeManager()
    with pytest.raises(ValueError, match="does not exist"):
        manager.apply_file_edit(
            [str(tmp_path / "nope.dxf")], "sketch write", lambda: {"ok": True}
        )


class TestRunRevertible:
    """The route-level wrapper must be explicit about when there is no undo,
    rather than leaving the caller to infer it from a missing field."""

    def test_creates_a_changeset_when_saving_to_an_explicit_target(self, drawing):
        result, change_id, skipped = run_revertible(
            str(drawing), "write", lambda: {"ok": True}, save=True
        )
        assert result == {"ok": True}
        assert change_id and skipped is None

    def test_no_changeset_when_nothing_is_saved(self, drawing):
        _, change_id, skipped = run_revertible(
            str(drawing), "write", lambda: {"ok": True}, save=False
        )
        assert change_id is None
        assert "save=false" in skipped

    def test_no_changeset_without_an_explicit_target(self):
        _, change_id, skipped = run_revertible(
            None, "write", lambda: {"ok": True}, save=True
        )
        assert change_id is None
        assert "target_dwg_path" in skipped

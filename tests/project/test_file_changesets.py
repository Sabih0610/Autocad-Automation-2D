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


def test_repeated_writes_supersede_rather_than_block_the_drawing(drawing):
    """Writing a second sketch into the same drawing is ordinary use.

    Blocking it would put the drawing out of service for exactly the reason
    the stuck-changeset work set out to eliminate — and no page except
    project-chat renders a change_set_id, so there would be no way to resolve
    it. Each write keeps its own backup, so the changesets form an undo chain.
    """
    manager = ChangeManager()
    original = drawing.read_bytes()

    _, first = manager.apply_file_edit(
        [str(drawing)], "first write", lambda: (_corrupt(drawing, b"-A"), {"ok": True})[1]
    )
    after_first = drawing.read_bytes()
    _, second = manager.apply_file_edit(
        [str(drawing)], "second write", lambda: (_corrupt(drawing, b"-B"), {"ok": True})[1]
    )

    assert get_change_set(first)["status"] == "superseded"
    assert get_change_set(second)["status"] == "pending"

    # Reverting the newest returns the drawing to what the previous write left.
    manager.revert(second)
    assert drawing.read_bytes() == after_first
    assert drawing.read_bytes() != original


def test_a_project_changeset_still_blocks_a_file_level_write(drawing, monkeypatch):
    """Only a *file-level* changeset awaiting a decision is superseded. A
    project changeset represents a per-entity edit the user still has to keep
    or revert, and silently discarding that decision would lose real work."""
    from src.storage.database import connection
    from src.cad.scanner import file_hash

    manager = ChangeManager()
    _, existing = manager.apply_file_edit([str(drawing)], "first write", lambda: {"ok": True})

    # Promote it to look like a project changeset (drawing_id set).
    with connection() as conn:
        conn.execute("INSERT INTO projects VALUES ('p1','P','/x','active','t','t')")
        conn.execute(
            "INSERT INTO drawings VALUES ('d1','p1',?,?,?,NULL,NULL,NULL,'scanned',NULL)",
            (str(drawing), drawing.name, file_hash(drawing)),
        )
        conn.execute(
            "UPDATE change_set_files SET drawing_id='d1' WHERE change_set_id=?", (existing,)
        )

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

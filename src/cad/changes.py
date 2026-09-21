"""Durable whole-file changesets; AI-free, explicitly targeted, serialized writes."""
from contextlib import nullcontext
import json
import os
from pathlib import Path
import shutil
from uuid import uuid4

from src.backup import backup_file
from src.cad.scanner import configured_extractor, file_hash, stamp
from src.cad.session import (CAD_LOCK, cad_session, canonical_path, find_open_document,
                             get_document, mark_open)
from src.framework.commands.modification_executor import execute_operation
from src.framework.commands.operation_schema import validate_operation
from src.storage.database import connection
from src.storage.entity_repository import store_snapshot
from src.storage.project_repository import get_project, now


def get_change_set(change_set_id):
    with connection() as conn:
        row = conn.execute("SELECT * FROM change_sets WHERE change_set_id=?", (change_set_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown changeset: {change_set_id}")
        result = dict(row)
        result["items"] = [dict(row) for row in conn.execute("SELECT * FROM change_set_items WHERE change_set_id=?", (change_set_id,))]
        result["files"] = [dict(row) for row in conn.execute("SELECT * FROM change_set_files WHERE change_set_id=?", (change_set_id,))]
        result["validation"] = [dict(row) for row in conn.execute("SELECT * FROM validation_results WHERE change_set_id=?", (change_set_id,))]
    for item in result["items"]:
        item["before_value"] = json.loads(item["before_value"]) if item["before_value"] else None
        item["after_value"] = json.loads(item["after_value"]) if item["after_value"] else None
    return result


def list_change_sets(project_id):
    with connection() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM change_sets WHERE project_id=? ORDER BY created_at DESC", (project_id,))]


def refresh_drawing(drawing_id, path, extractor_factory=configured_extractor):
    signature = stamp(path)
    snapshot = extractor_factory().extract(path)
    digest = file_hash(path)
    if stamp(path) != signature:
        raise ValueError("Drawing changed during post-edit validation")
    with connection() as conn:
        store_snapshot(conn, drawing_id, snapshot)
        conn.execute("""UPDATE drawings SET path=?,filename=?,file_size=?,file_modified_at=?,file_hash=?,
            last_scanned_at=?,scan_status='scanned',scan_error=NULL WHERE drawing_id=?""",
                     (str(path), Path(path).name, *signature, digest, now(), drawing_id))
    return snapshot


class ChangeManager:
    def __init__(self, *, acad=None, extractor_factory=configured_extractor):
        self.acad = acad
        self.extractor_factory = extractor_factory

    def apply(self, project_id, operations, summary, *, on_item=None):
        if not operations or not summary.strip():
            raise ValueError("A changeset needs operations and a summary")
        project = get_project(project_id)
        if project["status"] != "active":
            raise ValueError("Project is archived")
        targets = {}
        for op in operations:
            validate_operation(op)
            path = canonical_path(op["target_dwg_path"])
            if not Path(path).is_relative_to(Path(project["root_path"])):
                raise ValueError("Operation is outside the selected project")
            with connection() as conn:
                row = conn.execute("SELECT * FROM drawings WHERE project_id=? AND path=?", (project_id, path)).fetchone()
            if row is None or row["scan_status"] != "scanned":
                raise ValueError("Target must be scanned in the selected project")
            if file_hash(path) != row["file_hash"]:
                raise ValueError("Drawing changed since scanning; rescan first")
            targets[path] = dict(row)
        # Canonicalized to match `targets`' keys (built via `canonical_path`
        # above) — comparing a raw `op["target_dwg_path"]` string (which may
        # use forward slashes, a different case, or a non-resolved path)
        # against `targets`' canonicalized keys below previously could fail
        # to recognize a rename's own target as one of `targets`, causing
        # `get_document(acad, path)` to run for it with `acad=None` (since a
        # changeset containing only a rename never opens a COM session) and
        # crash with "'NoneType' object has no attribute 'Documents'".
        rename_paths = {canonical_path(op["target_dwg_path"]) for op in operations if op["command"] == "RENAME_FILE"}
        if any(sum(canonical_path(op["target_dwg_path"]) == path for op in operations) != 1 for path in rename_paths):
            raise ValueError("A rename must be the only operation on its file in a changeset")
        has_cad = any(op["command"] != "RENAME_FILE" for op in operations)
        with CAD_LOCK, (cad_session(self.acad) if has_cad else nullcontext(None)) as acad:
            for path in targets:
                if path not in rename_paths and not get_document(acad, path).Saved:
                    raise ValueError("Save or discard existing unsaved edits before applying changes")
            change_id = uuid4().hex
            backups = {}
            with connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                for path in targets:
                    conflict = conn.execute("""SELECT 1 FROM change_set_files f JOIN change_sets c ON c.change_set_id=f.change_set_id
                        WHERE (f.original_path=? OR f.current_path=?) AND c.status IN ('applying','pending','error','reverting')""", (path, path)).fetchone()
                    if conflict:
                        raise ValueError("Resolve the existing pending changeset for this drawing first")
                conn.execute("INSERT INTO change_sets VALUES (?,?,?,'applying',?)", (change_id, project_id, summary, now()))
                for path, row in targets.items():
                    backup = backup_file(Path(path))
                    if file_hash(backup) != row["file_hash"]:
                        raise ValueError("Drawing changed while creating the backup")
                    backups[path] = str(backup)
                    conn.execute("INSERT INTO change_set_files VALUES (?,?,?,?,?,?,NULL,?)",
                                 (change_id, row["drawing_id"], path, path, str(backup), row["file_hash"], int(path not in rename_paths)))
            active_path = None
            try:
                for index, op in enumerate(operations):
                    active_path = canonical_path(op["target_dwg_path"])
                    row = targets[active_path]
                    if on_item:
                        on_item(index, "running", None)
                    result = execute_operation(op, acad=acad, verify_extractor=self.extractor_factory(),
                                               _preexisting_backup_path=backups[active_path],
                                               project_id=project_id)
                    current_path = result["path"]
                    self._record_file(change_id, row["drawing_id"], current_path)
                    with connection() as conn:
                        for change in result["changes"]:
                            entity = conn.execute("SELECT entity_id FROM entities WHERE drawing_id=? AND handle=?",
                                                  (row["drawing_id"], change["handle"])).fetchone()
                            backup = conn.execute("SELECT backup_path FROM change_set_files WHERE change_set_id=? AND drawing_id=?",
                                                  (change_id, row["drawing_id"])).fetchone()[0]
                            conn.execute("INSERT INTO change_set_items VALUES (?,?,?,?,?,?,?,?)", (uuid4().hex, change_id,
                                row["drawing_id"], backup, entity[0] if entity else None, change["field"],
                                json.dumps(change["before"]), json.dumps(change["after"])))
                    refresh_drawing(row["drawing_id"], current_path, self.extractor_factory)
                    if on_item:
                        on_item(index, "done", None)
                self._validation(change_id, True, "Saved files re-extracted; structured operation checks passed")
                with connection() as conn:
                    conn.execute("UPDATE change_sets SET status='pending' WHERE change_set_id=?", (change_id,))
            except Exception as exc:
                # Retain evidence and a usable revert action even after partial writes.
                for path, row in targets.items():
                    with connection() as conn:
                        current = conn.execute("SELECT path FROM drawings WHERE drawing_id=?", (row["drawing_id"],)).fetchone()[0]
                    if Path(current).exists():
                        self._record_file(change_id, row["drawing_id"], current)
                with connection() as conn:
                    conn.execute("UPDATE change_sets SET status='error' WHERE change_set_id=?", (change_id,))
                    for row in targets.values():
                        conn.execute("UPDATE drawings SET scan_status='pending' WHERE drawing_id=?", (row["drawing_id"],))
                self._validation(change_id, False, f"{type(exc).__name__}: {exc}")
                if on_item:
                    on_item(index, "error", str(exc))
            return get_change_set(change_id)

    def apply_file_edit(self, paths, summary, execute):
        """Wrap an arbitrary drawing write in a revertible changeset.

        `apply` models per-entity structured operations against drawings
        indexed in a project. The older workflows (sketch, P&ID, CAD3D,
        vessel, place-symbol, autocad/edit) are additive command batches
        against whatever file the user points at, which is usually in no
        project at all — so they produced no changeset and could not be
        reverted, which is why seven of eight mutating workflows had no undo.

        This covers them at file granularity: back up, run `execute`, record
        the resulting hash. Revert restores the backup. No per-entity detail
        is recorded, deliberately — the goal is that every write can be undone,
        not that every write is introspectable.

        `paths` may be empty (an unsaved/untitled ActiveDocument has nothing to
        back up); `execute` still runs and the result reports that no changeset
        was created, rather than silently pretending one exists.
        """
        if not summary.strip():
            raise ValueError("A changeset needs a summary")

        targets = []
        for raw in paths:
            path = canonical_path(raw)
            if not Path(path).is_file():
                raise ValueError(f"Cannot back up a drawing that does not exist: {path}")
            targets.append(path)

        if not targets:
            return execute(), None

        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for path in targets:
                conflict = conn.execute("""SELECT 1 FROM change_set_files f JOIN change_sets c ON c.change_set_id=f.change_set_id
                    WHERE (f.original_path=? OR f.current_path=?) AND c.status IN ('applying','pending','error','reverting')""", (path, path)).fetchone()
                if conflict:
                    raise ValueError("Resolve the existing pending changeset for this drawing first")
            change_id = uuid4().hex
            conn.execute("INSERT INTO change_sets VALUES (?,?,?,'applying',?)", (change_id, None, summary, now()))
            for path in targets:
                before_hash = file_hash(path)
                backup = backup_file(Path(path))
                if file_hash(backup) != before_hash:
                    raise ValueError("Drawing changed while creating the backup")
                conn.execute("INSERT INTO change_set_files VALUES (?,NULL,?,?,?,?,NULL,1)",
                             (change_id, path, path, str(backup), before_hash))

        try:
            result = execute()
        except Exception as exc:
            # Keep the changeset revertible: the write may have partially
            # landed before raising, and the backup is the only way back.
            for path in targets:
                if Path(path).exists():
                    self._record_file(change_id, None, path)
            with connection() as conn:
                conn.execute("UPDATE change_sets SET status='error' WHERE change_set_id=?", (change_id,))
            self._validation(change_id, False, f"{type(exc).__name__}: {exc}")
            raise

        for path in targets:
            if Path(path).exists():
                self._record_file(change_id, None, path)
        self._validation(change_id, True, "File-level changeset recorded; backup verified against the pre-edit file")
        with connection() as conn:
            conn.execute("UPDATE change_sets SET status='pending' WHERE change_set_id=?", (change_id,))
        return result, change_id

    @staticmethod
    def _record_file(change_id, drawing_id, path):
        with connection() as conn:
            if drawing_id is None:
                # A file-level changeset has no drawing row, so it is keyed by
                # path. Its current_path never moves (only RENAME_FILE moves a
                # file, and that is a project operation), so matching on
                # original_path is stable.
                conn.execute("UPDATE change_set_files SET after_hash=? WHERE change_set_id=? AND original_path=?",
                             (file_hash(path), change_id, canonical_path(path)))
                return
            conn.execute("UPDATE change_set_files SET current_path=?,after_hash=? WHERE change_set_id=? AND drawing_id=?",
                         (path, file_hash(path), change_id, drawing_id))

    @staticmethod
    def _validation(change_id, passed, message):
        with connection() as conn:
            conn.execute("INSERT INTO validation_results VALUES (?,?,?,?,?)", (uuid4().hex, change_id, "saved_file_validation", int(passed), message))

    def keep(self, change_id):
        with CAD_LOCK:
            change = get_change_set(change_id)
            if change["status"] == "kept":
                return change
            if change["status"] != "pending" or not change["validation"] or any(not row["passed"] for row in change["validation"]):
                raise ValueError("Only a successfully validated pending changeset can be kept")
            # Deliberately no file checks. `keep` writes nothing — it only
            # marks the changeset accepted — so it cannot overwrite anyone's
            # work and has nothing to verify. It used to share `revert`'s
            # freshness check, which meant that opening the drawing in AutoCAD
            # and saving any unrelated edit made keep AND revert refuse
            # forever, after which the conflict check in `apply` locked that
            # drawing out of every future changeset with no way back except
            # editing the database by hand.
            with connection() as conn:
                conn.execute("UPDATE change_sets SET status='kept' WHERE change_set_id=?", (change_id,))
            return get_change_set(change_id)

    def discard(self, change_id):
        """Release a changeset without restoring files, so the drawing unblocks.

        `apply` refuses to touch a drawing that has a changeset in
        'applying', 'pending', 'error' or 'reverting'. That is the right
        default — it stops two changesets fighting over one file — but it
        means any changeset that can no longer be kept or reverted takes its
        drawing out of service permanently, and the only way out was editing
        the database by hand.

        This deliberately does NOT touch the filesystem: whatever is on disk
        stays exactly as it is, and the backup is left in place so it can
        still be recovered manually. It only records that the caller has
        decided this changeset is no longer pending a decision.
        """
        with CAD_LOCK:
            change = get_change_set(change_id)
            if change["status"] in {"kept", "reverted", "discarded"}:
                return change
            with connection() as conn:
                conn.execute(
                    "UPDATE change_sets SET status='discarded' WHERE change_set_id=?",
                    (change_id,),
                )
            return get_change_set(change_id)

    @staticmethod
    def _check_files(change):
        for item in change["files"]:
            current = Path(item["current_path"])
            # A revert that already restored `original_path` but failed before
            # removing `current_path` (e.g. a transient PermissionError) is a
            # resumable, expected intermediate state, not damage — `current`
            # simply won't have been touched since that failed attempt, so it
            # still matches `after_hash` unconditionally requiring `current` to
            # exist below would otherwise permanently block a retry.
            resuming_revert = change["status"] == "reverting" and not current.exists()
            # `after_hash` is written only once `execute_operation` has already
            # saved the file, so a NULL here means the process died between the
            # save and the bookkeeping. The file on disk could be either the
            # pre-edit or the post-edit content and there is no way to tell
            # which. Comparing it against `before_hash` — as the old
            # `after_hash or before_hash` fallback did — refused the revert in
            # exactly the case revert exists for, and left the drawing locked
            # out of every future changeset. The backup is integrity-checked
            # just below, so restoring from it returns the file to a known
            # state; that is strictly better than refusing forever.
            interrupted_apply = item["after_hash"] is None
            if not (resuming_revert or interrupted_apply):
                # `before_hash` is accepted as well as `after_hash` because an
                # in-place revert interrupted after `os.replace` leaves the
                # file already correctly restored. Re-running the restore from
                # backup is idempotent, so resuming is safe — whereas the old
                # check saw a "wrong" hash and refused the retry permanently.
                acceptable = {item["after_hash"], item["before_hash"]} - {None}
                if not current.exists() or file_hash(current) not in acceptable:
                    raise ValueError("Drawing changed after this changeset; refusing to overwrite later work")
            if file_hash(item["backup_path"]) != item["before_hash"]:
                raise ValueError("Backup integrity check failed")
            if item["current_path"] != item["original_path"] and Path(item["original_path"]).exists():
                # Distinguish "a genuinely different file appeared here" (a
                # real conflict) from "our own earlier revert attempt already
                # restored this from backup, then failed on the next step" (a
                # resumable retry) — only the former should block reverting.
                # Without this, a revert that partially succeeded (original
                # restored, but removing the renamed file failed) could never
                # be retried: every retry would immediately refuse to proceed
                # because of the very state its own prior attempt left behind.
                if file_hash(item["original_path"]) != item["before_hash"]:
                    raise ValueError("Original rename destination now exists; refusing to overwrite it")
            if not item["uses_cad"] and (current.with_suffix(".dwl").exists() or current.with_suffix(".dwl2").exists()):
                raise ValueError("Close the renamed drawing before deciding this changeset")

    def _close_targets(self, paths):
        if self.acad is None:
            from src.parametric.vessel.dwg_export import AutoCADNotRunningError
        try:
            with cad_session(self.acad) as acad:
                docs = [(path, find_open_document(acad, path)) for path in paths]
                if any(doc is not None and not doc.Saved for _, doc in docs):
                    raise ValueError("A drawing has later unsaved edits; save them separately before reverting")
                for path, doc in docs:
                    if doc is not None:
                        doc.Close(False)
                    mark_open(path, False)
        except Exception as exc:
            if self.acad is None and isinstance(exc, AutoCADNotRunningError):
                for path in paths:
                    mark_open(path, False)
            else:
                raise

    def revert(self, change_id):
        with CAD_LOCK:
            change = get_change_set(change_id)
            if change["status"] == "reverted":
                return change
            if change["status"] not in {"pending", "error", "applying", "reverting"}:
                raise ValueError("This changeset is already finalized")
            self._check_files(change)
            cad_paths = [item["current_path"] for item in change["files"] if item["uses_cad"]]
            if cad_paths:
                self._close_targets(cad_paths)
            self._check_files(change)
            with connection() as conn:
                conn.execute("UPDATE change_sets SET status='reverting' WHERE change_set_id=?", (change_id,))
            for item in change["files"]:
                original, current = Path(item["original_path"]), Path(item["current_path"])
                temporary = original.with_name(f".{original.name}.{uuid4().hex}.restore")
                # Resumable: if a prior revert attempt already restored
                # `original` from the backup but then failed before removing
                # `current` (e.g. a transient PermissionError), a retry must
                # not re-copy the backup over an already-correct `original` —
                # only finish the remaining step. `_check_files` above already
                # verified `original`'s hash matches `before_hash` whenever it
                # exists at this point, so this is safe, not just optimistic.
                already_restored = original.exists() and original != current
                try:
                    if not already_restored:
                        shutil.copy2(item["backup_path"], temporary)
                        os.replace(temporary, original)
                    if current != original and current.exists():
                        current.unlink()
                finally:
                    temporary.unlink(missing_ok=True)
                with connection() as conn:
                    # Keyed on original_path, not drawing_id: a file-level
                    # changeset (from sketch/P&ID/CAD3D/vessel/place-symbol/
                    # autocad-edit) covers a drawing that is not registered in
                    # any project and carries drawing_id NULL, and `WHERE
                    # drawing_id = NULL` never matches anything.
                    conn.execute("UPDATE change_set_files SET current_path=original_path,after_hash=before_hash WHERE change_set_id=? AND original_path=?",
                                 (change_id, item["original_path"]))
                    if item["drawing_id"] is not None:
                        conn.execute("UPDATE drawings SET path=?,filename=?,scan_status='pending' WHERE drawing_id=?",
                                     (str(original), original.name, item["drawing_id"]))
                # Only an indexed drawing has an index entry to refresh.
                if item["drawing_id"] is not None:
                    refresh_drawing(item["drawing_id"], original, self.extractor_factory)
            with connection() as conn:
                conn.execute("UPDATE change_sets SET status='reverted' WHERE change_set_id=?", (change_id,))
            return get_change_set(change_id)

# Module 4: Cross-Cutting Integration Gaps

Three unrelated bugs from `docs_analysis/10_project_extension_review.md`, grouped here only
because each one is a gap *between* two subsystems rather than a bug inside one — an offline
scanner not knowing about a second backups folder, an audit logger not knowing about a newer
route's response shape, and a legacy write path not knowing about the new lock. Fixed in
`src/cad/scanner.py`, `src/api/main.py`, `src/framework/commands/executor.py`, and
`src/framework/commands/edit_executor.py`, with new coverage in `tests/project/test_scanner.py`,
the new `tests/api/test_main_audit_status.py`, and `tests/framework/test_command_executor.py`.

## The bugs

1. **Incomplete backup-folder exclusion.** (Tier 1, item 2.) `src/cad/scanner.py`'s
   file-discovery excluded only the app's own root-level `backups/` folder
   (`src.backup.BACKUP_ROOT`). A second, older, separate `src/backups/` folder with real stale
   `.dwg` files was not excluded, so if a project's root ever included this repo itself, those
   stale backups would get indexed as live project drawings.

2. **Audit-log status misreporting.** (Round 2, verified directly against
   `_status_from_result` in `src/api/main.py`.) The audit middleware's `_status_from_result`
   recognized failure only via a literal `{"ok": False}` key. The newer project/changeset routes
   (`src/api/routes/projects.py`, `src/api/routes/changes.py`) instead return the underlying
   `jobs_multi_file`/`change_sets` database row directly, which signals failure with a
   `{"status": "error"}` field and carries no `"ok"` key at all. A genuinely failed multi-file
   job or changeset execution was silently audit-logged as `status="ok"`.

3. **Write-serialization not actually unified across legacy and new code paths.** (Round 2:
   "The new single-writer lock only serializes the new project/changeset routes against each
   other — legacy sketch/P&ID/CAD3D/title-block writes don't share it...".)
   `src/framework/commands/executor.py` (behind `/api/sketch/approve`, `/api/pid/approve`) and
   `src/framework/commands/edit_executor.py` (behind `/api/autocad/edit`) never acquired
   `CAD_LOCK` at all, while `src/framework/commands/modification_executor.py` and
   `src/cad/changes.py` did. A legacy approval write and a new project/changeset write could
   genuinely interleave their COM calls against the one live AutoCAD session, since only one
   side was ever trying to protect against it.

## The fix

### Bug 1 — `src/cad/scanner.py:62-72` (`scan_project`)

The file-discovery comprehension gained a third filter clause:

```python
and "backups" not in {part.lower() for part in p.resolve().relative_to(root).parts}
```

This excludes any directory literally named "backups" (case-insensitive) found *anywhere* under
the scanned project root, replacing the old single-hardcoded-path check. It is deliberately
scoped to `p.resolve().relative_to(root).parts` — i.e. only the path segments *inside* the
scanned tree — rather than the file's full absolute path. Verified this distinction actually
matters: for a project root at `.../backups/plant` with a live file at
`.../backups/plant/live.dxf`, the full absolute path's parts include `"backups"` (as an
ancestor of `root` itself), which would wrongly exclude every file in the project; `relative_to(root).parts`
for that same file is just `("live.dxf",)`, correctly containing no `"backups"` segment. The
now-unused `from src import backup` import was removed.

### Bug 2 — `src/api/main.py:112-127` (`_status_from_result`)

Added a second check after the pre-existing `ok is False` check:

```python
if isinstance(payload, dict) and payload.get("status") == "error":
    return "error"
```

Only the literal string `"error"` trips this branch. Traced the call chain to confirm the bug
was real and this is the correct fix: `POST /api/projects/jobs/{job_id}/execute` →
`orchestrator().execute(job_id)` → `ProjectOrchestrator._execute` (`src/cad/orchestrator.py:106-132`)
→ returns `get_multi_file_job(job_id)` (line 101/132), which is `dict(row)` from a
`SELECT * FROM jobs_multi_file` query (line 20) — a raw table row with a `status` column and no
`ok` key anywhere. `_execute` sets that column to `'error'` (orchestrator.py:125,129) whenever
the underlying `ChangeManager.apply()` call doesn't come back `"pending"`, *without* raising —
i.e. exactly the silent-failure case the bug describes, a normal return, not an exception. The
same literal `status='error'` shape is used by `src/cad/changes.py:137` for `change_sets`, which
`POST /api/change-sets/{id}/apply|keep|revert` returns via the same route pattern — so the fix
correctly covers both call sites named in the review. The comment block also correctly
enumerates the non-error status values already in use elsewhere in the app's data model
(`pending`, `running`, `done`, `applying`, `kept`, `reverted`, `active`, `scanned`) that must
*not* be misclassified — confirmed these values are real, in use, and none of them is the string
`"error"`.

### Bug 3 — `src/framework/commands/executor.py:13,462` and `edit_executor.py:14,136`

Both `execute_commands` and `execute_edit_plan` were decorated with `@serialized`, imported from
`src.cad.session` (`from src.cad.session import serialized`). `src/cad/session.py:6` re-exports
it unchanged from `src/cad/locks.py`, where it is:

```python
CAD_LOCK = RLock()
def serialized(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with CAD_LOCK:
            return function(*args, **kwargs)
    return wrapped
```

This is the identical decorator already used on `inspect_active_drawing`
(`src/framework/autocad/inspector.py:229`), and the same `CAD_LOCK` instance
`modification_executor.py:210` and `changes.py:82,157,219` take directly. Grepped the whole
`src/` tree for `CAD_LOCK`/`serialized`: the participant list is now `scanner.py` (already
serialized before this fix, for scan-vs-scan safety — unrelated to this bug), `changes.py`,
`modification_executor.py`, `inspector.py`, and, newly, `executor.py` and `edit_executor.py`.
That matches the review's "Round 2" list plus the two files this fix adds.

Because `CAD_LOCK` is a plain `threading.RLock()`, and `execute_edit_plan` internally calls
`execute_commands` (`edit_executor.py:186`) — both now `@serialized` — the same thread
re-acquiring its own already-held lock is safe by definition of `RLock`; no deadlock is
introduced. Confirmed `execute_command_sequence` (`executor.py:543-558`), the schema-validating
wrapper, was deliberately left undecorated: it only calls `validate_command_sequence` and then
delegates to the now-serialized `execute_commands` (line 558) — it does no COM work of its own
first, so wrapping it too would be redundant, not incorrect.

## How each is proven

**Bug 1 — `tests/project/test_scanner.py`:**
- `test_any_backups_subfolder_within_the_project_is_excluded` creates a project root with a live
  `.dxf`, a `backups/2026-01-01/stale.dxf`, and a `nested/backups/also_stale.dxf`, and asserts
  `scan_project` discovers only the one live file. This would have failed before the fix — the
  old code only excluded the app's own `BACKUP_ROOT` path, which isn't inside a temp `tmp_path`
  fixture at all, so both stale files would have been discovered and indexed.
- `test_a_project_root_named_backups_is_not_wrongly_excluded` creates a project root at
  `tmp_path/backups/plant` and asserts its one live file is still discovered. This is the
  regression guard for the `relative_to(root)` scoping decision above: a naive "does `'backups'`
  appear anywhere in the absolute path" check would make this test fail (report `discovered=0`),
  because the ancestor directory is literally named `backups`, even though nothing being scanned
  is actually a backup.

**Bug 2 — `tests/api/test_main_audit_status.py`** (new file — there was previously no test file
for `src/api/main.py`'s helpers at all). Five direct unit tests on `_status_from_result`:
`ok: False` → `"error"`; `ok: True` → `"ok"`; `{"status": "error", ...}` (shaped exactly like the
real `jobs_multi_file`/`change_sets` row) → `"error"`; each of the eight legitimate non-error
`status` values → `"ok"` (this is the test that would have caught an overly broad "any status
key present" fix); and non-dict payloads (`"not a dict"`, `None`) → `"ok"`, unchanged.

**Bug 3 — `tests/framework/test_command_executor.py::test_execute_commands_holds_cad_lock_for_its_whole_duration`.**
It monkeypatches `executor._execute_one_command` to signal a `threading.Event` and then block on
a second one, starts `execute_commands` on a background thread, waits for that signal, and then
asserts a **non-blocking** `CAD_LOCK.acquire(blocking=False)` from the main thread returns
`False` while `execute_commands` is paused mid-call, and `True` again (with a matching
`release()`) once it completes.

Reasoned through whether this genuinely would have failed before the fix: without `@serialized`,
`execute_commands` never touches `CAD_LOCK` at all. The background thread would still reach and
block inside the patched `_execute_one_command`, but nothing would be held. The main thread's
`CAD_LOCK.acquire(blocking=False)` would then succeed immediately (return `True`, not `False`),
so `assert CAD_LOCK.acquire(blocking=False) is False` would raise `AssertionError` — the test
fails exactly because the old code held no lock for another writer to be blocked by. This is a
genuine proof of lock-holding for the call's whole duration, not just an import-time check.

## Verification run

Targeted: `tests/project/test_scanner.py tests/api/test_main_audit_status.py
tests/framework/test_command_executor.py` — **34 passed**, 0 failed.

Full suite: `tests/` — **975 passed, 10 skipped, 0 failed** (119s). Note this number reflects the
current working tree as a whole, which also contains other modules' uncommitted fixes (e.g.
`fixes/01_pid_component_identity.md`'s XData tagging, `fixes/02_schema_contamination.md`,
`fixes/03_save_verification_and_rollback_safety.md`) beyond just this module's three bugs, so the
delta from the review doc's stated baseline (956 passed/10 skipped) is not attributable to Module
4 alone.

## Discrepancies found

One, worth flagging explicitly: `git diff -- src/framework/commands/executor.py` contains **two
unrelated hunks**, not one. Alongside the `@serialized` decorator (Bug 3, this module), the same
file's diff also shows the new `TAG_XDATA_APPID` constant, `_ensure_tag_app_registered`, and
`_apply_entity_tag` — the P&ID component-identity fix, which is a *different* bug ("Round 2"'s
top-priority finding) already fully documented in `fixes/01_pid_component_identity.md`. That
work is out of scope here; it happens to share a file with this module's Bug 3 fix, the same way
`fixes/01_pid_component_identity.md` itself notes an unrelated hunk in `schema.py` belonging to
Module 2. Likewise, `tests/framework/test_command_executor.py`'s diff contains two tests
(`test_line_with_tag_writes_recoverable_xdata`, `test_command_without_tag_writes_no_xdata`) that
belong to that same Module 1 fix, not this one — only
`test_execute_commands_holds_cad_lock_for_its_whole_duration` is Module 4's.

Beyond that, every claim in the implementing agent's description checked out exactly against the
actual code: the scanner's `relative_to(root)` scoping, the exact audit-status literal check and
its non-error allowlist, the `@serialized`/`CAD_LOCK`/`RLock` reentrancy reasoning, and the
deliberate choice to leave `execute_command_sequence` undecorated. No corrections needed.

# Module 5: Medium-Priority Integration Gaps

Seven unrelated bugs from `docs_analysis/10_project_extension_review.md` — grouped here only
because each is a "Tier 2 / medium-priority" gap between two subsystems (project registration vs.
entity lookup, a changeset's own bookkeeping vs. its own paths, this app's session flag vs.
AutoCAD's real lock state, the new engine vs. the legacy engine's COM retry, an explicit empty
input vs. "no input", two concurrent requests vs. shared module globals, and a crashed process vs.
a job it had claimed). Fixed in `src/framework/commands/modification_executor.py`,
`src/cad/changes.py`, `src/api/routes/autocad_edit.py`, `src/api/routes/autocad_inspect.py`,
`src/api/routes/title_block.py`, `src/api/routes/line_list.py`, `src/cad/orchestrator.py`, and
`src/api/main.py`, with new coverage in `tests/project/test_changes.py`,
`tests/project/test_modification.py`, `tests/api/test_autocad_inspect_routes.py`,
`tests/api/test_autocad_edit_routes.py`, the new `tests/api/test_module_settings_lock.py`,
`tests/project/test_orchestrator.py`, and the new `tests/api/test_startup_reconciliation.py`.

## The bugs

1. **Overlapping registered projects broke entity lookup.** (Round 2: "Two registered projects
   with overlapping root folders (parent + child) break edits, because entity lookup during
   modification is global rather than scoped to the selected project.") Registering a parent
   folder and one of its own subfolders as two separate projects, then scanning both, indexes the
   same physical file under two different `drawing_id`s (drawings are keyed by `project_id` +
   `path`). A path+handle lookup with no project scope then matches both rows and always refuses
   to edit ("not uniquely indexed"), even though the caller unambiguously selected one project.

2. **A rename's own path wasn't recognized as covered by itself.** (Round 2: "A forward-slash path
   breaks the filesystem-only rename path with a confusing raw `AttributeError`...".)
   `ChangeManager.apply`'s `rename_paths` set compared the raw, non-canonicalized
   `op["target_dwg_path"]` string against `targets`' canonicalized keys. A path spelled with
   forward slashes (or any other non-canonical spelling) wasn't recognized as matching, so the
   "does this file need a COM session" check ran for it anyway with no session available
   (`acad=None`, since an all-rename changeset never opens one), crashing with
   `AttributeError: 'NoneType' object has no attribute 'Documents'`.

3. **The "is this file open" flag could get stuck forever.** (Round 2: "A rename-in-progress 'is
   this file open' flag has no path to clear itself on a normal external close — only revert
   clears it.") `drawing_sessions.is_open` is only ever cleared by `ChangeManager._close_targets`
   during a revert. A normal successful edit leaves the drawing open in AutoCAD by design, and the
   user closing it directly in AutoCAD (outside this app) has no way to notify the app. Every
   future rename attempt on that file was permanently blocked by a flag with no way to clear.

4. **The new structured modification engine had no COM busy-retry.** (Tier 2, item 10.) Unlike the
   legacy executor's `_com_retry` (`src/parametric/vessel/dwg_export.py`), a transient "AutoCAD
   busy" COM error in `modification_executor.py` aborted the whole operation — triggering a full
   rollback — instead of waiting and retrying.

5. **An explicitly-sent empty `target_dwg_path` was silently treated as "not specified."** (Tier 2,
   item 11.) `autocad_edit.py` and `autocad_inspect.py` both built their options dict with
   `if target_dwg_path else {}`, so an explicit empty string (falsy) fell through to the
   `ActiveDocument` fallback instead of being rejected with a clear error — a narrow violation of
   "never silently fall back to whatever's active."

6. **Concurrent requests to the legacy title-block/line-list routes raced on shared module
   globals.** (Round 2: "Concurrent requests to the pre-existing, unmodified title-block/line-list
   routes can leak each other's parameters through shared module globals...".)
   `_temporary_module_settings` monkey-patches module-level constants on a `use_case` module for
   one request's duration, with no lock — two concurrent requests could observe each other's
   overrides mid-flight, and whichever request's `finally` ran last would restore its own
   originals over the other's still-in-flight state.

7. **A multi-file project job stranded by a process crash could never be retried.** (Tier 2, item
   in the combined "batch together" list; also Round 2: "No crash-recovery/reconciliation for a
   multi-file job if the process itself dies mid-job...".) `ProjectOrchestrator._execute` claims a
   job by flipping `status` from `'pending'` to `'running'` *before* doing any work. If the process
   died right there, the job was stuck at `'running'` forever, since claiming only ever matches
   `status='pending'`.

## The fix

### Bug 1 — `src/framework/commands/modification_executor.py:43-62,239-248`; `src/cad/changes.py:120`

`_indexed_record(path, handle, eid=None, project_id=None)` (line 43) gained an optional
`project_id` parameter. When `project_id is None` the query is unchanged (the original
unscoped `WHERE d.path=? AND e.handle=?`); when given, it adds `AND d.project_id=?` (lines
56-61). `execute_operation` (line 239) gained a matching optional `project_id=None` parameter,
threaded straight through to the one call site of `_indexed_record` (line 247). The only
production caller, `ChangeManager.apply` in `src/cad/changes.py`, now passes its own `project_id`
parameter — the same one the method already receives as its first argument (`changes.py:59`) — at
line 120. Grepped every call site of both functions (production code and every test): the sole
non-test caller of `execute_operation` is `changes.py:120`; every test call (in
`tests/project/test_changes.py`, `test_modification.py`, `test_pid_component_identity.py`) omits
`project_id`, so they keep the original unscoped lookup unchanged. This is genuinely
backward-compatible, not just optional-by-signature.

### Bug 2 — `src/cad/changes.py:86-87`

`rename_paths` and the very next consistency check both now apply `canonical_path()` to every
`op["target_dwg_path"]` before comparing:
```python
rename_paths = {canonical_path(op["target_dwg_path"]) for op in operations if op["command"] == "RENAME_FILE"}
if any(sum(canonical_path(op["target_dwg_path"]) == path for op in operations) != 1 for path in rename_paths):
```
This matches `targets`' keys, which are built the same way at line 68. The actual crash site this
fixes is line 92: `if path not in rename_paths and not get_document(acad, path).Saved:` — `path`
there is always a canonicalized key from `targets`. Before the fix, a rename submitted with a
forward-slash path would have a raw, non-canonical entry in `rename_paths`, so `path not in
rename_paths` would wrongly evaluate `True` for what is actually a pure-rename changeset, and
`get_document(None, path)` would be called (no COM session was opened, since `has_cad` is `False`
when every operation is a rename) and blow up on `.Documents`.

### Bug 3 — `src/framework/commands/modification_executor.py:195-218` (`rename_file`)

```python
lock_files_exist = source.with_suffix(".dwl").exists() or source.with_suffix(".dwl2").exists()
if opened and opened[0] and not lock_files_exist:
    conn.execute("UPDATE drawing_sessions SET is_open=0 WHERE path=?", (str(source),))
    opened = None
if (opened and opened[0]) or lock_files_exist:
    raise ValueError("Close the drawing in AutoCAD before renaming")
```
The reconciliation only fires when the flag says open **and** no `.dwl`/`.dwl2` lock file exists —
treating the lock files' absence as the more reliable, filesystem-level signal than the
possibly-stale database flag. Confirmed the guard is exactly this narrow: if a lock file genuinely
exists, the first `if` never fires (its `not lock_files_exist` condition is `False`), so `opened`
is left alone and the final check still raises via its own `lock_files_exist` term. A genuinely
open drawing is never let through.

### Bug 4 — `src/framework/commands/modification_executor.py:11,31-40,290`

`from src.parametric.vessel.dwg_export import _com_retry` (line 11) — the same helper
`executor.py` (the legacy engine) already uses. `_assign` (line 31), the single point every
property/coordinate assignment in this module goes through, forward and rollback alike, now
wraps its `setattr` in `_com_retry(lambda: setattr(...), f"assigning {change.property}")` (line
40). The final `doc.Save()` call (line 290) got the identical treatment:
`_com_retry(lambda: doc.Save(), "saving document")`.

Verified `_com_retry`/`_is_busy_error` (`src/parametric/vessel/dwg_export.py:36-73`) do **not**
misclassify this module's own validation errors as retryable: `_is_busy_error` returns `True` only
for a `pywintypes.com_error` whose HRESULT is `RPC_E_CALL_REJECTED` or
`RPC_E_SERVERCALL_RETRYLATER`, or for a plain `AttributeError` — never for `RuntimeError` or
`ValueError`, which is what this module's own validation (`"New radius must be positive..."`,
`"AutoCAD did not retain..."`, etc.) raises throughout. `_com_retry`'s loop does
`if not _is_busy_error(exc): raise` before ever sleeping or retrying, so a `ValueError`/`RuntimeError`
propagates on the very first attempt, with no delay — confirmed by reading the function directly,
not inferred.

### Bug 5 — `src/api/routes/autocad_edit.py:43`; `src/api/routes/autocad_inspect.py:31`

Both changed
`options = {"target_dwg_path": target_dwg_path} if target_dwg_path else {}`
to
`options = {"target_dwg_path": target_dwg_path} if target_dwg_path is not None else {}`.
An empty string is now forwarded into `inspect_active_drawing(**options)` rather than dropped, and
gets rejected downstream by `canonical_path`'s existing "An explicit absolute drawing path is
required" check (confirmed this is the real downstream error text, matched by both new tests).

### Bug 6 — `src/api/routes/title_block.py:1,22,30`; `src/api/routes/line_list.py:1,22,30`

Both files gained `import threading` and a module-level `_SETTINGS_LOCK = threading.Lock()`, and
`_temporary_module_settings`'s entire body (monkey-patch the module attributes → `yield` → restore
in `finally`) is now wrapped in `with _SETTINGS_LOCK:`. These are **two separate, independently
constructed `Lock()` instances** — one per file — not a shared lock; confirmed by reading both
diffs side by side, each declares its own `_SETTINGS_LOCK = threading.Lock()`. That's correct for
this bug: each route only ever races against concurrent requests to *itself* (both call sites
patch a different `use_case` module — line-list's own use case vs. title-block's own), so a
per-file lock is sufficient and doesn't over-serialize two unrelated routes against each other.

### Bug 7 — `src/cad/orchestrator.py:18-45`; `src/api/main.py:1,62-80`

New function `reconcile_interrupted_jobs()` (`orchestrator.py:18`): selects every
`jobs_multi_file` row with `status='running'`, and for each one sets that job's own `status` to
`'error'` and every one of its `job_items` still `pending`/`running` to `status='error'` with
`error="Interrupted by a process restart; create a new plan and retry"`; returns the list of
recovered job IDs.

Wiring, `src/api/main.py`: a new `@asynccontextmanager async def _lifespan(_app: FastAPI):`
(line 62) that locally imports and calls `reconcile_interrupted_jobs()` once, then `yield`s.
`app = FastAPI(...)` (line 77) passes `lifespan=_lifespan` (line 80) directly in the constructor
call — not a decorator applied after the fact. Grepped the whole `src/` tree for `on_event`: zero
matches, confirmed no leftover `@app.on_event("startup")` usage anywhere, old or new.

## How each is proven

**Bug 1 — `tests/project/test_changes.py::test_overlapping_project_roots_do_not_block_editing`.**
Registers a parent project at `tmp_path/plant` and a child project at
`tmp_path/plant/unit_a` over the same physical file, scans both, then calls
`ChangeManager(acad=Acad()).apply(child_project, [resize(...)], ...)` and asserts
`status == "pending"`. Traced why this fails pre-fix: scanning both projects inserts two separate
`drawings` rows (one per `project_id`) for the same path, and therefore two separate `entities`
rows for the same handle once scanned. `_indexed_record`'s old unscoped
`WHERE d.path=? AND e.handle=?` join would return both rows (`len(rows) != 1`), raising "Entity
must be uniquely indexed before editing" instead of applying the resize. Genuine regression test.

**Bug 2 — `tests/project/test_changes.py::test_rename_with_forward_slash_path_does_not_crash`.**
Applies a `RENAME_FILE` operation whose `target_dwg_path` is `path.as_posix()` (forward slashes)
and asserts the changeset reaches `status == "pending"` and the rename actually happened on disk.
Traced why this fails pre-fix, using the real control flow at `changes.py:90-93`: with an
all-rename changeset, `has_cad` is `False`, so `acad` is bound to `None` via
`nullcontext(None)`. The loop `for path in targets: if path not in rename_paths and not
get_document(acad, path).Saved:` iterates `targets`' canonicalized key, which will never
string-equal the raw posix-slash entry the old code put in `rename_paths` — so `path not in
rename_paths` is wrongly `True`, and `get_document(None, path)` is called, raising
`AttributeError: 'NoneType' object has no attribute 'Documents'` instead of running to completion.

**Bug 3 — two tests in `tests/project/test_modification.py`.**
`test_rename_reconciles_stale_open_flag_when_no_lock_file_exists` calls `mark_open(str(path),
True)` with no `.dwl`/`.dwl2` file present, then asserts `execute_operation` on a `RENAME_FILE`
op *succeeds* (renames the file on disk). Pre-fix, the old condition was simply `(opened and
opened[0]) or ...` with no reconciliation step at all, so this would unconditionally raise
`ValueError("Close the drawing in AutoCAD before renaming")` — a genuine regression test for the
"stuck forever" bug. The companion, renamed test
`test_rename_is_filesystem_only_and_rejects_genuinely_open_file` (was
`test_rename_is_filesystem_only_and_rejects_open_file`) now additionally writes a real `path.with_suffix(".dwl")`
file before asserting the rename is rejected, and removes it before asserting the retry succeeds.
This is a legitimate correction, not a weakened test: the old version was asserting that
`is_open=True` **alone**, with no corroborating lock file, should always block — which is
precisely the assumption bug 3 is about. The rewritten test now asserts the more correct invariant
("open" must be corroborated by a real lock file to actually block a rename), while still proving
a *genuinely* open file (real `.dwl` present) is correctly rejected. Both tests pass with the fix
in place and I confirmed by re-reading the exact reconciliation condition (bug 3's fix section
above) that a genuine lock file is never bypassed.

**Bug 4 — `tests/project/test_modification.py::test_transient_com_busy_error_is_retried_not_fatal`.**
Monkeypatches `fake_cad.Entity.__setattr__` so the *first* attempt to set `EndPoint` raises
`AttributeError("simulated transient AutoCAD-busy error")` and every subsequent attempt succeeds,
then performs a resize and asserts `state["end_point_attempts"] == 2` and the change actually
applied. Pre-fix, `_assign` called `setattr` directly with no retry wrapper, so the injected
`AttributeError` on the first attempt would propagate immediately, triggering the full rollback
path instead of a second, successful attempt — the assertion on `attempts == 2` would never be
reached. The task noted the implementing agent already hand-verified this one by reverting the fix
and reruning; I did not repeat that experiment, but independently confirmed by re-reading
`_is_busy_error` that a plain `AttributeError` is in fact treated as retryable (see bug 4's fix
section above), which is exactly what this test's injected fault relies on.

**Bug 5 — one test per route.**
`tests/api/test_autocad_edit_routes.py::test_empty_target_dwg_path_is_not_silently_dropped` posts
`target_dwg_path=""` and asserts the captured `inspection_target == ""`. Pre-fix, `"" if "" else
{}` evaluates the falsy branch, so `options` would be `{}` and the captured target would be
whatever the fallback path used (not `""`) — the assertion would fail.
`tests/api/test_autocad_inspect_routes.py::test_empty_target_dwg_path_is_not_silently_dropped` GETs
`?target_dwg_path=` and asserts both that the fake inspector actually received
`target_dwg_path == ""` and that this produces a `500` with `"absolute drawing path is required"`
in the response (the fake inspector explicitly raises that `ValueError` when it receives `""`).
Pre-fix, the empty string would never reach the fake inspector at all — `captured.get(...)` would
be `None`, and the response would be a normal `200`, not the expected `500`. Both are genuine
regression tests.

**Bug 6 — the new `tests/api/test_module_settings_lock.py`, both tests, parametrized over
`title_block_routes` and `line_list_routes`.**
`test_settings_lock_is_held_for_the_whole_override_duration` starts a background thread that
enters `_temporary_module_settings(...)` and blocks (via a `threading.Event`) while still inside
the `with`, then asserts a **non-blocking** `lock.acquire(blocking=False)` from the main thread
returns `False` while the background thread is paused mid-override, and `True` again once it
finishes (with the module's real value confirmed restored). Pre-fix, `_temporary_module_settings`
never touched any lock, so the main thread's non-blocking acquire would immediately succeed
(`True`, not `False`) — the `is False` assertion would fail. The task noted the implementing agent
already hand-verified this exact scenario (for the `title_block` parametrization) by reverting the
fix; I did not repeat that, but the same reasoning applies identically to the `line_list`
parametrization, which uses the identical code shape. `test_settings_are_restored_even_when_the_wrapped_call_raises`
confirms the `finally`-based restore still runs when the wrapped call raises — this passes both
before and after the fix (the lock doesn't change `finally` semantics), so on its own it wouldn't
catch a missing lock; it is a correctness/regression guard for the lock's own implementation
(that wrapping the body in `with _SETTINGS_LOCK:` didn't accidentally swallow the exception or skip
the restore), not proof the lock exists.

**Bug 7 — two tests.**
`tests/project/test_orchestrator.py::test_reconcile_recovers_a_job_stranded_by_a_process_crash`
plans a real job, then directly UPDATEs `jobs_multi_file`/`job_items` to `status='running'` to
simulate "claimed, but the process died before doing any work" — the exact state `_execute` leaves
behind on a crash. It confirms `orchestrator.execute(job_id)` on this stuck job raises
`ValueError` matching `"already executing"` (i.e., genuinely stuck, not silently resumable), then
calls `reconcile_interrupted_jobs()` and asserts the job ID comes back in the recovered list, the
job and all its items are now `status == "error"` with the "Interrupted by a process restart..."
message, and a separate, genuinely-`pending` job (never claimed) is left untouched by a second
`reconcile_interrupted_jobs()` call. This directly exercises the described bug: without
`reconcile_interrupted_jobs` existing at all, there would be no way to un-stick this job, and the
test's own import of the function would `ImportError`. `tests/api/test_startup_reconciliation.py::test_app_startup_calls_reconcile_interrupted_jobs`
monkeypatches `src.cad.orchestrator.reconcile_interrupted_jobs` and asserts it's actually called
when `TestClient(main_module.app)` is used **as a context manager**. I confirmed the
"context-manager vs. bare call" distinction is real: FastAPI/Starlette's `TestClient` only runs
`lifespan` startup/shutdown handlers when entered via `with TestClient(app):` (it uses the ASGI
lifespan protocol under the hood, which only activates on `__enter__`); a bare `TestClient(app)`
constructor call does not trigger `_lifespan` at all. Pre-fix (no `lifespan=_lifespan` wired into
the `FastAPI(...)` constructor), this test's `calls` list would stay empty and the final assertion
would fail.

## Verification run

Targeted:
```
pytest tests/project/test_changes.py tests/project/test_modification.py \
       tests/api/test_autocad_inspect_routes.py tests/api/test_autocad_edit_routes.py \
       tests/api/test_module_settings_lock.py tests/project/test_orchestrator.py \
       tests/api/test_startup_reconciliation.py -q
  → 77 passed, 7 warnings in 23.69s
```

Full suite:
```
pytest tests/ -q
  → 989 passed, 10 skipped, 0 failed, 29 warnings in 119.55s
```
(The review document's own baseline before this round of work was 956 passed/10 skipped; 989
reflects new tests added across *all* modules being fixed in this pass — including
`fixes/01`-`04` — not just this module's seven bugs.) No `DeprecationWarning` about `on_event` or
anything else related to the `lifespan` wiring appeared anywhere in the run.

## Discrepancies found

None of substance — every claim in the implementing agent's description checked out exactly
against the actual diffs and current code: `execute_operation`'s `project_id` is genuinely
optional and backward-compatible (only one production caller, all test callers unaffected); the
`rename_file` reconciliation condition is exactly as narrow as described and correctly leaves a
genuinely-locked file blocked; `_is_busy_error` does not treat `RuntimeError`/`ValueError` as
retryable, so this module's own validation errors fail fast with no retry delay; the `lifespan`
context manager is passed directly to the `FastAPI(...)` constructor with no leftover
`@app.on_event` anywhere in the tree; and the two `_SETTINGS_LOCK`s are confirmed separate,
independently-constructed `Lock()` instances, one per route module.

One scoping note, worth flagging so the raw `git diff` output isn't mistaken for belonging
entirely to this module: `src/framework/commands/modification_executor.py`'s and
`src/cad/changes.py`'s diffs each contain substantially more than these seven bugs' worth of
changes — the `Normal`-vector floating-point tolerance, the `Layer`/`Linetype` case-insensitive
verification, the rollback-during-rollback exception safety, the `SET_ENTITY_PROPERTY`
save-re-verification, and the resumable-revert (`resuming_revert`/`already_restored`) logic are
all real, but they belong to Tier 1 items 3-5 and the related Round 2 findings, already fully
documented in `fixes/03_save_verification_and_rollback_safety.md`. Likewise, `src/api/main.py`'s
diff also contains the `_status_from_result` audit-log fix, documented in
`fixes/04_cross_cutting_integration_gaps.md`. I did not re-document any of that here; this record
covers only the seven bugs listed above.

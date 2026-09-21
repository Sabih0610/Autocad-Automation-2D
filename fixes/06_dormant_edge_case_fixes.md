# Module 6: Dormant Edge-Case Fixes

Four unrelated bugs, grouped here only because each is rare/hard to trigger in normal use but real
once you construct the triggering condition: a `VACUUM` that never runs today but is legal SQLite
behavior against this schema, a worker-process crash mid-scan, an asymmetry between two sibling
validation branches in one `plan()` method, and an in-memory cache with no expiry. Fixed in
`src/storage/spatial.py`, `src/cad/scanner.py`, `src/cad/orchestrator.py`,
`src/api/routes/pid.py`, and `src/api/routes/cad3d.py`, with new coverage in
`tests/project/test_spatial.py`, `tests/project/test_scanner.py`, `tests/project/test_orchestrator.py`,
`tests/api/test_pid_routes.py`, and `tests/api/test_cad3d_routes.py`.

## The bugs

1. **A `VACUUM` can silently desynchronize the R*Tree spatial index from the entities it points
   at.** `entities.entity_id` is a `TEXT PRIMARY KEY`, so the table has no `INTEGER PRIMARY KEY`
   alias and SQLite keeps an implicit, separate `rowid`. The `spatial_index` R*Tree virtual table
   stores that `rowid` as its own `id` (`ensure_spatial`'s triggers all do
   `INSERT OR REPLACE INTO spatial_index SELECT e.rowid, ...`). Per SQLite's own documentation, a
   table shaped like this can have its rowids renumbered by `VACUUM`. If that ever happens, every
   `id` already stored in `spatial_index` keeps pointing at whatever entity now happens to hold
   that old rowid — wrong nearby-entity results, with no error raised anywhere.

2. **A worker-process crash during a parallel scan lost track of already-succeeded files.** The
   original parallel-scan block called `future.result()` inside `as_completed()` for every
   submitted file. If a worker process died outright (not a normal exception raised *inside* the
   extraction function, but the process itself crashing), every other still-pending future in that
   same broken pool also raises `BrokenProcessPool` when `.result()` is called — even for files
   that were never actually touched by the crash. Left unhandled, this marked every other pending
   file as errored too: collateral damage for files that were both innocent and, in the multi-file
   case, potentially already extracted in an earlier completed future.

3. **Radius resizing had no plan-time positivity/finiteness check, unlike length resizing.**
   `ProjectOrchestrator.plan()` validates a length resize's `after` value (`after <= 0` raises) at
   plan time, before any `jobs_multi_file`/`job_items` row exists. Radius resizing had no
   equivalent branch — an invalid radius (for example a large negative `delta_mm` driving the
   result negative, or non-finite) was only ever caught later, at *execute* time, inside
   `modification_executor.py`'s resize handler. Because a multi-file job's items execute
   sequentially and persist to real DWG files as they go, this meant sibling job items could
   already have been written to disk before the invalid radius item failed — plan-time and
   execute-time validation were asymmetric for no principled reason.

4. **P&ID and CAD3D approval tokens were replayable indefinitely.** `_PID_CACHE` and `_CAD3D_CACHE`
   are plain in-memory dicts that never expire or remove entries on their own. Once a token existed
   (from `/generate`), calling `/approve` with it re-executed the same P&ID/3D scene into AutoCAD —
   and calling `/approve` again with the *same* token re-executed it again, with no bound on how
   many times.

## The fix

### Bug 1 — `src/storage/spatial.py:13-37`

New function `rebuild_spatial_index(conn)`: if `spatial_index` exists, it `DELETE`s every row from
it and re-`INSERT`s from a fresh join of `entities`/`entity_geometry` (the same
`e.rowid, g.min_x, g.max_x, g.min_y, g.max_y, g.min_z, g.max_z` shape the creation triggers use),
which forces every `id` back to the entity's *current* rowid. It then unconditionally runs
`UPDATE spatial_version SET version=version+1 WHERE id=1`.

I traced what that version bump actually does, since it's easy to overstate: `SpatialIndex`'s
non-R*Tree (`cKDTree`) fallback path (`spatial.py:111-122`) keys its in-memory cache on
`(db path, spatial_version, drawing_id, layout)` and rebuilds straight from `entities`/
`entity_geometry` whenever that key changes — never from `spatial_index` or a cached rowid. So the
cKDTree path was never actually vulnerable to rowid renumbering in the first place; the version
bump here only forces any already-constructed `SpatialIndex` instance to drop its stale in-memory
cache, which is a correctness nicety (make sure a long-lived process re-reads current geometry)
rather than a fix for the rowid bug itself. The rowid bug is specifically an R*Tree-path problem,
and the `DELETE`+`INSERT` against `spatial_index` is what actually fixes it.

**Caveat, answered explicitly rather than left open:** I grepped the entire repository (not just
`src/`) for `rebuild_spatial_index` and it appears in exactly two places — its own definition in
`spatial.py` and the one test in `tests/project/test_spatial.py`. It is **not called from any
production code path**: not after a `VACUUM` (nothing in this codebase calls `VACUUM` at all, which
the function's own docstring says explicitly), not at startup, not from any maintenance/admin
route. This is a callable repair tool for an operator (or future code) to invoke manually or after
adding a `VACUUM` call somewhere — it does not provide any automatic, standing protection against
the bug it describes. The doc should not be read as claiming otherwise.

### Bug 2 — `src/cad/scanner.py:1-3,53-54,126-167`

`from concurrent.futures.process import BrokenProcessPool` (line 3) and a new
`pool_factory=ProcessPoolExecutor` keyword parameter on `scan_project` (line 54), added purely so
tests can inject a fake pool. The parallel-scan branch (`elif pending:`, line 126) was rewritten
around a `remaining = list(pending)` / `while remaining:` retry loop (lines 136-167):

- Each iteration creates a fresh pool via `pool_factory(max_workers=workers)`, submits every item
  still in `remaining`, and iterates `as_completed(futures)`.
- A normal exception raised *inside* `_extract_file` for one file is caught right there and
  recorded via `complete(item, error=exc)` — unrelated files are untouched.
- If `future.result()` itself raises `BrokenProcessPool`, that's re-raised out of the inner
  `try`/`except` (line 149-150: `except BrokenProcessPool: raise`) to the outer `except
  BrokenProcessPool as exc:` (line 157), which recomputes `remaining` as `[item for item in
  remaining if item not in finished_this_round]` — i.e. only the files that never got a
  result in this round are retried in the *next* fresh pool; anything already completed in
  `finished_this_round` (success or a normal per-file error) during the same round before the
  crash was noticed is not re-submitted.
- A `restarts` counter increments on every `BrokenProcessPool` catch, capped by `max_restarts =
  len(pending)` (line 138). If `restarts > max_restarts`, the safety valve fires (lines 160-165):
  every file still in `remaining` is marked failed via `complete(item, error=RuntimeError(f"Worker
  process crashed repeatedly: {exc}"))`, and `remaining` is cleared, ending the `while` loop.

**Verify point, answered:** exceeding the safety valve does **not** raise an exception out of
`scan_project` and does **not** silently drop the files either — it converts each still-unfinished
file into a normal per-file entry in `report["errors"]` (via the same `complete()`/`_record_error`
path every other extraction failure uses) and lets `scan_project` return its report normally. The
caller sees those specific files failed with a clear message; the function itself doesn't crash and
doesn't retry forever.

### Bug 3 — `src/cad/orchestrator.py:128-141` (`ProjectOrchestrator.plan`)

New `elif op["command"] == "RESIZE_COMPONENT" and op["dimension"] == "radius":` branch, sitting
right next to the pre-existing `length` branch (lines 120-127) it's meant to mirror:

```python
if record["entity_type"] not in {"CIRCLE", "ARC"}:
    raise ValueError("Radius resize requires a CIRCLE or ARC; choose a supported entity")
before = (record["max_x"] - record["min_x"]) / 2 / from_mm(1, record["units"])
after = op.get("value_mm", before + op.get("delta_mm", 0))
if not math.isfinite(after) or after <= 0:
    raise ValueError("Planned radius must be positive and finite")
preview = dict(field="radius_mm", before=before, after=after)
```

This runs inside the `for record in records:` loop that builds `operations`, entirely before the
`INSERT INTO jobs_multi_file` / `INSERT INTO job_items` calls further down in the same method — so
a rejected radius genuinely never reaches the database, matching the length branch's existing
plan-time-vs-execute-time symmetry.

**Verify point on the `before` proxy, answered rather than left open — and a real discrepancy
found.** The task asked me to compare this bounding-box-derived `before` against how
`modification_executor.py`'s resize handler computes the current radius. It computes it very
differently: `modification_executor.py:133-135` requires `entity.ObjectName in {"AcDbCircle",
"AcDbArc"}` and then does `before = float(entity.Radius)` — reading AutoCAD's own `Radius` COM
property directly off the live entity, for both CIRCLE and ARC alike.

`plan()`'s proxy instead uses `(max_x - min_x) / 2`, where `max_x`/`min_x` come from
`entity_geometry`, which is populated by `ezdxf.bbox.extents([entity])` in
`src/cad/extractor/dxf_extractor.py:85-87` — the actual rendered bounding box of the entity as
stored in DXF, not its full circle's bounding box.

- **For a CIRCLE**, these agree: a full circle's bounding box in its own plane is exactly
  `2*radius` wide, so `(max_x - min_x) / 2 == radius` (confirmed by the one test that exercises
  this branch, which uses a CIRCLE — see below).
- **For an ARC**, these can disagree, and I did not find any test that exercises this: an arc's
  bounding box only spans the *visible arc segment*, not the full circle it's part of. A 90-degree
  arc, for example, has an x-extent of only one radius, not two — `(max_x - min_x) / 2` would
  compute half the true radius, not the true radius, unless the arc happens to sweep through both
  the leftmost and rightmost points of its circle. `modification_executor.py`'s `entity.Radius` is
  unaffected by this — an ARC's COM `Radius` property is always its true radius regardless of
  angular span.

The practical consequence: for an ARC, `plan()`'s `before`/`after` preview values (and therefore
what `after` the plan-time positivity/finiteness check is actually validating) can be a different
number from what `modification_executor.py` will validate and apply at execute time. This doesn't
reopen the persisted-before-failure bug this fix targets — a *rejection* at plan time still
prevents a job row from ever being created — but it means the plan-time check could, in principle,
pass or fail on a slightly different quantity than the execute-time check would for the same ARC,
and the preview shown to a caller for an ARC resize could be inaccurate. This is a genuine,
unresolved discrepancy in the fix as written, not something I'm correcting here — flagging it as
requested.

### Bug 4 — `src/api/routes/pid.py:128-137`; `src/api/routes/cad3d.py:461,490-496`

`pid.py`'s `pid_approve`: `ok = bool(execution_result.get("ok"))` (line 128); `if ok:
_PID_CACHE.pop(request.token, None)` (lines 129-137, with an inline comment explaining the
rationale). A failed execution (`ok=False`) leaves the cache entry alone.

`cad3d.py`'s `cad3d_approve` computes `scene_status = "approved" if result.get("ok") else
"failed"` (line 461) and builds `response["ok"] = bool(result.get("ok"))` (line 474), then at the
very end: `if response["ok"]: _CAD3D_CACHE.pop(request.token, None)` (lines 490-496). Same
success-only consumption, same rationale in the inline comment.

**Retry-on-failure convention claim, checked against both routes named, not just asserted:**

- `src/api/routes/sketch.py`'s `sketch_approve` (lines 383-427) does exactly the same thing:
  `if execution_result.get("ok"): _token_cache.pop(request.token, None)` (lines 421-422) — token
  kept on failure, popped only on success. This part of the claim is confirmed.
- `src/api/routes/autocad_edit.py`'s `/api/autocad/edit` route, however, has **no token cache at
  all** — I read the whole file. It's a single-shot "inspect, generate an edit plan, optionally
  auto-execute" endpoint with no `/generate` + `/approve` split and nothing resembling a
  consume-on-success cache to compare against. The claim that bug 4's fix "matches
  `/api/autocad/edit`'s... existing retry-on-failure convention" doesn't hold in any literal sense —
  there's no analogous mechanism there to match. I'm flagging this as a discrepancy in the original
  description rather than silently dropping the comparison: the `/api/sketch/approve` half of the
  claim is real and confirmed; the `/api/autocad/edit` half does not apply.

## How each is proven

**Bug 1 — `tests/project/test_spatial.py::test_rebuild_spatial_index_repairs_stale_rowid_mapping`
(lines 80-115).** Scans a real drawing, finds the indexed entity's real `rowid`, then directly
`UPDATE`s `spatial_index SET id=? WHERE id=?` to move that entity's row to `real_rowid + 1000` — a
value no entity actually holds — simulating exactly the "VACUUM renumbered rowids out from under an
already-populated index" scenario. It asserts the entity's own `entity_id` is now *absent* from its
own `nearby()` results (proving the staleness is real and observable, not merely theoretical), then
calls `rebuild_spatial_index(conn)` and asserts `nearby()` finds results again and that
`spatial_index` now has a row keyed at the real rowid again. This is a genuine simulation of the bug
and a genuine proof the repair works, not just an API-shape check.

**Bug 2 — `tests/project/test_scanner.py::test_broken_process_pool_only_retries_files_never_attempted`
(lines 94-115), using `_CrashesOnceThenSucceedsPool` (lines 12-41).** The fake pool's `submit`
returns a genuine `concurrent.futures.Future` (constructed directly, not duck-typed) — necessary
because `as_completed()` inspects real `Future` internals. Its first constructed instance sets
every submitted future's exception to `BrokenProcessPool("simulated worker crash")`; its second
instance (the retry pool) actually runs the function and sets a real result. The test scans 3 files
with `max_workers=2` and this pool factory, then asserts `report["errors"] == []`,
`report["extracted"] == 3`, and `len(scanner.list_drawings(project)) == 3` — i.e., despite the
simulated crash, every file ends up extracted exactly once, with none reported as collateral-damage
errors. Pre-fix (no retry loop, a bare `future.result()` inside `as_completed`), the first crashed
future would propagate `BrokenProcessPool` straight out of `scan_project`, and none of these
assertions about a clean, complete report would hold.

**Bug 3 — `tests/project/test_orchestrator.py::test_plan_rejects_invalid_radius_before_creating_a_job`
(lines 162-187).** Creates a 10mm-radius CIRCLE tagged `C-101`, scans it, monkeypatches the AI
planner to always return `{"command": "RESIZE_COMPONENT", "dimension": "radius", "delta_mm": -50}`
(which would drive the radius to -40mm), then asserts `orchestrator.plan(...)` raises `ValueError`
matching `"Planned radius must be positive"`, and — critically — that `SELECT count(*) FROM
jobs_multi_file` is still `0` afterward. This directly proves the check runs before any DB write, not
just that it runs at all. Pre-fix, with no radius branch in `plan()` at all, this call would fall
through with no validation, insert a `jobs_multi_file` row and a `job_items` row for the invalid
radius, and only fail later were `.execute()` ever called — the `ValueError` would never be raised
here and the count assertion would fail (it would be `1`, not `0`).

**Bug 4 — one test per route, plus a pre-existing regression check re-verified.**
`tests/api/test_pid_routes.py::test_pid_approve_token_is_consumed_on_success_and_cannot_replay`
(lines 285-299) generates, approves once (asserts `200` and exactly one executor call), then
replays the identical token (asserts `404` and still exactly one executor call — i.e. genuinely not
re-executed). `tests/api/test_cad3d_routes.py::test_cad3d_approve_token_is_consumed_on_success_and_cannot_replay`
(lines 785-799) is the same shape against `/api/cad3d/approve`. Pre-fix, since neither cache ever
expired entries, the replay in both tests would also return `200` and the executor call count would
be `2`, not `1` — both assertions would fail. I also re-ran the pre-existing
`tests/api/test_pid_routes.py::test_pid_approve_autocad_not_running_returns_503` (lines 335-343),
which forces `execute_command_sequence` to raise `AutoCADNotRunningError` and asserts `token in
pid_routes._PID_CACHE` afterward — this still passes with the fix in place, confirming the `if ok:`
guard correctly distinguishes a failed approve (token kept) from a successful one (token popped);
it was not weakened or changed by this fix.

## Verification run

Targeted:
```
venv\Scripts\python.exe -m pytest tests/project/test_spatial.py tests/project/test_scanner.py \
       tests/project/test_orchestrator.py tests/api/test_pid_routes.py tests/api/test_cad3d_routes.py -q
  → 89 passed, 7 warnings in 21.70s
```

Full suite:
```
venv\Scripts\python.exe -m pytest tests/ -q
  → 992 passed, 10 skipped, 0 failed, 29 warnings in 118.06s
```
This matches the expected baseline exactly (992 passed / 10 skipped), confirming no regressions
from this module's changes.

## Discrepancies found

Two, both substantive enough to change how a reader should trust the original description, and
both already folded into their bug's "The fix" section above rather than left as open questions:

1. **Bug 1's "is it actually called automatically" question resolves to "no."**
   `rebuild_spatial_index` exists only as a manually-invokable repair function. It is not wired into
   any startup path, any `VACUUM` call (there is no `VACUUM` call anywhere in this codebase today),
   or any maintenance route. The fix adds the *tool*, not automatic protection — confirmed by
   grepping the entire repository for its only two call sites (its own definition and the test).

2. **Bug 3's two radius computations can genuinely disagree for ARC entities.**
   `plan()`'s bounding-box-derived `before = (max_x - min_x) / 2` and
   `modification_executor.py`'s `before = float(entity.Radius)` agree for a CIRCLE (whose bounding
   box is always exactly `2*radius` wide) but are not guaranteed to agree for an ARC, whose
   bounding box only spans the rendered arc segment rather than its full parent circle. No test in
   this module exercises an ARC through `plan()`'s radius branch — the one test that exists uses a
   CIRCLE, where the proxy happens to be exact. This doesn't undermine the core fix (an invalid
   plan is still rejected before any DB write), but the specific number being validated, and the
   preview shown to the caller, can be wrong for an ARC.

One overstatement, also worth flagging rather than silently correcting: bug 4's description claims
the success-only-consume fix "matches the existing retry-on-failure convention already used by
`/api/autocad/edit` and `/api/sketch/approve`." I confirmed the `/api/sketch/approve` half — it does
the identical `if execution_result.get("ok"): _token_cache.pop(...)` pattern. The
`/api/autocad/edit` half does not hold: that route has no token cache, no `/generate`+`/approve`
split, and nothing analogous to compare against — it's a single-shot endpoint. This looks like the
implementing agent conflated "this general kind of route" with "this specific route," and I'm
noting it rather than quietly dropping the comparison from the record.

# Group A (02eaf45) — adversarial verification

## 1. Verdicts

- **A1 ordering — PARTIAL.** Timestamps sort correctly now, but `get_latest()` still returns the wrong scene by another path.
- **A2 COM fake — PARTIAL.** Units, VARIANT, `Layers` and the dimension projection are correct; three schema-valid commands still crash it, and `Documents.Open` is unfaithful.
- **A3 delegation — HOLDS.** Additions and deletions land in the target on disk; save/backup/zoom happen exactly once.
- **A4 document leaks — PARTIAL.** Common paths right; `opened_here` is inferred rather than observed, and one retry path still leaks.
- **A5 test speed — HOLDS.** Real retry/backoff is still covered and the stub hid nothing (proved empirically).

## 2. Findings

**F1 — A4, HIGH. `opened_here` is inferred from our own lookup, not from AutoCAD.** `src/cad/session.py:48-53`. Real `AcadDocuments.Open` on an already-open drawing returns the *existing* Document. `open_document` instead decides `opened_here` from whether `find_open_document` matched, so any path mismatch `canonical_path`'s `resolve()`+`normcase` cannot unify (mapped drive vs UNC, junction, a `FullName` AutoCAD spells differently) gives `opened_here=True`, and the `finally` calls `doc.Close(False)` — **discarding the user's unsaved work**. Before A4 a lookup miss was merely wasteful; A4 made it destructive. `tests/project/fake_cad.py:271` hides this: its `Documents.Open` always constructs a new `Document` (Count 1→2). Reproduced (`a4c.py`): user's document closed, `ok=True` returned.

**F2 — A4, MEDIUM. The transient-busy retry leaks the document A4 set out to close.** `executor.py:550-556` wraps `open_document` in `_com_retry`, and `_is_busy_error` (`dwg_export.py:46`) treats *any* `AttributeError` as busy. If the error lands after `Documents.Open` succeeded, attempt 2 finds the drawing open → `opened_here=False` → never closed, while the caller sees `ok=True` (`a4b.py` §6). Same shape in the 3D and edit executors.

**F3 — A4, MEDIUM. New database dependency on paths that previously had none.** `open_document` calls `mark_open` unguarded (`session.py:52`). With SQLite failing, `execute_commands` now raises before running a single command *and* leaks the opened document (`a4_probe.py` §4); previously `Documents.Open` never touched the DB. Also untested: a relative `target_dwg_path` now raises `ValueError`, a missing file `FileNotFoundError`.

**F4 — A1, MEDIUM. `get_latest()` still returns the wrong scene.** `scene_store.py:230-233`: `get(token)` sets `_latest_token` to that token whenever it loads from disk. After a restart, one `store.get("<old token>")` makes `get_latest()` return the **old** scene — precisely the `/api/cad3d/edit`-edits-the-wrong-drawing harm the A1 docstring describes, while `list_records()[0]` stays correct (`a1_get.py`). Compounding: `_load_all_records_from_disk` (`:329-333`) recomputes `_latest_token` only when it is `None`, and `delete()`'s `max()` (`:269-276`) spans in-memory records only. Both `max()` calls sort correctly — over the wrong input set.

**F5 — A2, MEDIUM. Three schema-valid command shapes still cannot run against the fake.** `Entity.fields` (`fake_cad.py:11-12`) has no `Rotation`, `StartAngle`, `EndAngle` or `TextOverride`, so `__setattr__` (`:50`) raises `KeyError`. Measured: `TEXT`+`rotation_degrees`, `ELLIPSE`+`start/end_angle_degrees`, `DIM_LINEAR`+`text_override` — all valid per `schema.py:299/319/334`. `test_executor_creation_surface.py` covers only each command's minimal form, so "the entire creation surface" is overstated. (`msp.InsertBlock` is also missing, but `INSERT_BLOCK` is not in `_COMMAND_HANDLERS` — dead code.)

**F6 — A1, LOW.** The guard is per-process (`threading.Lock` + module global): two processes writing in the same tick still produce identical timestamps, and a restart after a huge same-tick burst can emit one sorting below a persisted record (needs 2M calls — unrealistic). Single-process server today.

**F7 — A3, LOW.** `execute_commands_in_document` (`executor.py:513`) is public, **not** `@serialized`, and skips the `commands must be a non-empty list` guard — it accepts `[]`, a `str`, a `dict`. Safe from its one caller (inside `@serialized execute_edit_plan`; `CAD_LOCK` is an `RLock`), but it is an unguarded COM write entry point. Separately `execute_cad3d_scene` has no `@serialized` (pre-existing) yet now *closes* documents, so it can close a drawing a concurrent `execute_commands` is using.

**F8 — process.** Another agent edited this working tree mid-session (8 files, mtimes 21:28–21:31, including `test_file_changesets.py`), so my second suite run reported 1 failure not attributable to Group A.

## 3. What I could not break

- **`@serialized` placement** verified at runtime: `execute_commands` **True**, `execute_edit_plan` **True**. Probing `CAD_LOCK` from a second thread mid-write: held during `execute_commands`, not during `execute_commands_in_document`.
- **A2 units, empirically**: `ezdxf.add_arc` takes **degrees**, COM radians — conversion correct. `add_ellipse(major_axis=…)` **is** relative to centre. `add_aligned_dim`'s sign convention matches the fake's projection, for ±offset and reversed `p1`/`p2`. `Layers.Item` raises `KeyError` (caught by `ensure_layer`), `Add` creates. A real `VARIANT` is not iterable, `.value` unwrap is correct, and nothing the executor passes (str/float/bool/tuple/None) falsely has `.value`.
- **A1 thread safety**: 32 threads × 3000 calls = **96 000 unique** timestamps, 0 duplicates, lexicographic == chronological order. Fixed width 27 chars over 5000 calls; `fromisoformat` parses it. Backwards clock jumps absorbed. The `"12:00:00Z" > "12:00:00.000001Z"` reasoning is correct (`.`=46 < `Z`=90).
- **A3/A4 end to end**, both with the user holding the target open and with the executor opening it: on disk the target has exactly the edited entities, the other drawing none; `save_calls`/backups/zooms each **1**; user-open doc stays open; self-opened doc closes after the save and on the exception path.
- **A5**: `test_transient_com_busy_error_is_retried_not_fatal` survives un-stubbed (`test_modification.py:247`). Reinstalling the real instrumented `_com_retry` over both stubs: **369 calls, 18 ops raised, 0 retried into success** — nothing hidden; 36 tests still pass.
- All 6 `point`→`tuple` stubs gone. **No order dependence** from the new module global: the 8 affected files pass alone and in permuted groupings.

## 4. Suite numbers

- Working tree, clean at session start: **1088 passed, 10 skipped, 0 failed** (80.4s).
- Pristine `git archive 527ec1e` export: **1088 passed, 10 skipped, 0 failed** (79.2s).
- Working tree during third-party edits: 1087 passed, 1 failed (`test_file_changesets.py`) — **invalid, see F8**.

Claimed numbers confirmed. No source or test file was modified; probes lived in the scratchpad.

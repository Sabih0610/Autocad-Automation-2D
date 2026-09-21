# Group A (02eaf45) — regression review

## 1. Overall risk verdict

Mostly sound, with **one blocking data-loss regression**. A1 (timestamps), A3 (targeting) and A5
(retry stubbing) are real fixes with real tests. A4 is the problem: `Close(False)` discards
unsaved changes, and the new `finally` runs it on *every* exit path — including the legitimate,
API-controlled `save=False` path. Work the executor reports as `ok: True` is silently thrown
away. Rework A4 before building on this commit; the rest is manageable.

## 2. Weakened tests

| Test | Used to assert | Now asserts | Lost coverage elsewhere? |
|---|---|---|---|
| `test_edit_executor.py::test_add_only_edit_calls_execute_commands` → `..._targets_the_document_it_opened` | delegate got `target_dwg_path is None`, `save is False`, `zoom_extents is False` | delegate got `doc is fake_doc` | **Legitimate.** `execute_commands_in_document` has no `save`/`zoom_extents` params, so those became unexpressible. Outer behaviour still covered at :312 and :334. The dropped `target_dwg_path is None` was asserting the bug. No real loss. |
| `test_autocad_3d_executor.py::test_target_dwg_path_opens_document` | `opened_paths`, `result["dwg_path"]` | both, **plus** `doc.closed is True` | Stronger. Only cosmetic loss: a `tmp_path` no longer pins `str(Path(...))` normalisation of a forward-slash input. |
| `test_executor_backup_safety.py::test_edit_delete_success_add_failure_is_not_saved` | patched `execute_commands` | patches `execute_commands_in_document` | Rename only; same seam, same assertions, name still accurate. |
| Six `monkeypatch.setattr(engine, "point", tuple)` removals | — | — | **Strengthening.** Real VARIANTs now reach `fake_cad.Entity.__setattr__`, which unwraps `.value`. Verified: `list(VARIANT)` raises `TypeError`. |

## 3. Uncovered behavioural changes

**3a. `save=False` + an executor-opened target silently discards all work — CRITICAL.**
`executor.py:630-633`, `edit_executor.py:276-279`, `autocad_3d_executor.py:751-754` →
`session.py:70` `doc.Close(False)`. Reproduced against the fake:
`execute_commands([CIRCLE], target_dwg_path=p, save=False)` returns `ok=True,
executed_count=1`, the doc closes, and the file on disk has **zero** entities. Reachable in
production: `cad3d.py:374`/`:461` forward `request.save`, `autocad_edit.py:61` forwards `save`.
Same applies with `save=True` and any error — the save is skipped, then the partial state is
discarded instead of being left on screen for the user. No test asserts document or disk
contents after an `opened_here` close.

**3b. A document opened here is leaked when `open_document` fails after `Documents.Open`.**
`session.py:49-52`: Open runs, then `same_path` can raise `ValueError` and `mark_open` can raise
`sqlite3.OperationalError`. Both propagate before the executor's `try`, so `opened_here` is
never set and the `finally` never runs — leaking exactly the document A4 set out to stop
leaking. Scenario: DB locked by a concurrent scan.

**3c. `zoom_extents=True` activates and zooms a document closed microseconds later**
(`executor.py:612` then `:633`), while still reporting `zoom_extents_called: True`. Every route
passes `zoom_extents=True`, so each explicit-target request steals AutoCAD focus for nothing.

**3d. `execute_commands_in_document` (`executor.py:513`) is public but not `@serialized`** and,
unlike `execute_commands`, does not validate `commands`. `CAD_LOCK` is an `RLock` so nothing
deadlocks today, but a caller outside `edit_executor` would write COM with no lock held.

**3e. `_LAST_TIMESTAMP` (`scene_store.py:21`) is process-local and never seeded from disk.**
`_load_all_records_from_disk` does not prime it, so after a restart a new record can get a
timestamp `<=` a persisted one and `get_latest()` regresses. The new test covers reload only
*within* one process.

No exception is masked: both `_safe_close_document` copies and `close_document`'s inner
`mark_open` use bare `except`, and no new early `return` was introduced inside the `try` blocks.

## 4. `mark_open` / database coupling

- **Cost:** ~3 ms per call measured warm (`connection()` re-runs schema DDL, three migrations and
  three `DROP IF EXISTS` every time). Two per explicit-target request ≈ 6 ms — negligible vs COM.
- **DB locked:** `timeout=2.0` (`src/logging/db.py:36`). On open this fails the whole request
  (3b); previously a DB hiccup could not fail an AutoCAD write at all. On close it is swallowed.
- **`rename_file` (`modification_executor.py:201-218`):** a stuck `is_open=1` is **not**
  permanently fatal — the `.dwl`/`.dwl2` reconciliation at :204 clears a stale flag, so a crash
  between open and close self-heals. Conversely `close_document` clears the flag even when
  `doc.Close` raised, briefly claiming a still-open drawing is closed; the lock-file check covers
  that too.
- **Net:** survivable, but it adds a new failure mode to a path that had none, for a flag whose
  only consumer already prefers the filesystem signal.

## 5. Fake-fidelity concerns

1. **`Layers.Add` diverges.** Real `AcadLayers.Add` returns the existing layer for a duplicate;
   `ezdxf.layers.add` raises `DXFTableEntryError` (verified). Not hit via `ensure_layer`, but a trap.
2. **`Entity.__setattr__` raises `KeyError` for anything outside `fields`** — `Rotation`,
   `StartAngle`, `EndAngle`, `TextOverride` are all set by `executor.py`, so those branches still
   cannot be tested, and `_com_retry` would not treat `KeyError` as busy.
3. `hasattr(value, "value")` is a too-broad VARIANT sniff; `tuple(value.value)` would `TypeError`
   on a scalar VARIANT.
4. **`AddPolyline` is unreachable and wrong.** `executor.py:288` takes that branch only when
   `AddLightWeightPolyline` is absent — adding it made the fallback *permanently* dead under this
   fake, the opposite of the docstring's claim. It also maps to `add_polyline3d`; ActiveX
   `AddPolyline` creates an old-style 2D polyline.
5. **`InsertBlock` was not added**, so the INSERT branch (`executor.py:341`) still never runs.
   Both the `ModelSpace` docstring and `test_executor_creation_surface.py`'s "Every
   entity-creation branch" overclaim.
6. `AddMText` is called by nothing in `src/` — dead fake surface.
7. `AddDimAligned`'s third ActiveX argument is `TextPosition`, not a dimension-line point; the
   projection approximates it but the name misleads. `Entity(dim.dimension).ObjectName` raises
   `KeyError` — `"DIMENSION"` is missing from `Entity.names` (verified `dxftype()`).

## 6. Checked and genuinely fine

- No exception swallowing or reordering from the `try/finally` wraps.
- `_com_retry` re-raises non-busy errors immediately, so `FileNotFoundError` from
  `open_document` is not retried into a 5 s stall.
- `CAD_LOCK` is an `RLock`; the old nested `@serialized` call was never a deadlock, and removing
  the nesting is a clean win.
- **Nothing orphaned.** `get_document` is live at `inspector.py:248`, `changes.py:92`,
  `modification_executor.py:251`. `_active_document` is reachable in all three executors via the
  no-target branch. `execute_commands_in_document` has exactly one production caller
  (`edit_executor.py:222`); nothing outside the three executors imports it.
- `mark_open` and `rename_file` agree on path canonicalisation.
- A1 is correct as written: `timespec="microseconds"` is genuinely required for lexicographic
  ordering, and its test freezes the clock rather than racing it.
- `test_edit_executor_targeting.py` is a real end-to-end test of A3 — `ActiveDocument` raises on
  the fake, so a regression fails loudly rather than silently retargeting.

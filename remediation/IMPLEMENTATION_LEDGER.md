# Implementation Ledger — What Is Done, What Is Left

**Verified 2026-09-21.** Every status below was checked against the code, not recalled.
Suite: **1089 passed, 10 skipped, 0 failed** (`venv\Scripts\python.exe -m pytest tests/ -q`).
Baseline before any of this work: 1003 passed.

---

## 1. Status at a glance

| Work | Scope | Status | Commit |
|---|---|---|---|
| Prompts 1–12 | 12 standalone bug fixes | **Done** (by Codex) | `0a0b490` |
| **Group A** | COM fidelity + test infrastructure | **Done**, 1 critical defect found after | `02eaf45` |
| **Group B** | One revert mechanism + explicit targets | **Done**, 3 defects found and fixed | `527ec1e`, `0c495c7` |
| **Group C** | Editing capability | **NOT STARTED** — 0 of 4 items | — |
| **Group D** | Index & API surface | **NOT STARTED** — 0 of 4 items | — |
| Follow-ups | 8 items from adversarial review | **NOT STARTED** | — |

Verified empirically that C and D are untouched:

```
C1  default P&ID template renders 80 commands, 5 tagged, 75 UNTAGGED
C2  0 occurrences of LWPOLYLINE / XScaleFactor / SCALE_ENTITY in the edit engine
C3  CLARIFY dead-end still live at src/ai/project_planner.py:41
C4  0 occurrences of layer-table or SummaryInfo extraction in dxf_extractor.py
D1  src/api/routes/projects.py still has exactly its original 10 routes
D2  0 occurrences of proximity / TEXT-label association in dxf_extractor.py
D3  .env.example ABSENT
D4  AUDIT_ROUTE_MAP still keyed by path only — 0 references to request method
```

---

## 2. Prompts 1–12 — done (`0a0b490`)

33 files, +1300/−91. Implemented by Codex against `remediation/CODEX_PROMPTS.md`.

| # | Fix | Files |
|---|---|---|
| 1 | Backup before mutation; save gated on no errors | `framework/commands/executor.py`, `edit_executor.py`, `framework/cad3d/autocad_3d_executor.py`, `backup.py` |
| 2 | Stored XSS escaped | `api/static/jobs.html` |
| 3 | CAD3D move parser no longer reads the distance from the tag | `ai/cad3d_edit_planner.py` |
| 4 | `AddEllipse` given a relative vector | `framework/commands/executor.py` |
| 5 | P&ID DOWN flow arrow made symmetric | `framework/pid/symbols.py` |
| 6 | NaN/Infinity rejected by validation | `framework/commands/schema.py` |
| 7 | Token caches given a 10-minute TTL | `api/routes/pid.py`, `cad3d.py` |
| 8 | `/api/cad3d/edit` consumes its token | `api/routes/cad3d.py` |
| 9 | Audit rows always closed | `api/main.py` |
| 10 | Output token cap raised; `finish_reason` inspected | `ai/client.py` |
| 11 | Vessel head depth reconciled | `parametric/vessel/{geometry,draw_dimensions,draw_top_view,sheet}.py` |
| 12 | Test DB isolation | `tests/conftest.py`, `tests/api/conftest.py`, `logging/db.py` |

New tests: `test_audit_middleware_completion.py`, `test_jobs_static_xss.py`, `test_ai_client.py`,
`test_executor_backup_safety.py`, `test_backup.py`.

---

## 3. Group A — done (`02eaf45`)

16 files, +957/−294.

| Item | What changed | File |
|---|---|---|
| **A1** | `_utc_now_iso()` now strictly monotonic per process, formatted `timespec="microseconds"`. Bare `isoformat()` omits the fraction when zero, and `"12:00:00Z"` sorts *after* `"12:00:00.000001Z"`. | `framework/cad3d/scene_store.py` |
| **A2** | `ModelSpace` became a COM-shaped collection: `AddLine/AddCircle/AddArc/AddEllipse/AddLightWeightPolyline/AddPolyline/AddText/AddMText/AddDimAligned/Count/Item`, plus a `Layers` collection with `Item`/`Add`. `Entity.__setattr__` unwraps `VARIANT`. `AddArc` converts radians→degrees. | `tests/project/fake_cad.py` |
| **A2** | `monkeypatch.setattr(engine, "point", tuple)` removed from **all 6 sites** — the real VARIANT path is now exercised | `tests/project/test_{changes,modification,orchestrator,pid_component_identity}.py` |
| **A3** | Added `execute_commands_in_document()`; `edit_executor` now passes the document it already opened instead of `target_dwg_path=None` | `framework/commands/executor.py`, `edit_executor.py` |
| **A4** | Added `open_document()` → `(doc, opened_here)` and `close_document()`; all three executors route through them and close in a `finally` | `cad/session.py` + the 3 executors |
| **A5** | `_com_retry` stubbed in the two slowest test modules | `tests/framework/test_autocad_3d_executor.py`, `tests/project/test_pid_component_identity.py` |

New tests: `test_edit_executor_targeting.py` (2), `test_executor_creation_surface.py` (8),
plus a frozen-clock ordering test in `test_cad3d_scene_store.py`.

> **A4 introduced a critical data-loss bug.** See §6 item 1. It is not yet fixed.

---

## 4. Group B — done (`527ec1e` + `0c495c7`)

28 files, +1075/−119 across both commits.

### B1 — ChangeSet stuck-states (`cad/changes.py`)

Three ways a changeset could permanently lock a drawing out of every future edit:

| Bug | Fix |
|---|---|
| `keep` shared `revert`'s freshness check, so saving any unrelated edit in AutoCAD made **both** refuse forever | `keep` writes nothing, so it now checks nothing |
| A hard kill between the COM save and recording `after_hash` left it NULL; the `after_hash or before_hash` fallback then compared the pre-edit hash against the post-edit file | NULL is now an explicit "interrupted apply" that permits revert |
| Resume logic was rename-only, so an in-place revert interrupted after `os.replace` stuck at `reverting` | Revert accepts the file already hashing to `before_hash` |

Added `ChangeManager.discard()` + `POST /api/change-sets/{id}/discard`.

### B2 — file-level changesets

- New `ChangeManager.apply_file_edit(paths, summary, execute)` — back up, execute, record hash.
- New `src/api/routes/_revertible.py` with `run_revertible()`, returning
  `(result, change_set_id, skipped_reason)`.
- `change_set_files.drawing_id` relaxed to nullable, `PRIMARY KEY(change_set_id, original_path)`,
  with migration `src/storage/changeset_schema.py` wired into `database.connection()`.
- **Six routes wired**: sketch approve, P&ID approve, CAD3D approve, CAD3D edit, place-symbol,
  autocad/edit. Each returns `change_set_id` + `change_set_skipped_reason`.
- Repeated writes to one drawing **supersede** the previous pending file-level changeset, forming an
  undo chain. A *project* changeset still blocks.

**Latent bug fixed in passing:** the first-ever `connection()` to a fresh database was handed back
inside `ensure_spatial`'s implicit transaction, so any caller issuing `BEGIN IMMEDIATE` failed.
`ChangeManager.apply` would have hit this too.

### B3 — explicit write targets

`require_explicit_target()` in `_revertible.py`; `use_active_document: bool = False` added to the
sketch, P&ID, CAD3D and place-symbol request models. Rejected **before any COM call**. An explicitly
empty `target_dwg_path` stays distinct from an omitted one, in the guard *and* in all three
executors.

New tests: `test_changeset_recovery.py` (6), `test_file_changesets.py` (12),
`test_explicit_write_target.py` (6).

### Deliberately NOT done in Group B

| | Why |
|---|---|
| **Vessel** not wired | `/api/generate-vessel/confirm` writes a **new** output file rather than editing an existing drawing, so a changeset has nothing to restore. Both reviewers confirmed independently. **Do not "fix" this.** |
| **Title-block** not migrated | Still calls `backup_file` directly at `use_cases/update_title_block.py:139` |
| **No UI** | Six routes return `change_set_id`; nothing outside `project-chat.js` renders a Revert control |

---

## 5. Groups C and D — NOT STARTED

### Group C — editing capability

| Item | What is needed | Primary files |
|---|---|---|
| **C1** | Every shipped P&ID template must tag its `pipe_run` / `gate_valve` / `control_valve` components. Currently the default template renders **80 commands with only 5 tagged**, so the generator produces drawings the editor cannot address. | `framework/pid/component_templates.py`, `component_examples.py`, `components/piping.py`, `components/valves.py`, `scene_renderer.py`, `ai/pid_component_planner.py` |
| **C2** | Expand the editable entity set: LWPOLYLINE/POLYLINE scaling, INSERT via `XScaleFactor/YScaleFactor/ZScaleFactor`, ELLIPSE axes, a generic `SCALE_ENTITY`, RGB/TrueColor. Also fix ARC: plan time uses bbox `(max_x−min_x)/2`, execute time uses `entity.Radius` — they disagree for arcs. | `framework/commands/modification_executor.py` (`_resize`), `cad/orchestrator.py` (`plan`, ~line 120-141), `framework/commands/operation_schema.py`, `ai/project_planner.py` |
| **C3** | "Header color" always returns HTTP 409. Either implement it as a real operation, or make CLARIFY a first-class conversational response the frontend renders as a question. | `ai/project_planner.py:41`, `api/routes/projects.py:26`, `api/static/sketch.html` |
| **C4** | Extract the layer table and document SummaryInfo — currently neither is read, so layer colours and document properties are never queryable **and** are the only operations not re-verified after save. | `cad/extractor/dxf_extractor.py` (`_parse`), `storage/schema.sql`, `framework/commands/modification_executor.py` (post-save verification) |

**C1 must precede C2** — expanding the editable entity set is worth little while the generator emits
untaggable geometry.

### Group D — index & API surface

| Item | What is needed | Primary files |
|---|---|---|
| **D1** | Only two query shapes exist (`?tag=` exact match, `nearby?tag=`). Add list-by-drawing, filter by type/layer/block, free-text search, and read-back of `entity_properties` / `drawing_metadata`. Keep every query indexed — check `EXPLAIN QUERY PLAN`. | `api/routes/projects.py`, `storage/entity_repository.py` (`TAG_QUERY`) |
| **D2** | Tags come only from `TAG`/`COMPONENT_TAG`/`P_TAG` attributes or `TAG=` XData. Components labelled with a nearby plain TEXT entity index no tag and are invisible to every query and edit. Add conservative proximity association. | `cad/extractor/dxf_extractor.py` |
| **D3** | DWG scanning raises `RuntimeError` unless `ODA_FILE_CONVERTER` is set, and it is set nowhere. Make the error actionable and create `.env.example`. | `cad/extractor/oda.py`, new `.env.example` |
| **D4** | `AUDIT_ROUTE_MAP` is keyed by path only, so `GET /api/projects` is logged as `project_register` — every sidebar load forges a record. | `api/main.py` |

**D1 must precede D2.**

---

## 6. Known defects in what has already been shipped

Found by two adversarial reviews (`remediation/verification/`). None are fixed.

| # | Severity | Defect | File |
|---|---|---|---|
| 1 | **CRITICAL** | `open_document` infers ownership from whether `find_open_document` matched. Real `AcadDocuments.Open` returns the **already-open** document, so any path spelling the matcher cannot unify (mapped drive vs UNC, junction, 8.3 name) makes the `finally` close **the user's own drawing**, discarding unsaved work. The fake hides it — its `Open` always builds a second object. | `cad/session.py:48-53` |
| 2 | **HIGH** | Group B is unusable: six routes return `change_set_id` and revert works, but no page outside `project-chat.js` renders a Revert control | `api/static/sketch.html` |
| 3 | MEDIUM | A retried `open_document` leaks the document attempt 1 opened — attempt 2 sees it open and reports `opened_here=False` | `cad/session.py` + 3 executors |
| 4 | MEDIUM | `mark_open` is unguarded, so a SQLite failure now aborts `execute_commands` on a path that never touched the DB before | `cad/session.py` |
| 5 | MEDIUM | `get(<old token>)` still clobbers `_latest_token`, so `get_latest()` can return the old scene while `list_records()[0]` is correct — the two disagree | `framework/cad3d/scene_store.py:230-233` |
| 6 | MEDIUM | The fake raises `KeyError` for three schema-valid combinations: TEXT + `rotation_degrees`, ELLIPSE + angles, DIM_LINEAR + `text_override` | `tests/project/fake_cad.py` |
| 7 | MEDIUM | Title-block still uses its own `backup_file` call rather than the unified mechanism | `use_cases/update_title_block.py:139` |
| 8 | — | **Design decision, not a bug:** reverting a changeset whose apply was interrupted (`after_hash` NULL) can overwrite a third party's later edit. Chosen over refusing forever — but `discard()` now exists, which weakens that rationale. | `cad/changes.py` |

### Verified sound (do not re-investigate)

- `@serialized` is correctly on **both** `execute_commands` and `execute_edit_plan` — confirmed at
  runtime by probing `CAD_LOCK` from a second thread.
- `AddArc` radians→degrees, the ellipse major-axis vector, and the dimension projection are all
  empirically correct.
- 96,000 timestamps across 32 threads: zero duplicates.
- The `change_set_files` migration holds: real old-shape databases migrate with every row intact,
  new constraints enforced, `integrity_check` and `foreign_key_check` clean, and an interrupted
  migration rolls back and self-heals on the next call.
- Reinstalling the real `_com_retry` over both A5 stubs: 369 calls, 18 failures, **0** retried into
  success — the stub hid nothing.

---

## 7. Suggested order for manual work

1. **Defect 1** — data loss, currently live in `main`.
2. **Defect 2** — without it, all of Group B is invisible to users.
3. Defects 3, 4, 6 — same files as 1, cheap to do together.
4. Defect 5, 7; decide 8.
5. **C1**, then **C2** — the capability gap for Requirement 1.
6. **C3**, **C4** — Requirement 3.
7. **D1**, then **D2**; **D3**, **D4** — Requirements 2 and 5.

# Remediation Plan — Closing the Requirements Gap

**Date:** 2026-09-21
**Basis:** `docs_analysis/11_full_project_audit.md` (full audit, ~67 findings)
**Purpose:** specify exactly what must change, where, what it should produce, and how to prove it —
then hand each package to Codex as a standalone prompt.

**This document contains no code changes.** Every package below is written to be executed by Codex.

---

## The gap being closed

| # | Requirement | Today | Target |
|---|---|---|---|
| 1 | Precise in-place edits | Partially — LINE (length), CIRCLE/ARC (radius) only | All common entity types, incl. blocks and polylines |
| 2 | Get metadata, single + multi-file | Works | Works, incl. DWG and layer/document properties |
| 3 | Document-level changes | Partially — "header color" returns a 409 | Header/title-block color works or is answerable |
| 4 | Multiple projects | Works on new path; legacy uses whatever's open | No implicit active-document writes anywhere |
| 5 | Multi-file index | Works, narrowly — two query shapes | General query surface over the index |
| 6 | Consistent preview / keep / revert | 1 of 8 workflows is revertible | All 8 revertible through one mechanism |

---

## Work packages and execution order

Dependencies are real — WP1 and WP2 must land before WP3, and WP5 must land before WP4 is useful.

```
WP1  Backup + error-gated save          (safety floor; unblocks WP3)
WP2  Fix ChangeSet stuck-states          (unblocks WP3)
WP3  One revert mechanism for all 8      -> Requirement 6
WP5  Tag everything generated            (unblocks WP4 in practice)
WP4  Expand the editable entity set      -> Requirement 1
WP6  Document-level completeness         -> Requirement 3
WP7  Retire implicit ActiveDocument      -> Requirement 4
WP8  Index query surface + DWG/ODA       -> Requirements 2, 5
WP9  Standalone correctness bugs         (wrong output; independent)
```

WP9 has no dependencies and can be done at any time, including first — it is small and it stops the
app drawing incorrect geometry.

**Before WP1:** commit the repository. `docs_analysis/`, `fixes/`, `roadmap/`, `remediation/`,
`src/api/static/project-chat.js` and 5 test files are currently untracked. None of the work below is
safe to start on an uncommitted tree.

---

# WP1 — Backup before mutation, and never save a failed batch

**Closes:** the largest data-loss class. Prerequisite for WP3.

### What changes

Three executors write to live drawings with no backup and an unconditional save. Each needs:
1. A `backup_file()` call before the first mutating COM call, when a resolvable file path exists.
2. `doc.Save()` gated on `not errors`.
3. `backup_path` returned in the result dict.

`src/backup.py` also needs a `restore_file()` function and post-copy hash verification — it currently
has neither, while `changes.py:106` hash-verifies its own backups inline.

### Where in the code

| File | Symbol | Issue |
|---|---|---|
| `src/framework/commands/executor.py:463` | `execute_commands` | no backup; `save=True`, `continue_on_error=True` |
| `src/framework/commands/executor.py:543` | `execute_command_sequence` | same |
| `src/framework/commands/executor.py:510` | save block | not gated on `errors` |
| `src/framework/commands/edit_executor.py:137` | `execute_edit_plan` | deletes first, then saves regardless |
| `src/framework/commands/edit_executor.py:203` | `if save:` | not gated on `errors` |
| `src/framework/cad3d/autocad_3d_executor.py:616` | `execute_cad3d_scene` | no backup |
| `src/framework/cad3d/autocad_3d_executor.py:687` | `if save:` | not gated on `errors` |
| `src/backup.py` | module | no restore, no verification, no retention |

**Edge case that must be handled explicitly:** these executors can target `ActiveDocument`, which may
be an unsaved drawing with no file path. Backup is impossible there. The decision must be deliberate
and documented in the result — do not silently skip it.

### Expected effects

- A batch that produces any error no longer writes to disk.
- Any batch that does write to disk has a verified pre-edit copy first.
- Result dicts gain `backup_path: str | None` and `backup_skipped_reason: str | None`.
- `/api/sketch/approve` with a partially-failing plan leaves the file on disk untouched.
- No change to behaviour when `save=False` — that path stays exactly as it is.

### How to test

New tests (all with a fake COM double, no real AutoCAD):
1. `save=True` + one failing command → `doc.Save()` is **not** called, file on disk unchanged.
2. `save=True` + all commands succeed → a backup file exists and its hash equals the pre-edit file's.
3. `save=True` against an unsaved/untitled document → executes, and the result reports
   `backup_skipped_reason`, rather than raising or silently proceeding.
4. `save=False` → no backup taken, no save attempted (unchanged behaviour).
5. `edit_executor`: deletes succeed, additions fail, `save=True` → save is **not** called, so the
   deletions are not committed.

Regression gate: `venv\Scripts\python.exe -m pytest tests/ -q` must stay at **1003 passed, 10
skipped** plus the new tests.

### Codex prompt

```
You are working on a Windows-only Python/FastAPI app at F:\RC-Projects\autocad-ai\autocad-ai that
drives AutoCAD through COM (pywin32). Its core architectural rule: AI only produces schema-validated
JSON plans; deterministic Python is the only code that touches AutoCAD. Do not violate that.

TASK: three execution paths can permanently destroy a user's drawing. Fix all three.

The bug: `execute_commands`/`execute_command_sequence` (src/framework/commands/executor.py:463,543),
`execute_edit_plan` (src/framework/commands/edit_executor.py:137) and `execute_cad3d_scene`
(src/framework/cad3d/autocad_3d_executor.py:616) all call `doc.Save()` without checking whether any
command failed, and none of them ever calls `backup_file()` from src/backup.py. `continue_on_error`
defaults to True and /api/sketch/approve defaults `save=True`, so a plan where 47 of 50 commands
succeed writes a half-finished drawing over the real file with nothing to restore from.
`execute_edit_plan` is worst: it deletes entities by handle FIRST (line ~164), delegates the re-adds,
then saves unconditionally at line ~203 — if the additions fail, the deletions are committed forever.

REQUIRED CHANGES
1. In all three executors, take a backup via src/backup.py's `backup_file()` before the first
   mutating COM call, but only when `save` is true AND a real file path is resolvable.
2. Gate every `doc.Save()` on there being no errors. A batch with any error must not write to disk.
3. Return `backup_path: str | None` and `backup_skipped_reason: str | None` in each result dict.
4. Handle the unsaved/untitled ActiveDocument case explicitly: a backup is impossible with no file
   path. Do NOT silently skip — set `backup_skipped_reason` and keep going. Decide and document
   whether saving is still permitted there; state your reasoning in a comment.
5. Add `restore_file(backup_path, target_path)` to src/backup.py, and make `backup_file()` verify
   the copy by comparing hashes (src/cad/changes.py:106 already does this inline — reuse that
   approach rather than inventing a second one).

DO NOT change behaviour when `save=False`. DO NOT change the AI layer. DO NOT alter the
generate→approve HTTP contract beyond adding the two new result fields.

TESTS (write these; use the existing fake COM double in tests/project/fake_cad.py):
- save=True + one failing command -> Save() NOT called, file on disk byte-identical
- save=True + all succeed -> backup exists, backup hash == pre-edit file hash
- save=True on an unsaved document -> executes, result carries backup_skipped_reason
- save=False -> no backup, no save (unchanged)
- edit_executor: deletes succeed, additions fail, save=True -> Save() NOT called

VERIFY: `venv\Scripts\python.exe -m pytest tests/ -q` must report 1003 passed + your new tests,
10 skipped, 0 failed. Report the exact numbers. If any pre-existing test now fails, do not weaken
it — explain why the fix conflicts with it and stop.
```

---

# WP2 — Fix the three ChangeSet stuck-states

**Closes:** the bugs that brick the only revertible workflow. Prerequisite for WP3.

### What changes

`_check_files` enforces "current file must still hash to `after_hash`" for both `keep` and `revert`.
That is right for `revert` and wrong for `keep`, which writes nothing. Three consequences:

- **2a.** Apply an edit, then open the drawing in AutoCAD and save anything → keep *and* revert both
  refuse forever, and `changes.py:99-102` then blocks every future changeset on that drawing.
  Recovery requires manual SQL.
- **2b.** A hard kill between the COM save and `_record_file` leaves `after_hash` NULL, so
  `expected = after_hash or before_hash` compares the **pre-edit** hash against the **post-edit**
  file — revert is refused exactly when it is needed.
- **2c.** An in-place revert interrupted after `os.replace` leaves the disk correct but the DB stuck
  at `reverting`. The `fixes/03` resume logic only covers the **rename** case (`resuming_revert`
  requires `not current.exists()`; `already_restored` requires `original != current`), and for an
  in-place edit `original == current`.

### Where in the code

| File:line | Symbol | Issue |
|---|---|---|
| `src/cad/changes.py:172` | `keep` → `_check_files` | runs a freshness check it does not need |
| `src/cad/changes.py:188-191` | `_check_files` | only compares against `after_hash` |
| `src/cad/changes.py:187` | `resuming_revert` | rename-only |
| `src/cad/changes.py:251` | `already_restored` | rename-only |
| `src/cad/changes.py:109` | apply | inserts `after_hash` as NULL |
| `src/cad/changes.py:99-102` | apply | conflict check locks the drawing out |
| `src/api/routes/changes.py` | router | no discard/force route exists |

### Expected effects

- `keep` succeeds regardless of later external edits (it writes nothing, so it cannot clobber).
- `revert` accepts `current` hashing to **either** `after_hash` (normal) **or** `before_hash`
  (already restored — resume), for in-place edits as well as renames.
- A changeset interrupted before `after_hash` is recorded is detectable as interrupted, rather than
  silently falling back to `before_hash`.
- A new route resolves a stuck changeset without manual SQL.
- A drawing is never permanently locked out of future edits.

### How to test

1. Apply → externally modify and save the file → `keep` **succeeds**; the drawing is editable after.
2. Apply → externally modify → `revert` still refuses (this is correct, keep it) → the new discard
   route resolves it → the drawing is editable again.
3. In-place (non-rename) revert: interrupt after `os.replace` but before the DB update → retry
   **succeeds**.
4. Raise `KeyboardInterrupt` inside `_record_file` (reproduces the hard-kill DB state) → revert
   **succeeds**.
5. Existing `test_later_disk_or_unsaved_edits_are_not_overwritten` must still pass — the revert
   refusal is intended behaviour and must not be weakened.

### Codex prompt

```
You are working on F:\RC-Projects\autocad-ai\autocad-ai, a Python/FastAPI app that edits AutoCAD
drawings. src/cad/changes.py implements a ChangeSet mechanism (apply -> keep or revert) that is the
only revertible workflow in the app. It has three bugs that permanently brick a drawing.

BUG 1 (changes.py:172, 188-191): `_check_files` enforces "current file must still hash to
after_hash" for BOTH keep and revert. That's correct for revert (don't clobber later work) but wrong
for keep, which writes nothing. So if a user applies an edit, then opens the drawing in AutoCAD and
saves a note, keep AND revert both refuse forever — and the conflict check at changes.py:99-102 then
blocks every future changeset on that drawing. Recovery currently needs manual SQL.

BUG 2 (changes.py:109, consumed at :189): change_set_files is committed with after_hash NULL and only
backfilled by `_record_file` AFTER the COM save. A hard kill in that window makes
`expected = item["after_hash"] or item["before_hash"]` compare the PRE-edit hash against the
POST-edit file, so revert is refused exactly when it's needed.

BUG 3 (changes.py:187 `resuming_revert`, :251 `already_restored`): the resumable-revert logic only
covers the RENAME case — `resuming_revert` requires `not current.exists()` and `already_restored`
requires `original != current`. For a normal in-place edit `original == current`, so an interrupted
revert (died after os.replace, before the DB update) leaves the disk correctly restored but the DB
stuck at 'reverting' forever.

REQUIRED CHANGES
1. Remove the freshness check from the `keep` path entirely. Keep writes nothing; it cannot clobber.
2. In the revert path, accept `current` hashing to EITHER after_hash (normal) OR before_hash
   (already restored / resume), and make this work for in-place edits, not just renames.
3. Make a NULL after_hash an explicit "interrupted" state rather than silently falling back to
   before_hash. Decide how revert should behave for it and comment your reasoning.
4. Add a route to src/api/routes/changes.py that resolves a stuck changeset (discard/force-close)
   without manual SQL, so a drawing can never be permanently locked out.

DO NOT weaken the genuine safety property: revert must still refuse to overwrite later work when the
file has genuinely diverged. The existing test
`test_later_disk_or_unsaved_edits_are_not_overwritten` asserts that and must still pass.

TESTS (write these):
- apply -> externally modify+save -> keep SUCCEEDS, and the drawing is editable afterwards
- apply -> externally modify -> revert still refuses -> new discard route resolves it -> editable
- in-place (NOT rename) revert interrupted after os.replace -> retry SUCCEEDS
- raise KeyboardInterrupt inside _record_file (reproduces the hard-kill DB state) -> revert SUCCEEDS

VERIFY: `venv\Scripts\python.exe -m pytest tests/ -q` -> 1003 passed + your new tests, 10 skipped,
0 failed. Report exact numbers.
```

---

# WP3 — One revert mechanism for all eight workflows

**Closes: Requirement 6.** Depends on WP1 and WP2.

### What changes

Today eight mutating workflows exist and one is revertible. Four separate token caches
(`sketch.py:40`, `pid.py:19`, `cad3d.py:42`, `vessel.py:37`) sit alongside ChangeSet, which became a
*fifth* mechanism rather than a unification.

**Design guidance — do not over-build this.** ChangeSet currently models per-entity structured
operations. The legacy workflows are additive command batches, which do not fit that model. Do not
try to decompose them into entity operations. Instead introduce a **file-level changeset**: back up
the file, execute, record the after-hash, and allow revert by restoring the backup. That gives
KEEP/REVERT to all eight workflows without modelling per-entity detail.

Scope: `/api/sketch/approve`, `/api/pid/approve`, `/api/cad3d/approve`, `/api/cad3d/edit`
(`execute=true`), `/api/generate-vessel/confirm`, `/api/place-symbol`, `/api/autocad/edit`.
`/api/title-block-update` already backs up and should be migrated to the same mechanism for
consistency.

### Where in the code

| File | Change |
|---|---|
| `src/cad/changes.py` | add a file-level changeset item type (whole-file backup + after-hash, no entity rows) |
| `src/api/routes/sketch.py:649` | wrap approve in a changeset, return `change_set_id` |
| `src/api/routes/pid.py:106` | same |
| `src/api/routes/cad3d.py:353, 432` | same, both approve and edit-with-execute |
| `src/api/routes/vessel.py` | same |
| `src/api/routes/place_symbol.py:37` | same |
| `src/api/routes/autocad_edit.py:116` | same |
| `src/api/routes/title_block.py` | migrate off its ad-hoc `backup_file` call |
| `src/api/static/sketch.html` | surface `change_set_id` + a Revert control in every result bubble |

### Expected effects

- Every mutating route returns a `change_set_id`.
- `POST /api/change-sets/{id}/revert` restores the pre-edit file for any of the eight workflows.
- The chat UI offers Revert after every operation, not only project operations.
- Token caches keep their current job (holding an unexecuted plan between generate and approve) but
  are no longer the only record that something happened.

### How to test

1. For each of the eight routes: execute with `save=True` against a temp DXF → a `change_set_id` is
   returned → revert → the file is **byte-identical** to before.
2. Revert twice → the second is rejected cleanly, not a crash.
3. Execute → externally modify → revert refuses (WP2 semantics hold for file-level changesets too).
4. A failed execution (WP1: no save) creates no changeset, or creates one marked failed — decide and
   test whichever you implement.

### Codex prompt

```
You are working on F:\RC-Projects\autocad-ai\autocad-ai. PREREQUISITE: work packages WP1 and WP2 from
remediation/REMEDIATION_PLAN.md must already be complete. Verify that before starting — src/backup.py
should have restore_file(), and src/cad/changes.py's keep path should no longer run a freshness check.

CONTEXT: this app has 8 mutating workflows and only 1 is revertible. The project's own stated goal was
"every mutating operation can be previewed, kept, or reverted, consistently, across every workflow."
Four token caches (sketch.py:40, pid.py:19, cad3d.py:42, vessel.py:37) sit alongside the ChangeSet
mechanism in src/cad/changes.py, which became a fifth mechanism rather than a unification.

TASK: give all 8 workflows KEEP/REVERT through the existing ChangeSet mechanism.

DESIGN CONSTRAINT — READ THIS CAREFULLY. ChangeSet currently models per-entity structured operations.
The legacy workflows (sketch, P&ID, CAD3D, vessel, place-symbol, autocad/edit) are additive command
batches that do NOT fit that model. Do NOT decompose them into entity operations — that is a large
and unnecessary refactor. Instead add a FILE-LEVEL changeset item type: back up the file, execute,
record the after-hash, and revert by restoring the backup. Reuse the existing change_sets /
change_set_files tables and the existing keep/revert routes. Per-entity detail is out of scope.

ROUTES TO COVER: /api/sketch/approve (routes/sketch.py:649), /api/pid/approve (pid.py:106),
/api/cad3d/approve and /api/cad3d/edit with execute=true (cad3d.py:353,432),
/api/generate-vessel/confirm (vessel.py), /api/place-symbol (place_symbol.py:37),
/api/autocad/edit (autocad_edit.py:116). Also migrate /api/title-block-update off its ad-hoc
backup_file() call onto the same mechanism.

ALSO: update src/api/static/sketch.html so every result bubble shows the change_set_id and offers a
Revert control — today only project operations get one. Escape all interpolated values; that file
already has an escapeText helper, use it.

DO NOT remove the token caches. They still do a real job (holding an unexecuted plan between generate
and approve). This task is about what happens AFTER execution.

TESTS (write these):
- for EACH of the 8 routes: execute against a temp DXF with save=True -> change_set_id returned ->
  revert -> file is BYTE-IDENTICAL to before
- revert twice -> second is rejected cleanly, no crash
- execute -> externally modify the file -> revert refuses (WP2 semantics must hold here too)
- a failed execution creates no changeset (or one marked failed — implement one, test it, say which)

VERIFY: `venv\Scripts\python.exe -m pytest tests/ -q`. Report exact pass/skip/fail numbers.
```

---

# WP4 — Expand the editable entity set

**Closes: Requirement 1.** Much more useful after WP5.

### What changes

Resize currently supports LINE (length) and CIRCLE/ARC (radius, XY-plane only). There is no scale or
stretch operation anywhere, so polylines, blocks, 3D solids, ellipses, splines and dimensions cannot
be resized at all. Colour is ACI 0–256 only, with no RGB/TrueColor.

Add: LWPOLYLINE/POLYLINE scaling, INSERT/block scaling (`XScaleFactor`/`YScaleFactor`/`ZScaleFactor`),
ELLIPSE axis resize, a generic `SCALE_ENTITY` operation about a chosen basepoint, and RGB TrueColor.

### Where in the code

| File:line | Symbol | Change |
|---|---|---|
| `src/framework/commands/modification_executor.py` | `_resize` | add per-type branches |
| `src/framework/commands/modification_executor.py:141-148` | radius path | currently XY-plane only |
| `src/cad/orchestrator.py:120-141` | `plan` | plan-time validation must match the new set |
| `src/framework/commands/operation_schema.py:22-24` | colour | ACI-only; add TrueColor |
| `src/ai/project_planner.py` | `OPERATION_VARIANTS` | teach the planner the new operations |

**Note:** `orchestrator.py` validates dimensions at plan time and `modification_executor` validates
again at execute time. Both must be updated together or plans will be accepted and then fail.

Also relevant: the audit found that for ARCs the plan-time "before radius" is derived from a bounding
box (`(max_x - min_x) / 2`) while execute-time reads `entity.Radius` via COM. For an arc the bounding
box spans only the rendered segment, not the full circle, so these disagree. Fix that while here.

### Expected effects

- A user can resize a polyline, a block reference and an ellipse, not just lines and circles.
- A generic scale operation works about a specified basepoint.
- Colours can be set as RGB as well as ACI.
- Plan-time and execute-time validation agree for every supported type, including ARC.

### How to test

1. For each newly supported type: build a DXF containing it, scan, plan a resize, execute, re-extract
   and assert the new dimension — and assert the entity handle is **unchanged** (proving in-place
   edit, not delete-and-recreate).
2. Unsupported types still fail at **plan** time with a clear message, before any job row is created.
3. ARC resize: plan-time `before` equals execute-time `before` (the bounding-box vs `Radius`
   disagreement).
4. RGB colour round-trips through save and re-extraction.

### Codex prompt

```
You are working on F:\RC-Projects\autocad-ai\autocad-ai. The app edits AutoCAD entities in place via
COM property assignment (never delete-and-recreate — preserve that rule absolutely).

TASK: the in-place editor supports far too few entity types. Expand it.

TODAY: length resize works on LINE only; radius resize on CIRCLE/ARC only and only in the XY plane.
There is no scale or stretch operation anywhere, so polylines, block references, 3D solids, ellipses,
splines and dimensions cannot be resized at all. Colour is ACI integer 0-256 only.

ADD SUPPORT FOR
- LWPOLYLINE / POLYLINE scaling
- INSERT (block reference) scaling via XScaleFactor / YScaleFactor / ZScaleFactor
- ELLIPSE major/minor axis resize
- a generic SCALE_ENTITY operation about a caller-specified basepoint
- RGB / TrueColor in addition to ACI

WHERE
- src/framework/commands/modification_executor.py `_resize` — add per-type branches
- src/cad/orchestrator.py:120-141 `plan` — plan-time validation MUST be updated in lockstep, or plans
  get accepted and then fail at execute time
- src/framework/commands/operation_schema.py:22-24 — colour schema
- src/ai/project_planner.py OPERATION_VARIANTS — teach the planner the new operations

ALSO FIX WHILE HERE: for ARC entities the plan-time "before radius" is computed from the bounding box
as (max_x - min_x)/2, but execute time reads entity.Radius via COM. An arc's bounding box spans only
the rendered segment, not the full circle, so these two disagree. Make them agree.

HARD RULES
- Every edit must remain an in-place property assignment. No .Delete() + re-add, ever.
- Keep the existing pre-flight guards: unsaved-doc check, index-freshness hash check, live-vs-indexed
  geometry check, units check, post-assignment read-back, post-save re-extraction. New types must go
  through all of them.
- Unsupported types must still be rejected at PLAN time (before a job row is created), with a message
  naming the type and what is supported.

TESTS (write these; use real DXF files via ezdxf plus the fake COM double in tests/project/fake_cad.py):
- for EACH newly supported type: build a DXF, scan, plan, execute, re-extract, assert the new
  dimension, AND assert the entity handle is UNCHANGED (this proves in-place editing)
- an unsupported type fails at plan time with a clear message and creates no job row
- ARC: plan-time `before` == execute-time `before`
- an RGB colour round-trips through save and re-extraction

VERIFY: `venv\Scripts\python.exe -m pytest tests/ -q`. Report exact numbers.
```

---

# WP5 — Make generated drawings addressable

**Enables Requirement 1 in practice.** Small, high leverage — do it before WP4.

### What changes

`fixes/01` gave P&ID pipes and valves a `tag` parameter, but **no shipped template ever passes one**.
Rendering the default template produces **80 commands, 5 tagged** — all five from the vessel and
instrument bubbles. 26 LINEs, 25 POLYLINEs, 2 ARCs and 1 CIRCLE carry no tag.

The consequence is structural: the app's own generator produces drawings its own editor cannot
address. "Generate a P&ID, then resize pipe P-101" — the exact scenario `fixes/01` was written for —
still fails end to end.

### Where in the code

| File | Change |
|---|---|
| `src/framework/pid/component_templates.py:50-124, 154-198, 230-255` | every `pipe_run`, `gate_valve`, `control_valve` must carry a `tag` |
| `src/framework/pid/component_examples.py` | same for `PipeRunComponent`, `GateValveComponent`, `ControlValveComponent` |
| `src/framework/pid/components/piping.py`, `valves.py` | confirm `render()` passes `tag=self.tag` through |
| `src/framework/pid/scene_renderer.py:88, 98-108` | older non-component path passes no `tag` at all |
| `src/ai/pid_component_planner.py` | planner should emit tags; auto-generate where the model omits one |
| `src/framework/cad3d/` | audit for the same gap on the 3D side |

### Expected effects

- Rendering any shipped P&ID template produces geometry where **every** component carries a
  recoverable `TAG=` XData value.
- After generating a P&ID and scanning it, `GET /api/projects/{id}/entities?tag=P-101` finds the pipe.
- A resize planned against a generated component succeeds end to end.

### How to test

1. For every shipped template: render it and assert **zero** untagged component commands (the current
   count is 5 of 80 tagged — the test should assert the ratio is 1:1 for component-bearing commands).
2. Full round trip: generate a P&ID → execute into a DXF → scan → `find_by_tag` returns the pipe →
   plan a resize → it validates.
3. Tag uniqueness within a drawing is enforced (the planner already rejects ambiguous tags).

### Codex prompt

```
You are working on F:\RC-Projects\autocad-ai\autocad-ai. This app generates P&ID drawings AND edits
drawings by engineering tag. Right now those two halves cannot reach each other.

THE BUG: a previous fix (documented in fixes/01_pid_component_identity.md) added a `tag` parameter to
the pipe/valve/instrument symbol builders so generated components would carry recoverable AUTOCAD_AI_TAG
XData. But NO SHIPPED TEMPLATE EVER PASSES ONE. Rendering the default template
(choose_pid_component_template("draw me a p&id") -> horizontal_separator) produces 80 commands of which
only 5 are tagged — all 5 from the vessel and instrument bubbles. 26 LINEs, 25 POLYLINEs, 2 ARCs and
1 CIRCLE have no tag. So "generate a P&ID, then resize pipe P-101" — the exact scenario that fix was
written for — still fails end to end.

REQUIRED CHANGES
1. src/framework/pid/component_templates.py:50-124, 154-198, 230-255 — every pipe_run, gate_valve and
   control_valve component in every shipped template must carry a tag.
2. src/framework/pid/component_examples.py — same for PipeRunComponent, GateValveComponent,
   ControlValveComponent (all currently constructed without tag=).
3. src/framework/pid/components/piping.py and valves.py — confirm render() actually passes
   tag=self.tag through to the symbol builder.
4. src/framework/pid/scene_renderer.py:88,98-108 — the older non-component path passes no tag at all.
   It is currently dormant (no caller outside framework/pid) but it is exported; either wire tags
   through it or mark it clearly as deprecated.
5. src/ai/pid_component_planner.py — the planner should emit tags, and auto-generate a sensible one
   when the model omits it. Follow the existing engineering convention (P-101, V-201, FT-301...).
6. Audit src/framework/cad3d/ for the same gap and report what you find.

TESTS (write these):
- for EVERY shipped template: render it and assert zero untagged component commands
- full round trip: generate a P&ID -> execute into a DXF -> scan it -> find_by_tag returns the pipe ->
  plan a resize against it -> the plan validates
- tag uniqueness within a drawing is enforced

VERIFY: `venv\Scripts\python.exe -m pytest tests/ -q`. Report exact numbers.
```

---

# WP6 — Document-level completeness

**Closes: Requirement 3.**

### What changes

Three separate gaps:

- **"Header color" is a dead end.** `project_planner.py:35-36` instructs the model to return
  `CLARIFY`, which becomes a `ValueError` → HTTP 409. The user gets an error, not a follow-up
  question. Either implement title-block/header colour as a real operation, or make CLARIFY a
  conversational response the UI can act on.
- **The extractor reads no layer table and no SummaryInfo** (`dxf_extractor.py:47-49`). So layer
  colours and document properties are never queryable, and they are the only operations **not**
  re-verified after save.
- **Layer colour is ACI-only** — same limitation as entity colour in WP4.

### Where in the code

| File:line | Change |
|---|---|
| `src/ai/project_planner.py:35-36` | the CLARIFY instruction |
| `src/ai/project_planner.py:42` | `plan_operation` turns CLARIFY into a `ValueError` |
| `src/cad/extractor/dxf_extractor.py:47-49` | `_parse` — extract layer table and SummaryInfo |
| `src/storage/schema.sql` | somewhere to store layer/document metadata |
| `src/framework/commands/modification_executor.py:185-192` | `_prepare` — layer colour, doc properties |
| `src/framework/commands/modification_executor.py:321-348` | post-save verification covers only RESIZE and SET_ENTITY_PROPERTY |

### Expected effects

- Asking to change a header colour either performs it or returns an answerable clarification the UI
  renders as a question — never a bare 409.
- Layer names, layer colours and document properties are extracted, stored and queryable.
- Layer-colour and document-property edits are verified after save, like every other operation.

### How to test

1. A DXF with a layer coloured 5 → scan → the layer and its colour appear in the index.
2. Plan and execute a layer-colour change → re-extract → the new colour is confirmed, and a lying
   save is caught (temporarily make the fake COM double not persist, assert the operation fails).
3. Document properties (Title/Author) round-trip through scan → edit → re-extract.
4. A "change the header colour" prompt returns a structured clarification, not an unhandled 409.

### Codex prompt

```
You are working on F:\RC-Projects\autocad-ai\autocad-ai. This app edits AutoCAD drawings from natural
language. Three gaps in document-level editing.

GAP 1 — "header color" is a dead end. src/ai/project_planner.py:35-36 instructs the model to return
CLARIFY for it, and plan_operation at :42 turns that into a ValueError -> HTTP 409. The user asks a
reasonable question and gets an error. Either (a) implement title-block/header colour as a real
operation, or (b) make CLARIFY a first-class conversational response the frontend can render as a
follow-up question. Pick one, implement it properly, and explain your choice in a comment. If you pick
(b), src/api/static/sketch.html must actually render it as a question rather than a red error.

GAP 2 — the extractor reads no layer table and no SummaryInfo. src/cad/extractor/dxf_extractor.py:47-49
`_parse` extracts entities and geometry but never the layer table or document SummaryInfo. Verified: a
DXF with a layer coloured 5 yields DocumentMetadata(properties={}). Consequences: layer colours and
document properties are never queryable from the index, AND they are the only operations not
re-verified after save. Extract both, store them (extend src/storage/schema.sql as needed), and make
them queryable.

GAP 3 — layer colour is ACI 1-255 only (modification_executor.py:185-187 sets
doc.Layers.Item(layer).Color). Add RGB/TrueColor. If WP4 has already landed, reuse the same colour
representation rather than inventing a second one.

ALSO: extend the post-save verification at modification_executor.py:321-348 to cover layer-colour and
document-property edits. It currently covers only RESIZE and SET_ENTITY_PROPERTY, so these two
operations trust a silent Save().

TESTS (write these):
- a DXF with a coloured layer -> scan -> layer and colour appear in the index
- plan+execute a layer colour change -> re-extract confirms it
- a LYING save is caught: make the fake COM double not persist the change, assert the operation fails
  rather than reporting success
- document properties (Title/Author) round-trip through scan -> edit -> re-extract
- a "change the header colour" request returns a structured clarification, not an unhandled 409

VERIFY: `venv\Scripts\python.exe -m pytest tests/ -q`. Report exact numbers.
```

---

# WP7 — Retire implicit ActiveDocument writes

**Closes: Requirement 4.**

### What changes

The new path resolves every document by absolute path and the test suite actively forbids implicit
targeting (`fake_cad.Acad.ActiveDocument` raises
`AssertionError("Implicit active-document targeting is forbidden")`). The legacy routes never got
this: `sketch.py:402`, `pid.py:108`, `cad3d.py` and `autocad_edit.py:43` all accept an *optional*
`target_dwg_path` and silently fall back to `ActiveDocument`. `place_symbol`, `title_block` and
`line_list` have no project concept at all.

Two related defects to fix in the same pass:

- **`edit_executor.py:188`** delegates additions with `target_dwg_path=None`, so `executor.py:482`
  resolves `ActiveDocument` — **not** the document `edit_executor` opened at `:42`. Deletions land in
  one drawing and additions in another.
- **`executor.py:476-480` and `edit_executor.py:40-47`** call `acad.Documents.Open()` directly
  instead of `session.get_document`, skipping the `is_file` check, the already-open lookup and the
  identity check — and **never `Close()`**. Open documents accumulate across requests. Same at
  `autocad_3d_executor.py:644-647`.

### Where in the code

| File:line | Change |
|---|---|
| `src/api/routes/sketch.py:402` | fallback to ActiveDocument |
| `src/api/routes/pid.py:108` | same |
| `src/api/routes/cad3d.py:353, 432` | same |
| `src/api/routes/autocad_edit.py:43` | same |
| `src/framework/commands/edit_executor.py:188` | delegates with `target_dwg_path=None` |
| `src/framework/commands/executor.py:476-480` | direct `Documents.Open`, never closed |
| `src/framework/commands/edit_executor.py:40-47` | same |
| `src/framework/cad3d/autocad_3d_executor.py:644-647` | same |

### Expected effects

- Writing to the active document requires an explicit opt-in flag; it is never the silent default.
- `edit_executor` deletions and additions always land in the **same** document.
- Documents opened by an executor are closed again; they stop accumulating in the AutoCAD session.

### How to test

1. A request with no target and no opt-in flag → rejected with a clear message, no COM write.
2. A request with the explicit opt-in → uses ActiveDocument, as before.
3. `edit_executor` with an explicit target while a *different* document is active → both deletions
   and additions land in the target.
4. Executing N requests with `target_dwg_path` → the number of open documents does not grow.

### Codex prompt

```
You are working on F:\RC-Projects\autocad-ai\autocad-ai. The app was meant to stop assuming "whatever
drawing AutoCAD happens to have open." The new project path did that; the legacy routes never did.

TASK 1 — remove implicit active-document targeting from the legacy routes.
src/api/routes/sketch.py:402, pid.py:108, cad3d.py:353 and :432, autocad_edit.py:43 all accept an
OPTIONAL target_dwg_path and silently fall back to ActiveDocument. Make writing to the active document
require an explicit opt-in (e.g. a `use_active_document: bool = False` request field). With neither a
target nor the opt-in, reject the request with a clear message before any COM call. The new path
already enforces this — tests/project/fake_cad.py's Acad.ActiveDocument raises
AssertionError("Implicit active-document targeting is forbidden"). Match that standard.

TASK 2 — fix a real cross-document bug. src/framework/commands/edit_executor.py:188 delegates its
additions with target_dwg_path=None, so executor.py:482 resolves acad.ActiveDocument — NOT the document
edit_executor opened at line 42. There is no doc.Activate() before delegation (it only happens at line
220, after the save). So with drawing B focused and a request targeting drawing A, the deletions land
in A and the new geometry lands in B, and doc.Save() saves only A. The reported entity counts are read
from A, so they lie too. Make deletions and additions always target the same document.

TASK 3 — stop leaking open documents. executor.py:476-480, edit_executor.py:40-47 and
autocad_3d_executor.py:644-647 all call acad.Documents.Open() directly instead of using
src/cad/session.py's get_document, which does an is_file check, an already-open lookup and a
FullName identity check. None of them ever Close(). Every approve with a target_dwg_path leaves another
drawing open in the user's AutoCAD session, accumulating across requests. Route them through
get_document and close what you open (but never close a document the user already had open —
get_document's already-open lookup tells you which).

TESTS (write these):
- no target and no opt-in -> rejected with a clear message, no COM write attempted
- explicit opt-in -> uses ActiveDocument as before
- edit_executor with an explicit target while a DIFFERENT document is active -> deletions AND
  additions both land in the target
- N requests with target_dwg_path -> the count of open documents does not grow

VERIFY: `venv\Scripts\python.exe -m pytest tests/ -q`. Report exact numbers.
```

---

# WP8 — Index query surface, TEXT labels, and DWG support

**Closes: Requirements 2 and 5.**

### What changes

Three limits make the index far less useful than it should be:

- **Only two query shapes exist** — `?tag=` exact match and `nearby?tag=`. There is no "list entities
  in drawing X", no filter by type/layer/block, no free-text search, and no way to read back
  `drawing_metadata` or `entity_properties`.
- **Tags come only from `TAG`/`COMPONENT_TAG`/`P_TAG` attributes or `TAG=` XData.** Drawings that
  label components with plain TEXT index no tag at all, so they are invisible to every query and
  every edit.
- **DWG scanning needs `ODA_FILE_CONVERTER`**, which is unset, undocumented and absent from the
  startup script — so the index is effectively DXF-only.

### Where in the code

| File | Change |
|---|---|
| `src/api/routes/projects.py:57-76` | add list/filter/search endpoints |
| `src/storage/entity_repository.py:70-82` | `TAG_QUERY` is exact-match only |
| `src/cad/extractor/dxf_extractor.py:67-71` | tag extraction sources |
| `src/cad/extractor/oda.py` | surface a clear setup error, not a bare `RuntimeError` |
| `.env.example` (create), `README`, `setup-and-start.ps1` | document `ODA_FILE_CONVERTER` |

Note `src/api/main.py`'s `AUDIT_ROUTE_MAP` is keyed by path only, never method — `/api/projects` has
both a GET and a POST, so `GET /api/projects` currently logs as `project_register`. Fix that while
adding routes, or the new endpoints will inherit the same confusion.

### Expected effects

- Entities can be listed and filtered by drawing, type, layer and block, and searched by text.
- Layer/document metadata is readable back out of the index (pairs with WP6).
- Components labelled with nearby TEXT are indexed and addressable.
- DWG folders scan successfully once ODA is configured, with a clear error when it is not.

### How to test

1. Scan a multi-entity DXF → list entities for the drawing → filter by type, by layer → correct
   subsets returned.
2. Free-text search finds an entity by a label that is **not** a formal tag.
3. A DXF labelling a pipe with plain TEXT near the line → after scan, that component is findable.
4. A `.dwg` with `ODA_FILE_CONVERTER` unset → a clear, actionable error naming the variable (not a
   bare `RuntimeError`).
5. `GET /api/projects` is audit-logged as a *list* operation, not `project_register`.

### Codex prompt

```
You are working on F:\RC-Projects\autocad-ai\autocad-ai. It maintains a SQLite index of a folder of
AutoCAD drawings. The index itself is solid — its spatial correctness was verified across 675
comparisons with zero mismatches. The problem is that almost nothing can be asked of it.

GAP 1 — only two query shapes exist: GET /api/projects/{id}/entities?tag= (exact match) and
GET /api/projects/{id}/nearby?tag=. There is no "list entities in drawing X", no filter by type/layer/
block, no free-text search, and no way to read back drawing_metadata or entity_properties. Add these
to src/api/routes/projects.py (currently :57-76) and src/storage/entity_repository.py (TAG_QUERY at
:70-82 is exact-match only). Keep queries indexed — do not introduce table scans; check
EXPLAIN QUERY PLAN for anything you add, as tests/project/test_entity_index.py already does.

GAP 2 — tags are only extracted from TAG/COMPONENT_TAG/P_TAG block attributes or TAG= XData
(src/cad/extractor/dxf_extractor.py:67-71). Real drawings frequently label a component with a plain
TEXT entity placed near it. Those components index no tag at all, so they are invisible to every query
AND to every edit. Add proximity-based TEXT label association. Be conservative: a wrong association is
worse than none, since edits are driven off this index. Document your distance threshold and your
reasoning, and make it configurable.

GAP 3 — DWG scanning raises RuntimeError unless ODA_FILE_CONVERTER is set. It is not set in .env, not
in the README, and not in setup-and-start.ps1, so the index is effectively DXF-only today. Make
src/cad/extractor/oda.py raise a clear, actionable error naming the variable and how to install the
converter. Create a .env.example documenting every variable (.gitignore already has a !.env.example
negation for it) and document the setup.

ALSO FIX: src/api/main.py's AUDIT_ROUTE_MAP is keyed by path only, never by HTTP method, and
/api/projects has both a GET (list) and a POST (register). So GET /api/projects is currently
audit-logged as use_case="project_register" — every sidebar load forges a record claiming a project was
registered. Make the map method-aware before adding more routes to it.

TESTS (write these):
- scan a multi-entity DXF -> list entities for the drawing -> filter by type, by layer -> correct subsets
- free-text search finds an entity by a label that is NOT a formal tag
- a DXF labelling a pipe with a nearby plain TEXT entity -> after scan that component is findable
- a .dwg with ODA_FILE_CONVERTER unset -> clear actionable error naming the variable
- GET /api/projects is audit-logged as a list operation, not project_register

VERIFY: `venv\Scripts\python.exe -m pytest tests/ -q`. Report exact numbers.
```

---

# WP9 — Standalone correctness bugs

**No dependencies.** Small, self-contained, and they stop the app producing wrong output. Can be done
first.

### What changes

| Bug | Location | Effect today |
|---|---|---|
| Move parser reads the distance out of the tag | `src/ai/cad3d_edit_planner.py:246` | `"move P-101 up 500 mm"` moves it **101 mm** |
| `AddEllipse` given an absolute point | `src/framework/commands/executor.py:246` | preview and drawn ellipse differ |
| DOWN flow arrow malformed | `src/framework/pid/symbols.py:528` | 71 units and asymmetric vs 90 and symmetric |
| `NaN`/`Infinity` pass validation | `src/framework/commands/schema.py:382` | poisons `$EXTMIN`/`$EXTMAX` on a saved file |
| Stored XSS | `src/api/static/jobs.html:161` | attacker-controlled string executes in the operator's browser |
| Token caches never expire | `src/api/routes/pid.py:19`, `cad3d.py:42` | unbounded memory growth |
| `/api/cad3d/edit` token never consumed | `src/api/routes/cad3d.py:325` | scene replayable into AutoCAD |
| Audit rows stuck at `started` | `src/api/main.py:298` | unauthenticated unbounded DB growth |
| Output token cap too low | `src/ai/client.py:130` | any sketch over ~25 commands fails as "invalid JSON" |
| Vessel head depth disagreement | `draw_dimensions.py:87-90` vs `geometry.py:65-66` | drawn 5510, dimensioned 5500 |

### Expected effects

Correct geometry, correct dimensions, no XSS, bounded memory, and honest error messages.

### How to test

Each bug gets a test asserting the corrected behaviour. Two existing tests must be **repaired**, not
just supplemented:
- `tests/framework/test_cad3d_edit_planner.py:95` uses the exact broken phrasing but asserts only
  `component_id`. It must assert the delta.
- `tests/parametric/test_view_consistency.py:78` never calls any source function — it computes
  `2000/4` inline and asserts `== 500`. It is a tautology and cannot fail. Rewrite it to call the real
  code.

### Codex prompt

```
You are working on F:\RC-Projects\autocad-ai\autocad-ai. Ten independent correctness bugs, all
verified. Fix each, and write a test for each.

1. src/ai/cad3d_edit_planner.py:246 — the deterministic move-parser regex matches the digits inside
   the component tag, so the tag number becomes the move distance. Verified:
     'move P-101 up 500 mm'    -> [0,0,101]    expected [0,0,500]
     'shift T-101 left 250'    -> [-101,0,0]   expected [-250,0,0]
     'move the pump up 500 mm' -> [0,0,500]    correct (name has no digits)
   Only the distance-first form ("1000 mm to the right") parses correctly. Since nearly every
   engineering tag has digits, the broken case is the common one.
   ALSO: tests/framework/test_cad3d_edit_planner.py:95 uses the exact broken phrasing but asserts only
   component_id, never the delta — which is why this survived. Fix the test to assert the delta.

2. src/framework/commands/executor.py:246 — AutoCAD COM AddEllipse(Center, MajorAxis, RadiusRatio)
   takes MajorAxis as a vector RELATIVE to center. The executor passes command["major_axis_endpoint"]
   raw/absolute. src/framework/commands/preview.py:142-146 does it correctly (endpoint - center), so the
   user previews one ellipse and AutoCAD draws a different one. There is no ELLIPSE test at all — add one.

3. src/framework/pid/symbols.py:528 — the DOWN flow arrow uses `y + width` for its base corners where
   every other direction uses `half`. At size=100, RIGHT/LEFT/UP are 90 long and symmetric; DOWN is 71
   and asymmetric (y bbox -45..+26 instead of -45..+45). It appears in the DEFAULT template (P_DRAIN).
   tests/framework/test_pid_symbols.py:140 parametrizes all four directions but asserts only
   command=="POLYLINE" and closed is True — assert the actual points.

4. src/framework/commands/schema.py:382 — validate_command_sequence has no allow_nan=False guard
   (src/framework/commands/operation_schema.py:43 does), and src/ai/client.py:90 uses bare json.loads,
   which accepts NaN/Infinity literals. Verified: a CIRCLE with center=[NaN,0] and radius=Infinity
   returns ZERO validation errors and reaches AddCircle, poisoning $EXTMIN/$EXTMAX on a saved file.

5. src/api/static/jobs.html:161 — row.innerHTML interpolates truncateError(job.error_message) with no
   escaping; job.source and job.use_case at :159-160 likewise. sketch.html does this correctly in 60
   places via escapeText. Attack chain: POST /api/projects with a malicious root_path -> ValueError
   containing it -> HTTPException(409, str(exc)) -> stored in jobs.error_message -> executes when an
   operator opens /jobs.html, same-origin with the API that drives AutoCAD.

6. src/api/routes/pid.py:19 and cad3d.py:42 — _PID_CACHE and _CAD3D_CACHE never expire. created_at is
   stored and never read. sketch.py and vessel.py already implement a 10-minute TTL purge — copy that
   pattern rather than inventing a third one.

7. src/api/routes/cad3d.py:325 — cad3d_edit writes _CAD3D_CACHE[edited_token] and never pops it, even
   after execute=true succeeds. cad3d_approve:496 pops correctly. Same replay hole, missed.

8. src/api/main.py:298 — AuditJobMiddleware calls log_job_start() as soon as the path matches, but
   log_job_end() only runs from the endpoint wrapper. Any request that never reaches the endpoint (422
   validation, 404, 405) leaves a permanent row at status="started". Reproduced: POST /api/pid/generate
   with {"nope":1} -> 422 and an orphan row. This is an unauthenticated unbounded-DB-growth primitive.

9. src/ai/client.py:130 — _resolve_max_tokens defaults the OUTPUT cap to 800 tokens, while
   src/ai/command_generator.py:40 tells the model "Do not output more than 1000 commands." A 61-command
   sequence measures ~1,390 output tokens. The response is cut mid-JSON and the user gets
   "502 AI returned invalid JSON" — a token-budget problem misreported as a model formatting problem.
   Raise the default to match the other planners (which set 2000-5000 explicitly) AND inspect
   finish_reason at client.py:179 so a "length" truncation is reported as truncation.

10. src/parametric/vessel/draw_dimensions.py:87-90 uses ID/4 = 500 for head depth while
    src/parametric/vessel/geometry.py:65-66 draws the head with (D/2 + t)/2 = 505. Measured: drawn
    overall length 5510, dimension text says 5500, and head nozzles sit 5 mm off the head.
    CRITICAL: tests/parametric/test_view_consistency.py:78 was supposed to catch this but it never
    calls any source function — it computes V201.internal_diameter_mm / 4.0 inline in the test body and
    asserts 2000/4 == 500. It is pure arithmetic and cannot fail. REWRITE it to call the real code.
    Decide which value is correct, make all call sites agree, and say which you chose and why.

VERIFY: `venv\Scripts\python.exe -m pytest tests/ -q`. Report exact numbers. Two existing tests must be
repaired rather than supplemented (items 1 and 10) — do not leave a tautological test in place.
```

---

## Separate from the work packages: test-infrastructure debt

These are not requirement gaps but they determine whether any of the above can be trusted. Worth
handing to Codex as its own task once the packages above are done.

- **`tests/api/` has no `conftest.py`**, so running it writes to the real `jobs.db`. Proven: running
  `tests/api/` alone injected 135 rows into production job history and created 16 tables. Mirror
  `tests/project/conftest.py`'s isolation.
- **`tests/project/fake_cad.py:100-102` returns ModelSpace as a plain Python list**, so `executor.py`'s
  entire creation surface (lines 204-354) can never run against it. Circles, arcs, ellipses,
  dimensions and MText have no COM-shaped creation test at all.
- **`tests/project/test_modification.py:24` stubs out `session.point`** (`monkeypatch.setattr(engine,
  "point", tuple)`) for all 27 tests in the file, because the fake cannot accept a real VARIANT. Real
  AutoCAD requires a VARIANT and rejects a bare tuple, so that file proves nothing about coordinate
  assignment.
- **23 of 118 source modules have no test at all**, including the entire ~2,350-line vessel renderer —
  which is precisely why WP9 item 10 survived.
- **~65 s of the 122 s suite runtime is real `time.sleep`** from `_com_retry` exhausting its backoff.
  `tests/framework/test_autocad_inspector.py:129` already stubs `_com_retry`; the other files don't.
- **No CI exists at all.** Nothing enforces the 1003 tests.
- **No `pytest.ini`/`pyproject.toml`**, so no `testpaths`. `src/scratch/` contributes 0 test items
  today, but `draw_circle.py`, `draw_shapes.py` and `test.py` call `GetActiveObject("AutoCAD.Application")`
  and `AddCircle`/`AddLine` **at import time with no `__main__` guard**. One added `def test_…` away
  from pytest driving real AutoCAD. Nothing imports `src.scratch`; all 17 files are safely deletable.

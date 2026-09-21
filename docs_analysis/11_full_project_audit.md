# Full Project Audit — Bugs, Features, and Requirements Fit

**Date:** 2026-09-21
**Scope:** every source file in `src/` (~26,000 lines, 130+ files), the entire `tests/` tree (80+ files),
the static frontend, configuration and startup scripts.
**Method:** seven parallel review agents, each with an isolated subsystem scope, each required to
verify findings by reading the real code path and — where possible — executing it. Claims that could
not be substantiated were dropped. The highest-severity findings were then independently re-verified
by hand (marked ✅ below).

This audit supersedes nothing. It is complementary to:
- `docs_analysis/00`–`08` — what the code *is* (feature reference)
- `docs_analysis/09` — 30 pre-existing issues found in the original codebase
- `docs_analysis/10` — 20 issues found in the roadmap Steps 1–8 extension work
- `fixes/01`–`07` — seven rounds of fixes applied against doc 10's list

**Critical context:** the seven fix modules in `fixes/` were driven *entirely* by doc 10's list (the
extension review). Doc 09's 30 pre-existing issues were never worked through. Several remain open and
are re-confirmed below.

---

## 1. Verdict

The project contains two applications.

**The new one** — register a project → scan a folder → query a SQLite index → plan an operation →
apply it as a changeset → keep or revert — is well-built. It is genuinely offline (no AutoCAD needed
to scan or query), genuinely in-place (no delete-and-redraw), well-tested, and its index is
trustworthy: an agent ran 675 R*Tree-vs-cKDTree comparisons across coordinates spanning 1 → 1e9 and
found zero mismatches, and the `expected_hash` freshness checks reliably catch out-of-band file edits
before any COM write.

**The old one** — the sketch, P&ID, CAD3D, vessel, place-symbol and `/api/autocad/edit` workflows —
is the part users actually touch from the chat UI, and it writes to live drawings with **no backup,
no revert, and a save that is not gated on whether errors occurred**.

Nothing was retired, migrated, or gated when the new application was built. Both are fully wired and
reachable. That is the single most important finding in this document, and it is the direct cause of
the requirements gap in §2.

---

## 2. Requirements fit

Against the five goals stated in `roadmap/00_why_and_goals.md`, plus the cross-cutting goal from the
same document.

| # | Requirement | Verdict |
|---|---|---|
| 1 | Make precise edits (resize / recolor / rename in place) | **Partially works** |
| 2 | Get metadata — open drawing, and many at once | **Works** |
| 3 | Change document-level things (names, header/layer colors) | **Partially works** |
| 4 | Work on multiple projects | **Works** (new path); legacy path unchanged |
| 5 | Persistent queryable multi-file index | **Works, narrowly** |
| — | One consistent preview / keep / revert across every workflow | **Does not work** |

### R1 — Precise edits · Partially works

Real in-place mutation exists and is well-guarded: `HandleToObject` + property assignment
(`modification_executor.py:31-40`), no delete/recreate, with an unsaved-doc check, an index-freshness
hash check, a live-vs-indexed geometry check, a units check, a read-back assertion after assignment,
and a post-save re-extraction confirming the value persisted.

**But the supported entity set is very small:**
- Length resize: **LINE only.** POLYLINE and INSERT/block are rejected at plan time and again at
  execute time.
- Radius resize: **CIRCLE and ARC only**, XY-plane only.
- **3D solids, polylines, blocks, ellipses, splines and dimensions cannot be resized at all** — there
  is no scale or stretch operation anywhere in the codebase.
- Recolor is ACI integer 0–256 only. No RGB / TrueColor.
- "Rename" of an entity means setting its TEXT/attribute string, not a name property.
- Requires the file to be inside a registered, scanned, hash-current project. An arbitrary file on
  disk cannot be edited this way.
- **Requires AutoCAD running.**

The old delete-and-redraw path the roadmap was written to replace is still live and untouched:
`POST /api/autocad/edit` → `edit_executor.py:136` → `_delete_entity_by_handle:93` (`entity.Delete()`),
with no backup and no revert.

### R2 — Get metadata · Works

Both halves function. Live inspection (`GET /api/autocad/inspect`) honours an explicit
`target_dwg_path` and otherwise falls back to `ActiveDocument`; it requires AutoCAD. Multi-file
scanning (`POST /api/projects/{id}/scan`) needs **no AutoCAD**, runs in a process pool with
crash-isolation retry, and correctly re-extracts 0 files on an unchanged rescan.

**Gap:** DWG scanning raises `RuntimeError` unless `ODA_FILE_CONVERTER` is set. It is not set in
`.env`, not in the README, and not in the startup script — so **the offline index is effectively
DXF-only today**.

### R3 — Document-level changes · Partially works

- **File name:** `RENAME_FILE` renames the file **on disk**, same folder, extension preserved, no
  overwrite, with the DB row updated transactionally and filesystem rollback on failure. Verified
  end-to-end. **Runs without AutoCAD.** It does not change any internal drawing name — AutoCAD has no
  separate settable document name.
- **Document properties:** SummaryInfo Title / Author / Subject / Keywords / Comments /
  RevisionNumber plus custom keys. Requires AutoCAD.
- **Layer color: implemented** — `SET_LAYER_COLOR` sets `doc.Layers.Item(layer).Color`. ACI 1–255
  only. Requires AutoCAD.
- **"Header color": not implemented as a concept.** `project_planner.py:35-36` instructs the model to
  return `CLARIFY`, which becomes a `ValueError` → HTTP 409. The user gets an error, not a follow-up
  question.
- **Real hole:** `DXFExtractor._parse` (`dxf_extractor.py:47-49`) extracts **no layer table and no
  SummaryInfo**. So layer-color and document-property edits are the only operations *not* re-verified
  after save, and neither is ever queryable from the index.

### R4 — Multiple projects · Works on the new path

Projects are registered with a unique root index; every new-path document is resolved by absolute
path via `get_document`; the test suite actively enforces the rule (`fake_cad.Acad.ActiveDocument`
raises `AssertionError("Implicit active-document targeting is forbidden")`); operations outside the
project root are rejected; overlapping roots are disambiguated by `project_id`. A working UI exists in
`project-chat.js`.

**Not fixed:** the legacy workflows still default to whatever is open — `sketch.py:402`, `pid.py:108`,
`cad3d.py`, `autocad_edit.py:43` all accept an *optional* `target_dwg_path` and fall back to
`ActiveDocument`. `place_symbol`, `title_block` and `line_list` have no project concept at all.

### R5 — Persistent multi-file index · Works, narrowly

The index itself is sound and is the best-tested area of the project (43 tests against real DXF
files). Verified live: tag lookup returned entities across two files with no file opened; spatial
proximity search returned neighbours with `distance_mm` from the R*Tree.

**Hard limits:** only two query shapes are exposed — `?tag=` exact-match and `nearby?tag=`. There is
no "list entities in drawing X", no filter by type or layer or block, no free-text search, and no way
to read back `drawing_metadata` or `entity_properties`. Tags come only from `TAG`/`COMPONENT_TAG`/
`P_TAG` attributes or `TAG=` XData — **drawings that label components with plain TEXT index no tag at
all**, and are therefore invisible to every query and every edit.

### Cross-cutting — preview / keep / revert · Does not work

| Workflow | Backup before mutating | Preview | Revert |
|---|---|---|---|
| Sketch `/api/sketch/approve` | **No** | Yes (DXF preview) | **No** |
| P&ID `/api/pid/approve` | **No** | Token only | **No** |
| CAD3D `/api/cad3d/approve`, `/edit` | **No** | Token + scene store | **No** |
| Vessel `/api/generate-vessel/confirm` | **No** | Yes (extraction review) | **No** |
| Title block `/api/title-block-update` | **Yes** | `DRY_RUN` flag | Manual file copy only |
| Place symbol `/api/place-symbol` | **No** | `dry_run` flag | **No** |
| `/api/autocad/edit` | **No** | `auto_execute=false` | **No** |
| Project ops (changeset) | **Yes**, integrity-checked | Yes, before/after per item | **Yes** — but see §3.1–3.3 |

Four distinct token caches remain verbatim (`sketch.py:40`, `pid.py:19`, `cad3d.py:42`,
`vessel.py:37`). **ChangeSet is a fifth mechanism, not a unification.** One of eight mutating
workflows is revertible — and that one has three ways to become permanently stuck (§3.1–3.3).

---

## 3. Critical findings

### 3.1 `keep()` and `revert()` share one guard — any post-apply save bricks the drawing ✅
`src/cad/changes.py:172, 188-191`

`_check_files` enforces "current file must still hash to `after_hash`" for **both** `keep` and
`revert`. That is correct for `revert` (don't clobber later work) but wrong for `keep`, which writes
nothing and only marks the changeset accepted.

An engineer applies an AI resize, then opens the drawing in AutoCAD, adds a note and saves. Now:

```
keep   REFUSED -> Drawing changed after this changeset; refusing to overwrite later work
revert REFUSED -> Drawing changed after this changeset; refusing to overwrite later work
rescan -> {'extracted': 1}        # does not help
later edit BLOCKED -> Resolve the existing pending changeset for this drawing first
```

The changeset is stuck at `pending` forever, and the conflict check at `changes.py:99-102` locks that
drawing out of **every future edit**. Recovery requires manual SQL. No API route exposes a discard or
force path. **No test covers this** — the existing test asserts the revert refusal is intended, but
never calls `keep` afterwards nor checks the drawing is still editable.

### 3.2 Crash between COM save and `_record_file` leaves the edit applied and un-revertable
`src/cad/changes.py:109`, consumed at `:189`

`change_set_files` is committed with `after_hash NULL` and only backfilled *after* the file has
already been written and saved. A hard kill in that window makes
`expected = item["after_hash"] or item["before_hash"]` fall back to the **pre-edit** hash and compare
it against the **post-edit** file — so revert is refused in exactly the case it exists for, and a new
changeset is blocked. Verified by raising `KeyboardInterrupt` inside `_record_file` to reproduce the
same DB state a hard kill produces.

### 3.3 In-place revert interrupted after `os.replace` — disk correct, DB stuck forever
`src/cad/changes.py:187, 251`

The resumable-revert fix in `fixes/03` covers only the **rename** case: `resuming_revert` requires
`not current.exists()` and `already_restored` requires `original != current`. For a normal in-place
edit `original == current`, so neither applies. If the process dies after `os.replace` but before the
DB update, the file on disk is already correctly restored but its hash matches `before_hash` while
the guard expects `after_hash` — retry fails permanently and the changeset is stuck at `reverting`,
blocking all future changesets on that drawing.

**Common root cause for 3.1–3.3:** `_check_files` has no notion of "the file already matches a state
we know is safe." Hashing `current` against `before_hash` as well as `after_hash`, and dropping the
freshness check from `keep` entirely, would close all three.

### 3.4 Delete-then-save with no backup, save not gated on errors ✅
`src/framework/commands/edit_executor.py:203`

`execute_edit_plan` deletes entities by handle first (`:164-179`), delegates the re-adds (`:186-192`),
then calls `doc.Save()` **unconditionally** (`:203`). `backup_file()` is never called on this path.

`POST /api/autocad/edit` with `save=true` and `{"delete_handles": ["2A7","2A8"], "commands": [...]}`:
the deletes succeed, `execute_commands` then fails, and `doc.Save()` still commits the deletions to
disk. **The entities are permanently gone, the replacements were never drawn, and no backup exists.**
Every existing failure test passes `save=False`, so none of them catch it.

### 3.5 Same shape in the other two executors ✅
`src/framework/commands/executor.py:510` and `src/framework/cad3d/autocad_3d_executor.py:687`

Both save unconditionally after a partially-executed batch, with no backup. `continue_on_error`
defaults to `True`, and `/api/sketch/approve` declares `save: bool = True` (`sketch.py:55`) — so 47 of
50 commands succeeding means a half-drawn P&ID is written over the real file. The CAD3D executor has
the same pattern with no `StartUndoMark`/`EndUndoMark` anywhere in the repo (zero matches).

### 3.6 Additions are delegated to the wrong document ✅
`src/framework/commands/edit_executor.py:188`

Additions are delegated with `target_dwg_path=None`, so `executor.py:482` resolves
`acad.ActiveDocument` — **not** the document `edit_executor` opened at `:42`. No `doc.Activate()`
happens before delegation (it only runs at `:220`, after the save). With drawing B focused and a
request targeting drawing A: deletions land in A, new geometry lands in B, and `doc.Save()` saves A
only. The reported entity counts are read from A, so they also lie.

---

## 4. High-severity findings

### AI planning layer

**4.1 The CAD3D move parser reads the distance out of the component tag ✅**
`src/ai/cad3d_edit_planner.py:246`

```
'move P-101 up 500 mm'      -> [0, 0, 101]     expected [0, 0, 500]
'shift T-101 left 250'      -> [-101, 0, 0]    expected [-250, 0, 0]
'move V201 down 300 mm'     -> [0, 0, -201]    expected [0, 0, -300]
'move the pump up 500 mm'   -> [0, 0, 500]     correct — name has no digits
```

Only the distance-first word order (`"1000 mm to the right"`) parses correctly. Since virtually every
engineering tag contains digits, the broken case is the common one. When the AI planner fails,
`plan_cad3d_edit_resilient` falls back to this parser and silently moves the component by the numeric
part of its own tag, reporting success.
**`tests/framework/test_cad3d_edit_planner.py:95` uses the exact broken phrasing** but asserts only
`component_id`, never the delta. Its sibling `delete` and `update` tests assert their full payloads.

**4.2 Output token cap truncates any non-trivial sketch**
`src/ai/client.py:130`

`_resolve_max_tokens` defaults the **output** cap to 800 tokens. Every 2D command path uses that
default, while `command_generator.py:40` tells the model "Do not output more than 1000 commands." A
61-command sequence measures ~1,390 output tokens — already 1.7× over. The response is cut mid-JSON,
both retries hit the same cap, and the user gets
`502 AI returned invalid JSON: Expecting ',' delimiter` — a token-budget problem misdiagnosed as a
model formatting problem. Aggravating: `client.py:179` never inspects `finish_reason`, so a `"length"`
truncation is indistinguishable from malformed output.

**4.3 `NaN` / `Infinity` pass command validation ✅**
`src/framework/commands/schema.py:382`

`validate_command_sequence` has no `allow_nan=False` guard (unlike `operation_schema.py:43`), and
`client.py:90` uses bare `json.loads`, which accepts `NaN`/`Infinity` literals. Confirmed
empirically: a `CIRCLE` with `center=[NaN, 0]` and `radius=Infinity` returns **zero validation
errors**. `Infinity` passes `exclusiveMinimum: 0`; coordinates are unconstrained. Such a command
validates, previews, is approved, and reaches `msp.AddCircle`, poisoning `$EXTMIN`/`$EXTMAX` on a
saved file.

**4.4 Edit-plan retries are wasted on a permissive schema stub**
`src/ai/cad3d_edit_planner.py:44-55`, used at `:140`

The schema handed to `ask_ai` is a local stub (`"operations": {"type":"array","minItems":1}`,
`additionalProperties: true`) that accepts almost anything, while the schema actually enforced is
`validate_cad3d_edit_plan`. A malformed operation validates on attempt 1, so the two retries with
error feedback are never spent — then the real validator rejects it and the failure falls through to
the broken regex fallback of 4.1.

**4.5 Retries cannot repair, because the model never sees its own output**
`src/ai/client.py:194-206`

The retry appends a user message saying "Your previous response failed validation" but never appends
the assistant's failing output — verified message roles on attempt 2 are `['system','user','user']`.
At `temperature=0`, retries are re-rolls, not repairs. Separately, the `except Exception` at `:188`
catches transport errors (`AuthenticationError`, `RateLimitError`), burns a retry on them, and
relabels them `AIResponseError("AI failed after retry")` — a config or network failure reported as a
response-format failure.

### Drawing correctness

**4.6 `AddEllipse` is given an absolute point where AutoCAD expects a relative vector ✅**
`src/framework/commands/executor.py:246`

AutoCAD COM `AddEllipse(Center, MajorAxis, RadiusRatio)` takes MajorAxis as a vector **relative to
center**. `preview.py:142-146` correctly computes `endpoint - center`; the executor passes the raw
absolute point. With `center [1000,500]`, `major_axis_endpoint [1100,500]`, `ratio 0.5`, the preview
shows a 200-unit ellipse at (1000,500) while AutoCAD draws one with a ~2,236-unit major axis rotated
~26°. **The user approves one thing and a different thing is drawn.** No ELLIPSE test exists.

**4.7 The P&ID DOWN flow arrow is malformed ✅**
`src/framework/pid/symbols.py:528`

Uses `y + width` for its base corners where every other direction uses `half`. Measured at size 100:

```
RIGHT  bboxX=(-45,45)  bboxY=(-26,26)
LEFT   bboxX=(-45,45)  bboxY=(-26,26)
UP     bboxX=(-26,26)  bboxY=(-45,45)
DOWN   bboxX=(-26,26)  bboxY=(-45,26)   <- 71 long, asymmetric
```

It appears in the **default** template (`P_DRAIN` has `flow_direction: "DOWN"`).
`tests/framework/test_pid_symbols.py:140` parametrizes all four directions but asserts only
`command == "POLYLINE"` and `closed is True` — never the points.

**4.8 No shipped P&ID template tags any pipe or valve**
`src/framework/pid/component_templates.py:50-124, 154-198, 230-255`

`fixes/01` gave pipes and valves a `tag` parameter, but **nothing ever passes one.** Rendering the
default template produces **80 commands, 5 tagged** — all 5 from the vessel and instrument bubbles.
26 LINEs, 25 POLYLINEs, 2 ARCs and 1 CIRCLE carry no tag. The exact scenario `fixes/01` was written
for — "generate a P&ID, then ask to resize pipe P-101 later" — still fails end-to-end on the live
planner path. Same omission in `component_examples.py`.

**4.9 Vessel view label collides with the BOM table**
`src/parametric/vessel/render.py:131` vs `sheet.py:198`

The "FRONT VIEW" label is hardcoded at `origin_y - 4300.0`, but the sheet-layout extent estimate uses
`front_y_min = -shell_or - 2550.0` — 740 mm short. Rendering all five shipped examples puts the
"FRONT VIEW" text **inside the nozzle BOM table box for 4 of 5** (V201, V203_LONG, V204_END_NOZZLES,
V205_CLUSTERED). No test renders a sheet and checks for collisions.

**4.10 Vessel saddle uses the cross-section profile in the longitudinal view**
`src/parametric/vessel/geometry.py:164-181`, drawn at `draw_front_view.py:291-314`

`compute_saddle_geometry` builds the saddle top contour as `-sqrt(R² - x_offset²)` using the **axial**
offset. That is the side-view profile, but it is only ever drawn in the **front/longitudinal** view,
where the shell bottom is a straight line at `y = -R`. Measured (ID=2000, t=10): the saddle's top
corners poke **133 mm into the shell** at width 1000. Meanwhile `draw_side_view.py:264-269`, where
that arc belongs, draws a flat-topped trapezoid. The two are effectively swapped.

### 3D CAD

**4.11 CAD3D execution is not serialized ✅**
`src/framework/cad3d/autocad_3d_executor.py:616`

Only four functions carry `@serialized`: `scanner.py:52`, `inspector.py:229`,
`edit_executor.py:136`, `executor.py:462`. `execute_cad3d_scene` is not among them and never touches
`CAD_LOCK`, despite `fixes/04` claiming to unify write serialization "across legacy sketch/P&ID/CAD3D
/title-block writes." Two concurrent sync route handlers run on separate threadpool threads, so
`/api/cad3d/approve` can interleave COM calls with any other request into one AutoCAD session.
`src/use_cases/update_title_block.py:61` is likewise unprotected.

**4.12 Diagonal pipe segments silently degrade to hairlines**
`src/framework/cad3d/autocad_3d_executor.py:550-559`

`_add_axis_aligned_pipe_cylinder` raises on any non-axis-aligned segment; `_execute_pipe_run_3d`
catches **bare `Exception`**, draws an `AddLine` instead, increments `created`, and reports nothing.
Executing the default extended template, three separate pipe runs each come out half solid tube and
half hairline, with `ok: true` and no diagnostic field. The same handler also swallows genuine COM
failures.

**4.13 Valve orientation is validated, used for ports, then ignored when drawing**
`src/framework/cad3d/autocad_3d_executor.py:359-360`

`_execute_valve_placeholder_3d` maps `length→X, width→Y, height→Z` unconditionally with no
`Rotate3D`, while `routing.py:249-260` places ports along the **orientation axis**. Confirmed against
shipped templates: `dual_pump_skid`'s `XV_P101_SUC` is `orientation="Y"` with ports on the Y axis,
but the box's 300 mm extent is drawn on X. A Z-oriented valve is worse — the pipe visibly passes
through or stops short of the body.

**4.14 A read-only scene fetch hijacks `get_latest()`**
`src/framework/cad3d/scene_store.py:201`

`get()` sets `self._latest_token` on every cold disk load. After a server restart, opening
`GET /api/cad3d/state/{OLD}` to look at an old scene makes a subsequent `POST /api/cad3d/edit` with
no token (which falls back to `get_latest()`) apply the edit — and any `execute: true` — to the
**old** scene.

### API layer

**4.15 Audit rows stuck at `status="started"` forever — unauthenticated DB growth**
`src/api/main.py:298`

`AuditJobMiddleware` calls `log_job_start()` as soon as the path matches, but `log_job_end()` only
runs from the endpoint wrapper. Any request that never reaches the endpoint leaves a permanent orphan
row. Reproduced:

```
POST /api/pid/generate {"nope":1}  -> 422, row: pid_generate status=started, timestamp_end=NULL
GET  /api/pid/generate             -> 404, row: pid_generate status=started, timestamp_end=NULL
```

A loop of `GET /api/pid/generate` writes one permanent row per request, and `/api/jobs?status=started`
stops meaning anything.

**4.16 `/api/cad3d/edit` mints a token it never consumes**
`src/api/routes/cad3d.py:325`

`cad3d_edit` writes `_CAD3D_CACHE[edited_token]` and, unlike `cad3d_approve:496`, never pops it — even
after `execute=true` succeeds. This is exactly the hole `fixes/06` closed on the other two routes, and
it was missed. With `create_new_token: true` each edit mints a fresh, never-expiring token.

**4.17 Token caches still have no expiry**
`src/api/routes/pid.py:19`, `src/api/routes/cad3d.py:42`

`fixes/06` fixed the *replay-on-success* half but never implemented the *eviction* half its own
comment names. `created_at` is stored and never read. The normal "regenerate until I like it" loop
retains every rejected multi-hundred-KB plan for the process lifetime.

| Workflow | Replay after success | Unbounded cache |
|---|---|---|
| `/api/pid/approve` | Fixed | **Still broken — no TTL** |
| `/api/cad3d/approve` | Fixed | **Still broken — no TTL** |
| `/api/cad3d/edit` | **Still broken — never pops** | **Still broken** |
| `/api/sketch/approve` | Correct | Correct — 10-min TTL |
| `/api/generate-vessel/confirm` | Correct | Correct — 10-min TTL |

**4.18 Stored XSS in the jobs page ✅**
`src/api/static/jobs.html:161`

`row.innerHTML` interpolates `truncateError(job.error_message)` raw; `truncateError` only slices, it
never escapes. `job.source` and `job.use_case` at `:159-160` are likewise raw. `sketch.html` does this
correctly in 60 places via `escapeText`; `jobs.html` was never updated.

Chain: `POST /api/projects` with a malicious `root_path` → `register_project` raises `ValueError`
containing it → `projects.py:26` re-raises as `HTTPException(409, str(exc))` →
`_log_wrapped_route_error` stores the string in `jobs.error_message` → any operator opening
`/jobs.html` executes it, same-origin with the API that drives AutoCAD.

---

## 5. Medium and low findings

**API / routes**
- `projects.py:43, 74` — `projects()` and `changes()` bypass the hardened `respond()` helper, so the
  `sqlite3.OperationalError` handling added in `fixes/07` does not protect them. `GET /api/projects`
  is the most-hit route in the app (`project-chat.js:61` calls it on every page load).
- `main.py:34` — `AUDIT_ROUTE_MAP` is keyed by path only, never method, and `/api/projects` has both
  a GET and a POST. Verified: `GET /api/projects` logs `use_case="project_register"`. Every sidebar
  load forges an audit record claiming a project was registered.
- `vessel.py:180, 199, 214, 231, 244` — every failure returns HTTP 200 with `{"ok": false}`,
  including `AutoCADNotRunningError`. Every other route raises 503 for that. Any client keying off
  the status code treats total failure as success.
- `sketch.html:904, 921, 1343, 1436, 1532` — `buildResultHtml` and its P&ID/CAD3D siblings hardcode
  the titles "Drawing built in AutoCAD." / "Done — P&ID built in AutoCAD." and are called unchanged
  on the `!data.ok` branch, distinguished only by a red border. A drawing that wrote 3 of 40 commands
  reports as built.
- `sketch.py:649`, `pid.py:106`, `place_symbol.py:37` — live-drawing writes not serialized by
  `CAD_LOCK`; none of the live-write use cases back up before mutating.

**Storage / orchestration**
- `changes.py:97-110` — `backup_file()` runs a filesystem copy **inside** `BEGIN IMMEDIATE`. Since
  `jobs.db` is the same SQLite file as the project index, a concurrent request's `log_job_start`
  blocks on the 2 s timeout, raises `OperationalError`, and is swallowed by `_warn`. Measured: a
  backup held the write transaction for 2.25 s and the concurrent audit row was lost.
- `jobs.py:28-29` — `_timestamp_now()` uses naive local `datetime.now()` while the rest of the
  codebase uses UTC. `duration_seconds` subtracts two local timestamps, so a job spanning a DST
  change is off by an hour or negative. Nothing prunes the `jobs` table, and it shares a file with
  the live entity index, so unbounded audit growth degrades index queries.

**Execution framework**
- `executor.py:476-480`, `edit_executor.py:40-47` — both call `acad.Documents.Open()` directly rather
  than `session.get_document`, skipping the `is_file` check, the already-open lookup and the identity
  check — and **never `Close()`**. Every approve with a `target_dwg_path` leaves another drawing open;
  they accumulate across requests. Same issue at `autocad_3d_executor.py:644-647`.
- `session.py:23` — `if document.FullName` tests truthiness, but `canonical_path` raises `ValueError`
  for a non-absolute path. A never-saved "Drawing1.dwg" may abort the scan with an error that lies
  about the cause. *Trigger unverified — AutoCAD not available — but the guard mismatch is certain.*
- `backup.py` — no restore function, no copy verification, no retention. `changes.py:106`
  hash-verifies its backup; `modification_executor.py:236` does not. `BACKUP_ROOT` is inside the repo
  working tree and grows without pruning.
- `executor.py:348-371` — `DIM_LINEAR` calls `AddDimAligned` (true point-to-point distance) while
  `preview.py:209-213` draws a horizontal dimension. Name and preview both misrepresent the result.
- `executor.py:79, 178-193` — a `LAYER` command with `layer_name: "0"` returns early, silently
  discarding the schema-accepted `color` and `linetype`.
- `dwg_export.py:46-47` — `_is_busy_error` returns `True` for **any** `AttributeError`. It does not
  permanently swallow (the error is re-raised after the loop), but it costs a 5.0 s stall plus
  misleading "AutoCAD busy" spam per genuine attribute error. Worst case: `_ensure_tag_app_registered`
  is called for every tagged command and is wrapped in a bare `except Exception: pass`.
- `autocad_client.py` — focus-based, no `CoInitialize`, no `CAD_LOCK`, unverified `Save()`,
  `close_drawing(save_changes=True)` by default. Only reachable from `src/scratch/`, so effectively
  dead, but it is a loaded gun. Still defines a **duplicate `AutoCADNotRunningError`** ✅ that
  `except autocad_client.AutoCADNotRunningError` would silently fail to catch.

**Schema gaps that reach the executor** (all verified to pass validation with zero errors)
- CAD3D `scene_schema.py:28` — NaN coordinates reach `AddBox`/`AddCylinder` verbatim.
- CAD3D — no component-id uniqueness constraint on the generate→approve path; `get_component_by_id`
  returns the first match, so a pipe silently routes to the wrong twin.
- CAD3D — `visual_style: "centerline"` + `draw_centerline: false` yields `created == 0`, i.e. a
  schema-legal scene guaranteed to fail.
- `components/equipment.py:43, 93, 138, 176` — `to_scene_component()` emits `"tag": self.tag`
  unconditionally, so an untagged component makes `to_scene_data()` raise on `tag: None`.

**Vessel multi-view inconsistencies**
- `draw_side_view.py:261` — hardcodes support height, ignoring `Saddle.height_mm`; the front view uses
  the real value. With ID=2000 and `height_mm=1800` the same support is drawn 800 mm taller in the
  front view. Masked only because the shipped examples happen to set `height = 0.5*D`.
- `draw_side_view.py:208-228`, `draw_top_view.py:190` — `Nozzle.radial_angle_degrees` is honoured only
  by the front view. A SIDE_FRONT nozzle at 45° is drawn at y=714 in the front view and y=0 in the
  side view.
- `draw_dimensions.py:87-130` vs `geometry.py:65-66` — the dimension uses `ID/4` while the head is
  drawn with `(D/2 + t)/2`. See §6.3.
- `draw_dimensions.py:234` — bottom-nozzle dimensions stack with no awareness of the fixed T-T dim or
  the callout row; for V203_LONG two dimension lines land 50 mm apart with 120-high text.

**Dead / dormant**
- `scene_renderer.py:88, 98-108` — the older non-component P&ID path calls symbol builders with no
  `tag=` at all. Dormant (no caller outside `framework/pid`) but exported.
- `command_orchestrator.py:83, 85` (and two siblings) — `_repair_for_schema_errors` passes the same
  object as both `bad_output=` and `previous_command_sequence=`, sending the entire invalid sequence
  **twice in one prompt**. Measured 19,587 chars containing `"command": "LINE"` 120 times for a
  60-command sequence, on top of a 13,297-char schema dump — then asked to re-emit the whole drawing
  inside the 800-token cap of §4.2.
- `command_verifier.py:85` — embeds the complete generated sequence, unbounded; `COMMAND_SCHEMA` has
  `minItems: 1` and **no `maxItems`**.
- `consistency_explainer.py:115` — the AI's `overall_status` and `issue_count` are returned verbatim
  with no cross-check against the deterministic `mismatches` list. A PASS envelope over 5 real
  mismatches writes "Overall Status: PASS / Issue Count: 0" into the **manager-facing** summary file
  while the JSON API still says FAIL. One assertion would close it.

---

## 6. Can the test suite be trusted?

**Partially.** Confirmed baseline: **1003 passed, 10 skipped, 122 s.** No order-dependence was found
(five files run individually matched their full-suite results). All 10 skips are benign live-AI gates;
none hides an AutoCAD or ODA path.

But the suite is strongest where it matters least and absent where it matters most.

### 6.1 The COM fake cannot exercise the code that writes drawings
`tests/project/fake_cad.py:100-102`

`ModelSpace` returns a **plain Python list**. Real `AcadModelSpace` is a COM collection with
`AddLine`/`AddCircle`/`AddArc`/`AddEllipse`/`AddText`/`AddDimAligned`/`AddLightWeightPolyline`. So
`executor.py:484` and **every creation branch at lines 204-354** can never run against this fake. The
untracked `test_pid_component_identity.py` partially mitigates this with a `_CreatingModelSpace`, but
only for `AddLine`, `AddLightWeightPolyline` and `AddText` — **circles, arcs, ellipses, dimensions and
MText have no COM-shaped creation test at all.**

What the fake *does* get right: `SetXData` correctly unwraps a real `VARIANT` via `.value` (verified
against installed pywin32 — `VARIANT` is not iterable, `list(v)` raises `TypeError`), and the
`ezdxf`-backed save/reload round-trip is genuine. Error types diverge though: the fake raises
`KeyError` where real COM raises `pywintypes.com_error`, so no test ever sees a real `com_error`.

### 6.2 The fake's inaccuracy forced production code to be stubbed out
`tests/project/test_modification.py:24`

`monkeypatch.setattr(engine, "point", tuple)` replaces `session.py:63-66`
(`VARIANT(VT_ARRAY|VT_R8, ...)`) with a plain tuple for **all 27 tests in the file** — the entire
in-place-edit surface. Real AutoCAD *requires* a VARIANT for point properties and rejects a bare
tuple. So `session.point` has zero effective coverage, and the file proves nothing about whether real
coordinate assignment works.

### 6.3 A test named for consistency is a tautology that hides a real defect
`tests/parametric/test_view_consistency.py:78`

`test_overall_length_used_by_views_is_consistent` **never calls any source function.** It computes
`V201.internal_diameter_mm / 4.0` inline in the test body and asserts `2000/4 == 500`. It is pure
arithmetic and cannot fail regardless of the source code.

The conflict it was named to catch is real and live:
- `draw_front_view.py:125` / `draw_top_view.py:126` draw the head using `minor_axis_mm` = **505**
- `draw_dimensions.py:87-90` annotates overall length using `ID/4` = **500**
- `geometry.py:103, 106` places head nozzles at ±**500**

Measured: drawn overall length **5510 mm**, dimension text says **5500 mm**, and head nozzles sit
5 mm off the head they attach to.

### 6.4 Running the API tests corrupts the real `jobs.db`

Proven by hash. Running `tests/api/` alone (173 passed) changed `jobs.db` md5 `7d25e945…` →
`901cb300…`, size 10,424,320 → 10,563,584 bytes:
- `jobs` rows: **10,275 → 10,410** (135 test rows in production job history)
- **16 tables created that did not exist**: `projects`, `drawings`, `entities`, `entity_geometry`,
  `entity_properties`, `change_sets`, `change_set_items`, `change_set_files`, `spatial_index*`,
  `relationships`, `validation_results`, …

`tests/project/conftest.py` monkeypatches `db.DB_PATH` and `backup.BACKUP_ROOT`. `tests/api/` has no
equivalent, and `src/logging/db.py:6` hardcodes `DB_PATH` with no env override.

### 6.5 Coverage gaps

**23 of 118 source modules (19%) are referenced by no test.** Those touching AutoCAD or the
filesystem:

```
src/use_cases/consistency_check.py            768 loc   COM + FS
src/parametric/vessel/sheet.py                622 loc   COM
src/parametric/vessel/draw_top_view.py        449 loc   COM + FS
src/parametric/vessel/draw_dimensions.py      404 loc   COM
src/parametric/vessel/draw_front_view.py      401 loc   COM + FS
src/use_cases/setup_symbol_test_blocks.py     376 loc   COM
src/parametric/vessel/draw_side_view.py       370 loc   COM + FS
src/use_cases/update_title_block.py           243 loc   COM + FS
src/use_cases/generate_vessel.py              216 loc   FS
src/use_cases/consistency_check_ai.py         204 loc   FS
src/use_cases/line_list_extract.py            182 loc   COM + FS
src/autocad_client.py                         133 loc   COM + FS
src/parametric/vessel/batch_render.py         106 loc   COM + FS
src/use_cases/verify_title_blocks.py           75 loc   COM + FS
```

**The entire vessel drawing renderer (~2,350 loc) is untested** — which is precisely why §6.3's
defect, §4.9's collision and §4.10's swapped profile all survive.

### 6.6 Half the suite runtime is real sleep

~65 s of 122 s is `time.sleep` from `_com_retry` exhausting its `0.5+1.0+1.5+2.0` backoff.
`test_pid_component_identity.py` costs ~10 s per test (two exhaustions each); eight
`test_autocad_3d_executor.py` tests cost ~5 s each. `tests/framework/test_autocad_inspector.py:129`
already stubs `_com_retry` — the correct pattern the other files don't use.

---

## 7. Configuration and operations

### Clean — verified
- **No committed secrets.** `git grep` for key patterns across all tracked files: zero hits. `.env` is
  untracked and gitignored, holding 4 keys read safely via `load_dotenv()` + `os.getenv`.
- **`jobs.db` is not committed** and is gitignored along with its WAL/SHM files.
- **No committed binaries or DWGs.** 249 tracked files; largest binary is a 20 KB PNG.
- **Dependencies fully pinned** (`==`, 48 packages), all current or near-current.
- **`GET /api/download/{filename:path}` is not vulnerable.** 11 traversal variants were probed —
  `../`, `..%2f`, `%2e%2e%2f`, double-encoded `..%252f`, `....//`, `C:/Windows/win.ini`,
  drive-relative, `//etc/passwd`, `%5C..%5C` — all returned 400/404. The `.resolve()` +
  `relative_to(OUTPUTS_DIR.resolve())` check is the real guard and it holds.

### Risks
- **Nothing from this entire effort is committed.** ✅ `docs_analysis/`, `fixes/`, `roadmap/`,
  `src/api/static/project-chat.js` (the project chat UI), both startup scripts, and 5 test files are
  all untracked — including `test_database.py` and `test_pid_component_identity.py`, the latter being
  the only COM-shaped creation coverage in the suite. A fresh clone or a stray `git clean` loses all
  of it.
- **No CI whatsoever** — no `.github/`, `.gitlab-ci.yml`, `Jenkinsfile`, `.circleci`. Nothing
  enforces the 1003 tests. Combined with the point above, correctness rests entirely on local runs.
- **Both startup scripts hardcode `C:\RC-Projects\autocad-ai\autocad-ai`** ✅ while the project is on
  `F:\`, so neither runs. The `.bat` is inert. The `.ps1` is the risky one: at lines 112-118 it
  renames `venv/` to `venv-broken-<timestamp>` and rebuilds whenever its dependency probe fails, and
  at 91-97 it overwrites `venv/pyvenv.cfg`. Nothing is hard-deleted and it cannot reach `F:\` today,
  but correcting the path would arm it. It also uses `Read-Host`, so it blocks non-interactively.
- **No `pytest.ini`/`pyproject.toml`** and therefore no `testpaths`. Bare `pytest` collects by
  scanning everything. `src/scratch/` contributes 0 items today, but `draw_circle.py`,
  `draw_shapes.py` and `test.py` call `GetActiveObject("AutoCAD.Application")` and
  `AddCircle`/`AddLine` **at module import time with no `__main__` guard**. One added `def test_…`
  away from pytest driving real AutoCAD. Nothing imports `src.scratch`; all 17 files are safely
  deletable.
- **No `.env.example`**, despite `.gitignore` carrying a `!.env.example` negation for it.
- `IMPLEMENTATION_LOG.md` is stale — records 956 passed against an actual 1003.

---

## 8. Recommended order of work

Ranked by "how much this protects real work per unit of effort."

1. **Commit everything.** All the analysis, fixes documentation, roadmap, the chat UI and 5 test files
   are untracked. Do this first; everything else is worth less if it can vanish.
2. **Add `backup_file()` + error-gated save to the three executors** (§3.4, §3.5). This closes the
   single largest data-loss class. Gate `doc.Save()` on `not errors`, or make `continue_on_error`
   default to `False` for destructive plans.
3. **Fix the `keep`/`revert` guard** (§3.1–3.3). Hash `current` against `before_hash` as well as
   `after_hash`, and drop the freshness check from `keep` entirely. This un-bricks the one revertible
   workflow and closes all three stuck-state bugs at once.
4. **Add a `conftest.py` to `tests/api/`** mirroring `tests/project/`'s isolation (§6.4). Running
   tests should not damage live data.
5. **Fix the CAD3D move parser** (§4.1) and assert the delta in its test.
6. **Fix `AddEllipse`** (§4.6) and the DOWN arrow (§4.7) — both are small, both silently produce wrong
   drawings.
7. **Escape `jobs.html`** (§4.18).
8. **Raise `max_tokens` and inspect `finish_reason`** (§4.2).
9. **Decide the strategic question below.**

---

## 9. The strategic question

Everything above is fixable. But the deepest finding is not a bug — it is that the roadmap built a
second application and left the first one running.

The old workflows are what a user reaches from the chat box. They are unbacked-up, unrevertible, and
they write to whatever drawing happens to be focused. The new workflow is safe but reaches only LINE,
CIRCLE and ARC, only inside a registered and scanned project, only via exact tag match, and only for
drawings whose components carry `TAG=` XData — which, per §4.8, **the app's own P&ID generator does
not produce for pipes or valves.**

So the two halves do not currently meet: the generator makes drawings the editor cannot address, and
the editor is reachable only for drawings the generator did not make.

Three viable directions:

- **Converge them.** Make the four legacy approve paths write through `ChangeManager` so they inherit
  backup and revert, and make the P&ID/CAD3D generators tag everything they draw. This is the option
  that actually delivers the roadmap's stated definition of done.
- **Gate the old paths.** Keep them, but make `save=True` require an explicit opt-in and always take
  a backup first. Cheapest path to "can't lose work."
- **Retire the old paths.** Route the chat UI exclusively through the new mechanism, and accept the
  capability regression until the operation set grows beyond LINE/CIRCLE/ARC.

The first is the most work and the only one that matches what was originally asked for.

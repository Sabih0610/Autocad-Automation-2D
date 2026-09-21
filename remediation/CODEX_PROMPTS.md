# Codex Prompts — One Issue Per Prompt

27 self-contained prompts. Hand Codex **one at a time**, in the order below where order is marked.
Each is written to work with no prior context, so you can paste it cold.

**After every prompt:** run `venv\Scripts\python.exe -m pytest tests/ -q`, confirm the numbers, and
commit before moving on. Baseline at time of writing: **1003 passed, 10 skipped**.

Full detail for any item: `docs_analysis/11_full_project_audit.md`.

| # | Issue | Urgency | Depends on |
|---|---|---|---|
| 1 | Gate saves on errors + back up first | **Urgent — active data loss** | — |
| 2 | Stored XSS in jobs.html | **Urgent — security** | — |
| 3 | CAD3D move parser reads digits from the tag | High | — |
| 4 | AddEllipse absolute vs relative vector | High | — |
| 5 | P&ID DOWN flow arrow malformed | High | — |
| 6 | NaN/Infinity pass validation | High | — |
| 7 | Token caches never expire | Medium | — |
| 8 | /api/cad3d/edit token never consumed | Medium | — |
| 9 | Audit rows stuck at "started" forever | Medium | — |
| 10 | Output token cap too low | Medium | — |
| 11 | Vessel head depth 505 vs 500 | Medium | — |
| 12 | tests/api writes the real jobs.db | High | — |
| 13 | fake_cad ModelSpace is a plain list | High | — |
| 14 | 65s of test runtime is real sleep | Low | 13 |
| 15 | ChangeSet stuck-states | **High** | 1 |
| 16 | One revert mechanism for all 8 workflows | High | 1, 15 |
| 17 | Tag all generated P&ID components | High | — |
| 18 | Expand the editable entity set | Medium | 17 |
| 19 | "Header color" dead end | Medium | — |
| 20 | Extract layer table + SummaryInfo | Medium | — |
| 21 | Retire implicit ActiveDocument writes | Medium | — |
| 22 | edit_executor delegates to wrong document | High | — |
| 23 | Opened documents never closed | Medium | — |
| 24 | Index query surface | Medium | — |
| 25 | TEXT-label association | Medium | 24 |
| 26 | ODA/DWG config + .env.example | Low | — |
| 27 | AUDIT_ROUTE_MAP ignores HTTP method | Low | — |

---

## 1 — Gate saves on errors, and back up first

```
In F:\RC-Projects\autocad-ai\autocad-ai (Python/FastAPI app driving AutoCAD via COM), three
executors can permanently destroy a user's drawing.

execute_commands / execute_command_sequence (src/framework/commands/executor.py:463,543),
execute_edit_plan (src/framework/commands/edit_executor.py:137) and execute_cad3d_scene
(src/framework/cad3d/autocad_3d_executor.py:616) all call doc.Save() without checking whether any
command failed, and none ever calls backup_file() from src/backup.py. continue_on_error defaults
True and /api/sketch/approve defaults save=True, so a plan where 47 of 50 commands succeed writes a
half-finished drawing over the real file with nothing to restore from.

edit_executor is the worst case: it deletes entities by handle FIRST (~line 164), delegates the
re-adds, then saves unconditionally at line 203. If the additions fail, the deletions are committed
forever.

CHANGES
1. In all three, take a backup via src/backup.py's backup_file() before the first mutating COM call,
   when save=True and a real file path is resolvable.
2. Gate every doc.Save() on there being no errors.
3. Return backup_path: str|None and backup_skipped_reason: str|None in each result dict.
4. Handle the unsaved/untitled ActiveDocument case explicitly — no path means no backup is possible.
   Do NOT silently skip; set backup_skipped_reason and comment your reasoning on whether saving
   should still be permitted there.
5. Add restore_file(backup_path, target_path) to src/backup.py, and make backup_file() verify its
   copy by hash. src/cad/changes.py:106 already does this inline — reuse that approach.

Do NOT change behaviour when save=False.

TESTS (use the fake COM double in tests/project/fake_cad.py):
- save=True + one failing command -> Save() NOT called, file byte-identical
- save=True + all succeed -> backup exists, its hash equals the pre-edit file's
- save=True on an unsaved document -> executes, result carries backup_skipped_reason
- save=False -> no backup, no save
- edit_executor: deletes succeed, additions fail, save=True -> Save() NOT called

VERIFY: venv\Scripts\python.exe -m pytest tests/ -q  (baseline 1003 passed, 10 skipped). Report exact
numbers. If a pre-existing test now fails, do not weaken it — explain the conflict and stop.
```

---

## 2 — Stored XSS in jobs.html

```
In F:\RC-Projects\autocad-ai\autocad-ai there is a stored XSS in the audit-log page.

src/api/static/jobs.html:161 does row.innerHTML with `${truncateError(job.error_message)}`
interpolated raw. truncateError (jobs.html:123) only slices the string, it never escapes. job.source
and job.use_case at :159-160 are equally raw.

Attack chain: POST /api/projects with a malicious root_path -> register_project raises ValueError
containing that string -> src/api/routes/projects.py:26 re-raises as HTTPException(409, str(exc)) ->
_log_wrapped_route_error stores it in jobs.error_message -> it executes when an operator opens
/jobs.html, same-origin with the API that drives AutoCAD.

src/api/static/sketch.html already solves this correctly — it has an escapeText helper used in about
60 places. jobs.html was never updated.

CHANGES: escape every server-supplied value interpolated into innerHTML in jobs.html. Reuse the same
escapeText approach sketch.html uses rather than inventing a second one. Audit the whole file, not
just the three lines named above.

TEST: a job row whose error_message contains `<img src=x onerror=...>` renders as inert text, not as
an element. Assert against the rendered DOM/HTML string, not just that the function was called.

VERIFY: venv\Scripts\python.exe -m pytest tests/ -q  (baseline 1003 passed, 10 skipped).
```

---

## 3 — CAD3D move parser reads the distance out of the tag

```
In F:\RC-Projects\autocad-ai\autocad-ai, the deterministic CAD3D edit fallback moves components by
the wrong distance.

src/ai/cad3d_edit_planner.py:246 — the move-parser regex matches the digits INSIDE the component
tag, so the tag number becomes the move distance. Verified by running it:

  'move P-101 up 500 mm'      -> [0.0, 0.0, 101.0]    expected [0, 0, 500]
  'shift T-101 left 250'      -> [-101.0, 0.0, 0.0]   expected [-250, 0, 0]
  'move V201 down 300 mm'     -> [0.0, 0.0, -201.0]   expected [0, 0, -300]
  'move the pump up 500 mm'   -> [0.0, 0.0, 500.0]    correct — name has no digits
  'move P-101 1000 mm to the right' -> [1000,0,0]     correct — distance-first form

Only the distance-first word order parses correctly. Nearly every engineering tag contains digits, so
the broken case is the common one. When the AI planner fails, plan_cad3d_edit_resilient falls back to
this parser and silently moves the component by the numeric part of its own tag, reporting success.

CHANGES: make the parser extract the distance from the distance token, not from the component tag.
Handle both word orders ("<tag> <direction> <distance>" and "<tag> <distance> to the <direction>").

CRITICAL — FIX THE TEST TOO: tests/framework/test_cad3d_edit_planner.py:95
(test_fallback_maps_tag_to_component_id) calls deterministic_edit_plan_from_request with the exact
broken phrasing "Move P-101 right 500" but asserts ONLY component_id == "P101" and never the delta.
That is why this bug survived. Its sibling delete/update tests assert their full payloads. Make this
test assert the delta. Do not add a new test alongside the weak one — repair it.

TESTS: cover all five phrasings above, asserting the full delta each time.

VERIFY: venv\Scripts\python.exe -m pytest tests/ -q  (baseline 1003 passed, 10 skipped).
```

---

## 4 — AddEllipse is given an absolute point, not a relative vector

```
In F:\RC-Projects\autocad-ai\autocad-ai, previewed ellipses and drawn ellipses differ.

AutoCAD COM AddEllipse(Center, MajorAxis, RadiusRatio) takes MajorAxis as a vector RELATIVE to the
center. src/framework/commands/executor.py:246 passes command["major_axis_endpoint"] raw — an
absolute point. src/framework/commands/preview.py:142-146 does it correctly, computing
(endpoint - center).

So with center [1000,500], major_axis_endpoint [1100,500], ratio 0.5: the preview shows a 200-unit
ellipse at (1000,500), while AutoCAD draws one with a ~2236-unit major axis rotated ~26 degrees. The
user approves one thing and a different thing is written to the drawing.

CHANGES: make the executor compute the major axis relative to the center, matching preview.py. Do not
change preview.py — it is the correct one.

TEST: there is currently NO ELLIPSE test in tests/framework/test_command_executor.py. Add one that
asserts the vector passed to AddEllipse equals (endpoint - center), with a non-origin center so the
bug would be caught. Also assert the executor and preview.py agree for the same command.

VERIFY: venv\Scripts\python.exe -m pytest tests/ -q  (baseline 1003 passed, 10 skipped).
```

---

## 5 — P&ID DOWN flow arrow is malformed

```
In F:\RC-Projects\autocad-ai\autocad-ai, one of the four P&ID flow-arrow directions draws wrong.

src/framework/pid/symbols.py:528 — the DOWN arrow uses `y + width` for its base corners where every
other direction uses `half`. Verified by running flow_arrow_commands at size=100:

  RIGHT  pts=[[45,0],[-45,-26],[-45,26]]    bboxX=(-45,45)  bboxY=(-26,26)
  LEFT   pts=[[-45,0],[45,-26],[45,26]]     bboxX=(-45,45)  bboxY=(-26,26)
  UP     pts=[[0,45],[-26,-45],[26,-45]]    bboxX=(-26,26)  bboxY=(-45,45)
  DOWN   pts=[[0,-45],[-26,26],[26,26]]     bboxX=(-26,26)  bboxY=(-45,26)   <-- 71 long, asymmetric

RIGHT/LEFT/UP are all 90 units and symmetric about the origin. DOWN is 71 and lopsided. It appears in
the DEFAULT template — P_DRAIN has flow_direction "DOWN".

CHANGES: make DOWN symmetric and the same length as the other three.

CRITICAL — FIX THE TEST TOO: tests/framework/test_pid_symbols.py:140 parametrizes all four directions
but asserts only command == "POLYLINE" and closed is True, never the points. That is why this
survived. Make it assert the actual point coordinates for all four directions.

VERIFY: venv\Scripts\python.exe -m pytest tests/ -q  (baseline 1003 passed, 10 skipped).
```

---

## 6 — NaN and Infinity pass command validation

```
In F:\RC-Projects\autocad-ai\autocad-ai, non-finite numbers reach AutoCAD.

src/framework/commands/schema.py:382 validate_command_sequence has no allow_nan=False guard — but
src/framework/commands/operation_schema.py:43 does, so the pattern already exists in this codebase.
Separately src/ai/client.py:90 uses bare json.loads, which accepts literal NaN and Infinity.

Verified: a command sequence containing
  {"command":"CIRCLE","center":[NaN,0],"radius":Infinity}
returns ZERO validation errors. Infinity passes exclusiveMinimum: 0, and coordinates are
unconstrained. Such a command validates, previews, is approved, and reaches msp.AddCircle — poisoning
$EXTMIN/$EXTMAX on a saved file, after which ZoomExtents and later extraction misbehave.

CHANGES
1. Reject non-finite numbers in validate_command_sequence. Follow operation_schema.py:43's approach.
2. Make src/ai/client.py:90 reject NaN/Infinity literals from the model rather than accepting them.

TESTS
- a sequence with NaN coordinates is rejected with a clear error naming the field
- a sequence with Infinity radius is rejected
- ordinary finite values still validate (no regression)
- client.py rejects a model response containing bare NaN/Infinity

VERIFY: venv\Scripts\python.exe -m pytest tests/ -q  (baseline 1003 passed, 10 skipped).
```

---

## 7 — Token caches never expire

```
In F:\RC-Projects\autocad-ai\autocad-ai, two in-memory caches grow without bound.

src/api/routes/pid.py:19 (_PID_CACHE) and src/api/routes/cad3d.py:42 (_CAD3D_CACHE) are plain dicts
with no TTL and no size cap. _PID_CACHE entries hold a full component_scene plus command_sequence;
_CAD3D_CACHE holds full scene_data. created_at IS stored but never read.

A previous fix made both pop their token on a successful approve, but never implemented eviction —
so the normal "generate, don't like it, regenerate" loop retains every rejected multi-hundred-KB plan
for the life of the process.

src/api/routes/sketch.py and src/api/routes/vessel.py already implement a correct 10-minute TTL purge.
COPY THAT PATTERN — do not invent a third cache policy.

CHANGES: add TTL-based eviction to both caches, matching sketch.py/vessel.py's approach and timeout.

TESTS
- an entry older than the TTL is purged and its token returns 404
- an entry within the TTL still works
- purging one expired entry does not evict a live one

VERIFY: venv\Scripts\python.exe -m pytest tests/ -q  (baseline 1003 passed, 10 skipped).
```

---

## 8 — /api/cad3d/edit mints a token it never consumes

```
In F:\RC-Projects\autocad-ai\autocad-ai, one route leaves a replayable execution token behind.

src/api/routes/cad3d.py:325 — cad3d_edit writes _CAD3D_CACHE[edited_token] and never pops it, even
after execute=true has already written the geometry into the live drawing. cad3d_approve at :496 pops
correctly on success; cad3d_edit was missed when that fix was applied.

Consequence: POST /api/cad3d/edit with execute=true writes to the drawing and returns edited_token.
That token can then be POSTed to /api/cad3d/approve to re-execute the same scene again. With
create_new_token=true each edit mints another never-expiring token.

CHANGES: make a successful cad3d_edit with execute=true consume its token, matching cad3d_approve:496.
A FAILED execution should keep the token so the caller can retry — that is the existing convention.

TESTS
- edit with execute=true succeeds -> the token is gone -> approving it returns 404
- edit with execute=false -> the token REMAINS (it has not been executed yet)
- edit with execute=true that FAILS -> the token remains so it can be retried
- existing tests at tests/api/test_cad3d_routes.py:362,492 assert the cache entry EXISTS; update them
  to match the corrected behaviour rather than deleting them

VERIFY: venv\Scripts\python.exe -m pytest tests/ -q  (baseline 1003 passed, 10 skipped).
```

---

## 9 — Audit rows stuck at "started" forever

```
In F:\RC-Projects\autocad-ai\autocad-ai, failed requests leave permanent orphan rows in the audit DB.

src/api/main.py:298 — AuditJobMiddleware calls log_job_start() as soon as the request path matches
AUDIT_ROUTE_MAP, but log_job_end() only ever runs from the endpoint wrapper. Any request that never
reaches the endpoint leaves a row at status="started" with timestamp_end NULL, forever.

Reproduced:
  POST /api/pid/generate {"nope":1}  -> 422, row: pid_generate status=started, timestamp_end=NULL
  GET  /api/pid/generate             -> 404, row: pid_generate status=started, timestamp_end=NULL

This is an unauthenticated unbounded-DB-growth primitive: a loop of GET /api/pid/generate writes one
permanent row per request. It also makes /api/jobs?status=started useless as a "currently running"
indicator.

CHANGES: ensure every job that is started is also ended, including on validation failures, 404s, 405s
and any path that bypasses the endpoint. The middleware already has a try/except/finally around
self.app(...) — the fix belongs there, not in the endpoint wrapper.

TESTS
- a 422 (schema validation failure) closes its job row with an error status
- a 404/405 on an audited path closes its row
- a normal successful request still closes its row exactly once (no double-end)
- an endpoint that raises still closes its row

NOTE: tests/api/ currently has no DB isolation and writes the real jobs.db. If prompt 12 has already
been done, use that isolation. If not, do NOT write these tests against the real jobs.db — isolate
them locally.

VERIFY: venv\Scripts\python.exe -m pytest tests/ -q  (baseline 1003 passed, 10 skipped).
```

---

## 10 — Output token cap truncates any non-trivial sketch

```
In F:\RC-Projects\autocad-ai\autocad-ai, moderately sized drawings fail with a misleading error.

src/ai/client.py:130 — _resolve_max_tokens defaults the OUTPUT cap to 800 tokens. Every 2D command
path uses that default (command_generator, command_repairer, command_verifier, drawing_task_planner,
edit_generator, vessel_planner). The CAD3D/P&ID/project planners all set it explicitly (2000/4000/
5000/500), so the 800 default is an oversight, not a policy.

Meanwhile src/ai/command_generator.py:40 instructs the model "Do not output more than 1000 commands."
A 61-command sequence measures ~1,390 output tokens — already 1.7x over the cap.

Result: any sketch needing more than ~25 commands has its response cut mid-JSON, _extract_json raises,
both retries hit the same cap, and the user gets "502 AI returned invalid JSON: Expecting ','
delimiter" — a token-budget problem misreported as a model formatting problem.

Aggravating: src/ai/client.py:179 reads response.choices[0].message.content but never inspects
finish_reason, so a "length" truncation is indistinguishable from genuinely malformed output.

CHANGES
1. Raise the default output cap to something consistent with the explicit callers (2000-4000), and
   justify the number you pick in a comment.
2. Inspect finish_reason at client.py:179. When it is "length", raise an error that SAYS the response
   was truncated and suggests a smaller request — do not report it as invalid JSON.

TESTS (stub the provider; do not make real API calls)
- a provider response with finish_reason="length" produces a truncation error, not a JSON error
- the default max_tokens sent to the provider is the new value
- an explicit max_tokens argument still overrides the default

VERIFY: venv\Scripts\python.exe -m pytest tests/ -q  (baseline 1003 passed, 10 skipped).
```

---

## 11 — Vessel head depth: drawn 505, dimensioned 500

```
In F:\RC-Projects\autocad-ai\autocad-ai, vessel drawings are dimensioned inconsistently with how they
are drawn.

src/parametric/vessel/draw_dimensions.py:87-90 computes head depth as internal_diameter_mm / 4.0 =
500 for V201. But src/parametric/vessel/geometry.py:65-66 draws the head with minor semi-axis
(D/2 + t)/2 = 505, and draw_front_view.py:125 / draw_top_view.py:126 use that 505 value.
geometry.py:103,106 places head nozzles at +/-500.

Measured on V201: drawn overall length 5510 mm, dimension text says 5500 mm, and head nozzles sit
5 mm inside the head they attach to. V203_LONG is off by 6 mm.

CRITICAL — A TEST WAS SUPPOSED TO CATCH THIS AND CANNOT.
tests/parametric/test_view_consistency.py:78 (test_overall_length_used_by_views_is_consistent) never
calls ANY source function. It computes V201.internal_diameter_mm / 4.0 inline in the test body and
asserts 2000/4 == 500 and 4500+1000 == 5500. It is pure Python arithmetic and cannot fail regardless
of what the source code does. Meanwhile the sibling test at :64 asserts 505 from the real
compute_head_arc. So the file asserts both numbers and catches neither.

CHANGES
1. Decide which value is correct — (D/2 + t)/2 or D/4 — and make EVERY call site agree. State which
   you chose and why.
2. REWRITE test_view_consistency.py:78 so it calls the real source functions. Do not leave a
   tautological test in place, and do not just add a new test beside it.

TESTS
- the dimensioned overall length equals the drawn overall length, computed from real source functions
- head nozzle positions sit on the head outline, not 5 mm inside it
- all five shipped examples (V201, V202, V203_LONG, V204_END_NOZZLES, V205_CLUSTERED) pass

NOTE: the entire ~2,350-line vessel renderer currently has no tests, which is why this survived.

VERIFY: venv\Scripts\python.exe -m pytest tests/ -q  (baseline 1003 passed, 10 skipped).
```

---

## 12 — tests/api writes the real jobs.db

```
In F:\RC-Projects\autocad-ai\autocad-ai, running the test suite damages live data.

tests/api/ has no conftest.py and therefore no database isolation, while tests/project/conftest.py
monkeypatches db.DB_PATH and backup.BACKUP_ROOT per test. src/logging/db.py:6 hardcodes
DB_PATH = PROJECT_ROOT / "jobs.db" with no environment override.

Proven by hash: running tests/api/ alone (173 passed) changed jobs.db from md5 7d25e945... to
901cb300..., grew it 10,424,320 -> 10,563,584 bytes, injected 135 test rows into production job
history, and CREATED 16 TABLES that did not exist there before (projects, drawings, entities,
entity_geometry, entity_properties, change_sets, change_set_items, change_set_files, spatial_index*,
relationships, validation_results and more).

CHANGES
1. Add tests/api/conftest.py mirroring tests/project/conftest.py's isolation (autouse fixture
   monkeypatching db.DB_PATH, and backup.BACKUP_ROOT if any API test can trigger a backup).
2. Consider allowing an environment override for DB_PATH in src/logging/db.py so isolation does not
   depend solely on monkeypatching. If you add one, make sure it cannot accidentally point at the
   real DB during tests.

VERIFY
- copy jobs.db to a temp location and record its hash
- run: venv\Scripts\python.exe -m pytest tests/api/ -q
- confirm the repo's jobs.db hash is UNCHANGED
- then run the full suite: venv\Scripts\python.exe -m pytest tests/ -q (baseline 1003 passed,
  10 skipped) and confirm jobs.db is still unchanged

Do not modify the repo's jobs.db yourself. If your testing dirties it, restore it from your copy and
say so.
```

---

## 13 — fake_cad ModelSpace is a plain list, so the drawing code is never tested

```
In F:\RC-Projects\autocad-ai\autocad-ai, a large amount of test coverage is illusory.

tests/project/fake_cad.py:100-102 returns ModelSpace as a plain Python list. Real AcadModelSpace is a
COM collection exposing AddLine, AddCircle, AddArc, AddEllipse, AddText, AddMText, AddDimAligned,
AddLightWeightPolyline, Count and Item. So src/framework/commands/executor.py:484
(msp = doc.ModelSpace) and its ENTIRE creation surface (lines 204-354) can never run against this
fake. executor.py:281's hasattr(msp, "AddLightWeightPolyline") fallback is likewise unreachable.

Knock-on effect: tests/project/test_modification.py:24 does
monkeypatch.setattr(engine, "point", tuple) for ALL 27 tests in that file, because the fake cannot
accept a real win32com VARIANT. Real AutoCAD REQUIRES a VARIANT for point properties and rejects a
bare tuple — so src/cad/session.py:63-66's point() has zero effective coverage and that file proves
nothing about whether real coordinate assignment works.

A partial reference implementation already exists: tests/project/test_pid_component_identity.py
supplies a _CreatingModelSpace with correct VARIANT unwrapping, but only for AddLine,
AddLightWeightPolyline and AddText. Circles, arcs, ellipses, dimensions and MText have no COM-shaped
creation test at all.

CHANGES
1. Give fake_cad.py a proper COM-shaped ModelSpace collection supporting the full Add* surface
   executor.py uses, plus Count and Item, with correct VARIANT handling (real VARIANTs are NOT
   iterable; the data is in .value).
2. Remove the monkeypatch.setattr(engine, "point", tuple) stub at test_modification.py:24 so the real
   session.point() VARIANT path is exercised.
3. Make the fake raise COM-shaped errors where real COM would (pywintypes.com_error) rather than
   KeyError, so error-handling paths are genuinely tested.

pywin32 IS installed in this venv (AutoCAD itself is not running), so you can verify VARIANT semantics
empirically. Put any scratch scripts in the system temp directory, not the repo.

VERIFY: venv\Scripts\python.exe -m pytest tests/ -q (baseline 1003 passed, 10 skipped). Removing the
point stub may surface real failures — those are genuine bugs the stub was hiding. Report them; do not
re-add the stub to make them go away.
```

---

## 14 — Half the test runtime is real sleep

```
In F:\RC-Projects\autocad-ai\autocad-ai, the test suite takes 122 seconds, roughly 65 of which are
literal time.sleep.

src/parametric/vessel/dwg_export.py:52-73 _com_retry sleeps 0.5 + 1.0 + 1.5 + 2.0 = 5.0 seconds when
its retries exhaust. Tests that trigger an exhaustion pay that in full:
  tests/project/test_pid_component_identity.py — 10.19s, 10.13s, 10.04s (two exhaustions each)
  tests/framework/test_autocad_3d_executor.py — eight tests at ~5.0s
  tests/project/test_modification.py::test_inspector_resolves_explicit_document — 5.03s

tests/framework/test_autocad_inspector.py:129,246,261,316 already solves this by stubbing _com_retry
to call the operation directly. Apply the same pattern to the files above.

CHANGES: stub _com_retry in the affected test files so exhaustion does not cost real wall-clock time.
Do NOT change _com_retry's production backoff — only how tests exercise it. Keep at least one test
that genuinely verifies the retry/backoff behaviour itself (stub time.sleep there rather than the
retry function, so the logic is still covered).

VERIFY: venv\Scripts\python.exe -m pytest tests/ -q --durations=20 — report the new total runtime and
confirm 1003 passed, 10 skipped is unchanged.
```

---

## 15 — ChangeSet stuck-states (do prompt 1 first)

```
In F:\RC-Projects\autocad-ai\autocad-ai, src/cad/changes.py implements the ChangeSet mechanism
(apply -> keep or revert). It is the ONLY revertible workflow in the app, and it has three bugs that
permanently lock a drawing out of all future edits.

BUG A (changes.py:172, 188-191): _check_files enforces "current file must still hash to after_hash"
for BOTH keep and revert. Correct for revert (don't clobber later work), wrong for keep, which writes
nothing. So: apply an AI edit, then open the drawing in AutoCAD and save a note, and now keep AND
revert both refuse forever — after which the conflict check at changes.py:99-102 (which blocks on
status IN ('applying','pending','error','reverting')) locks that drawing out of every future edit.
Recovery currently requires manual SQL. A rescan does not help.

BUG B (changes.py:109, consumed at :189): change_set_files is committed with after_hash NULL and only
backfilled by _record_file AFTER the COM save. A hard kill in that window makes
`expected = item["after_hash"] or item["before_hash"]` compare the PRE-edit hash against the POST-edit
file, so revert is refused in exactly the case it exists for.

BUG C (changes.py:187 resuming_revert, :251 already_restored): the resumable-revert logic is
RENAME-ONLY — resuming_revert requires `not current.exists()` and already_restored requires
`original != current`. For a normal in-place edit original == current, so a revert interrupted after
os.replace but before the DB update leaves the disk correctly restored while the DB is stuck at
'reverting' forever.

ROOT CAUSE: _check_files has no notion of "the file already matches a state we know is safe."

CHANGES
1. Remove the freshness check from the keep path entirely — keep writes nothing, so it cannot clobber.
2. In revert, accept current hashing to EITHER after_hash (normal) OR before_hash (already restored /
   resume), and make that work for in-place edits, not just renames.
3. Make a NULL after_hash an explicit "interrupted" state rather than silently falling back to
   before_hash. Decide how revert should behave for it and comment your reasoning.
4. Add a route to src/api/routes/changes.py that resolves a stuck changeset (discard / force-close)
   without manual SQL, so a drawing can never be permanently locked out.

DO NOT weaken the genuine safety property: revert must still refuse to overwrite later work when the
file has genuinely diverged. tests/project/test_changes.py's
test_later_disk_or_unsaved_edits_are_not_overwritten asserts that and must still pass.

TESTS
- apply -> externally modify and save -> keep SUCCEEDS, and the drawing is editable afterwards
- apply -> externally modify -> revert still refuses -> the new discard route resolves it -> editable
- in-place (NOT rename) revert interrupted after os.replace -> retry SUCCEEDS
- raise KeyboardInterrupt inside _record_file (reproduces the hard-kill DB state) -> revert SUCCEEDS

VERIFY: venv\Scripts\python.exe -m pytest tests/ -q  (baseline 1003 passed, 10 skipped).
```

---

## 16 — One revert mechanism for all eight workflows (do prompts 1 and 15 first)

```
In F:\RC-Projects\autocad-ai\autocad-ai there are 8 mutating workflows and only 1 is revertible.

The project's own stated goal was: "every mutating operation can be previewed, kept, or reverted,
consistently, across every workflow." Instead there are four separate token caches (sketch.py:40,
pid.py:19, cad3d.py:42, vessel.py:37) and the ChangeSet mechanism in src/cad/changes.py became a
FIFTH mechanism alongside them rather than a unification.

PREREQUISITES: prompts 1 and 15 must already be done. Verify: src/backup.py should have restore_file(),
and changes.py's keep path should no longer run a freshness check.

DESIGN CONSTRAINT — READ CAREFULLY. ChangeSet currently models per-entity structured operations. The
legacy workflows are additive command batches that do NOT fit that model. Do NOT decompose them into
entity operations — that is a large and unnecessary refactor. Instead add a FILE-LEVEL changeset item
type: back up the file, execute, record the after-hash, and revert by restoring the backup. Reuse the
existing change_sets / change_set_files tables and the existing keep/revert routes. Per-entity detail
is explicitly out of scope.

ROUTES TO COVER
  /api/sketch/approve            src/api/routes/sketch.py:649
  /api/pid/approve               src/api/routes/pid.py:106
  /api/cad3d/approve             src/api/routes/cad3d.py:432
  /api/cad3d/edit (execute=true) src/api/routes/cad3d.py:353
  /api/generate-vessel/confirm   src/api/routes/vessel.py
  /api/place-symbol              src/api/routes/place_symbol.py:37
  /api/autocad/edit              src/api/routes/autocad_edit.py:116
Also migrate /api/title-block-update off its ad-hoc backup_file() call (src/use_cases/
update_title_block.py:139) onto the same mechanism.

ALSO: update src/api/static/sketch.html so every result bubble shows the change_set_id and offers a
Revert control — today only project operations get one. Use the existing escapeText helper for all
interpolated values.

DO NOT remove the token caches. They still do a real job: holding an unexecuted plan between generate
and approve. This task is about what happens AFTER execution.

TESTS
- for EACH of the 8 routes: execute against a temp DXF with save=True -> a change_set_id is returned
  -> revert -> the file is BYTE-IDENTICAL to before
- revert twice -> the second is rejected cleanly, no crash
- execute -> externally modify the file -> revert refuses (prompt 15's semantics must hold here too)
- a failed execution creates no changeset, or one marked failed — implement one, test it, say which

VERIFY: venv\Scripts\python.exe -m pytest tests/ -q  (baseline 1003 passed, 10 skipped).
```

---

## 17 — No shipped P&ID template tags anything

```
In F:\RC-Projects\autocad-ai\autocad-ai, the app's own generator produces drawings its own editor
cannot address.

A previous fix added a `tag` parameter to the P&ID symbol builders so generated components would carry
recoverable AUTOCAD_AI_TAG XData. But NO SHIPPED TEMPLATE EVER PASSES ONE. Verified: rendering the
default template (choose_pid_component_template("draw me a p&id") -> horizontal_separator) produces
80 commands of which only 5 are tagged — all 5 from the vessel and instrument bubbles. 26 LINEs,
25 POLYLINEs, 2 ARCs and 1 CIRCLE carry no tag at all.

So "generate a P&ID, then resize pipe P-101" — the exact scenario that fix was written for — still
fails end to end, because the editor finds entities by tag and the generator emits none.

CHANGES
1. src/framework/pid/component_templates.py:50-124, 154-198, 230-255 — every pipe_run, gate_valve and
   control_valve in every shipped template must carry a tag.
2. src/framework/pid/component_examples.py — same for PipeRunComponent, GateValveComponent and
   ControlValveComponent, all currently constructed without tag=.
3. src/framework/pid/components/piping.py and valves.py — confirm render() actually passes
   tag=self.tag through to the symbol builder.
4. src/framework/pid/scene_renderer.py:88, 98-108 — this older non-component path passes no tag at
   all. It is dormant (no caller outside framework/pid) but exported; either wire tags through it or
   mark it clearly deprecated.
5. src/ai/pid_component_planner.py — the planner should emit tags, auto-generating a sensible one when
   the model omits it, following the existing engineering convention (P-101, V-201, FT-301).
6. Audit src/framework/cad3d/ for the same gap and report what you find.

TESTS
- for EVERY shipped template: render it and assert ZERO untagged component commands
- full round trip: generate a P&ID -> execute into a DXF -> scan it -> find_by_tag returns the pipe ->
  plan a resize against it -> the plan validates
- tag uniqueness within a drawing is enforced

NOTE: tests/framework/test_pid_component_templates.py:18 currently only checks that tag strings are
non-empty WHEN PRESENT, which is why this survived. Strengthen it.

VERIFY: venv\Scripts\python.exe -m pytest tests/ -q  (baseline 1003 passed, 10 skipped).
```

---

## 18 — Expand the editable entity set (do prompt 17 first)

```
In F:\RC-Projects\autocad-ai\autocad-ai, the in-place editor supports far too few entity types.

Today: length resize works on LINE only; radius resize on CIRCLE/ARC only, and only in the XY plane.
There is no scale or stretch operation anywhere, so polylines, block references, 3D solids, ellipses,
splines and dimensions cannot be resized at all. Colour is ACI integer 0-256 only.

ADD SUPPORT FOR
- LWPOLYLINE / POLYLINE scaling
- INSERT (block reference) scaling via XScaleFactor / YScaleFactor / ZScaleFactor
- ELLIPSE major/minor axis resize
- a generic SCALE_ENTITY operation about a caller-specified basepoint
- RGB / TrueColor alongside ACI

WHERE
- src/framework/commands/modification_executor.py `_resize` — add per-type branches
- src/cad/orchestrator.py:120-141 `plan` — plan-time validation MUST be updated in lockstep, or plans
  are accepted and then fail at execute time
- src/framework/commands/operation_schema.py:22-24 — colour schema
- src/ai/project_planner.py OPERATION_VARIANTS — teach the planner the new operations

ALSO FIX WHILE HERE: for ARC entities the plan-time "before radius" is computed from the bounding box
as (max_x - min_x)/2, but execute time reads entity.Radius via COM. An arc's bounding box spans only
the rendered segment, not the full circle, so the two disagree. Make them agree.

HARD RULES
- Every edit must remain an in-place property assignment. No .Delete() and re-add, ever.
- Keep every existing pre-flight guard for the new types too: unsaved-doc check, index-freshness hash
  check, live-vs-indexed geometry check, units check, post-assignment read-back, post-save
  re-extraction.
- Unsupported types must still be rejected at PLAN time, before a job row is created, with a message
  naming the type and what is supported.

TESTS (use real DXF files via ezdxf plus the fake COM double in tests/project/fake_cad.py)
- for EACH newly supported type: build a DXF, scan, plan, execute, re-extract, assert the new
  dimension, AND assert the entity handle is UNCHANGED (this proves in-place editing)
- an unsupported type fails at plan time with a clear message and creates no job row
- ARC: plan-time before == execute-time before
- an RGB colour round-trips through save and re-extraction

VERIFY: venv\Scripts\python.exe -m pytest tests/ -q  (baseline 1003 passed, 10 skipped).
```

---

## 19 — "Header color" is a dead end

```
In F:\RC-Projects\autocad-ai\autocad-ai, a reasonable user request always returns an error.

src/ai/project_planner.py:35-36 instructs the model to return CLARIFY for anything about header
colours, and plan_operation at :42 turns CLARIFY into a ValueError, which
src/api/routes/projects.py:26 maps to HTTP 409. So asking "change the header colour" produces a red
error, not a follow-up question.

CHANGES — pick ONE and implement it properly, explaining your choice in a comment:
(a) Implement title-block / header colour as a real operation, following how SET_LAYER_COLOR works at
    src/framework/commands/modification_executor.py:185-187; or
(b) Make CLARIFY a first-class conversational response: a distinct response shape the frontend can
    render as a follow-up question. If you choose this, src/api/static/sketch.html MUST actually
    render it as a question rather than a red error — do not stop at the backend.

Either way, a user asking about header colour must get something actionable, never a bare 409.

TESTS
- a "change the header colour" prompt returns a structured clarification (or performs the operation),
  not an unhandled 409
- if you chose (b): the frontend renders it as a question — assert on the rendered output
- if you chose (a): the colour change is verified after save, like other operations

VERIFY: venv\Scripts\python.exe -m pytest tests/ -q  (baseline 1003 passed, 10 skipped).
```

---

## 20 — Extractor reads no layer table and no SummaryInfo

```
In F:\RC-Projects\autocad-ai\autocad-ai, two whole categories of drawing data are never indexed.

src/cad/extractor/dxf_extractor.py:47-49 `_parse` extracts entities and geometry but never the layer
table or the document SummaryInfo. Verified: a DXF with a layer coloured 5 yields
DocumentMetadata(..., properties={}).

Two consequences:
1. Layer colours, layer names and document properties (Title/Author/Subject/...) are never queryable
   from the index.
2. Layer-colour and document-property edits are the ONLY operations not re-verified after save —
   src/framework/commands/modification_executor.py:321-348 covers only RESIZE and SET_ENTITY_PROPERTY,
   so those two operations currently trust a silent Save().

CHANGES
1. Extract the layer table (name, colour, linetype, on/off/frozen state) and document SummaryInfo in
   dxf_extractor.py.
2. Store them — extend src/storage/schema.sql as needed — and make them queryable.
3. Extend the post-save verification at modification_executor.py:321-348 to cover layer-colour and
   document-property edits.

TESTS
- a DXF with a coloured layer -> scan -> the layer and its colour appear in the index
- document properties (Title/Author) round-trip through scan -> edit -> re-extract
- a LYING save is caught: make the fake COM double not actually persist the change, and assert the
  operation FAILS rather than reporting success
- rescanning an unchanged drawing does not duplicate layer rows

VERIFY: venv\Scripts\python.exe -m pytest tests/ -q  (baseline 1003 passed, 10 skipped).
```

---

## 21 — Retire implicit ActiveDocument writes

```
In F:\RC-Projects\autocad-ai\autocad-ai, the legacy routes still write to whatever drawing happens to
be open.

The newer project path resolves every document by absolute path, and the test suite actively enforces
it — tests/project/fake_cad.py's Acad.ActiveDocument raises
AssertionError("Implicit active-document targeting is forbidden"). The legacy routes never got this:
src/api/routes/sketch.py:402, pid.py:108, cad3d.py:353 and :432, and autocad_edit.py:43 all accept an
OPTIONAL target_dwg_path and silently fall back to ActiveDocument.

CHANGES: make writing to the active document require an explicit opt-in (for example a
use_active_document: bool = False request field). With neither a target nor the opt-in, reject the
request with a clear message BEFORE any COM call. Match the standard the new path already enforces.

Keep the change backward-compatible where you reasonably can, but correctness wins over convenience —
silently writing to the wrong drawing is the bug being fixed.

TESTS
- no target and no opt-in -> rejected with a clear message, no COM write attempted
- explicit opt-in -> uses ActiveDocument, as before
- explicit target -> uses the target, ignoring whatever is active

VERIFY: venv\Scripts\python.exe -m pytest tests/ -q  (baseline 1003 passed, 10 skipped).
```

---

## 22 — edit_executor sends deletions and additions to different drawings

```
In F:\RC-Projects\autocad-ai\autocad-ai, one edit can be split across two different drawings.

src/framework/commands/edit_executor.py:188 delegates its additions to execute_commands with
target_dwg_path=None. So src/framework/commands/executor.py:482 resolves acad.ActiveDocument — NOT the
document edit_executor opened at line 42. There is no doc.Activate() before the delegation; it only
happens at line 220, AFTER the save.

Failure: the user has drawing B focused and sends a request targeting drawing A. The deletions land in
A, the new geometry lands in B, and doc.Save() saves only A. Drawing A loses entities, drawing B
silently accumulates stray unsaved geometry. The reported entity_count_after is read from A's
modelspace, so the returned counts also lie.

CHANGES: make deletions and additions always target the same document. Either pass the resolved target
through to execute_commands, or activate the target before delegating — pick the approach that does
not rely on global focus state, and explain why.

TESTS
- edit_executor with an explicit target while a DIFFERENT document is active: deletions AND additions
  both land in the target, and the other document is untouched
- the reported entity counts match the target document

NOTE: every existing edit test monkeypatches execute_commands away, which is why this survived. Your
test must NOT do that — it needs to exercise the real delegation.

VERIFY: venv\Scripts\python.exe -m pytest tests/ -q  (baseline 1003 passed, 10 skipped).
```

---

## 23 — Opened documents are never closed

```
In F:\RC-Projects\autocad-ai\autocad-ai, drawings pile up in the user's AutoCAD session.

src/framework/commands/executor.py:476-480, src/framework/commands/edit_executor.py:40-47 and
src/framework/cad3d/autocad_3d_executor.py:644-647 all call acad.Documents.Open() directly, instead of
using src/cad/session.py:35 get_document — which does an is_file check, an already-open lookup, and a
doc.FullName identity check. None of the three ever calls Close().

So every approve that passes a target_dwg_path leaves another drawing open, accumulating across
requests until the user notices or AutoCAD struggles.

CHANGES
1. Route all three through src/cad/session.py's get_document rather than calling Documents.Open()
   directly, so they inherit its checks.
2. Close what you open — but NEVER close a document the user already had open. get_document's
   already-open lookup tells you which case you are in; track that and only close documents your own
   call opened.
3. Make sure the close happens even when execution fails (try/finally), but AFTER any save.

TESTS
- N sequential requests with target_dwg_path -> the count of open documents does not grow
- a document the user already had open is NOT closed by the executor
- a failing execution still closes what it opened
- opening a path that is not a file produces a clear error (get_document's is_file check)

VERIFY: venv\Scripts\python.exe -m pytest tests/ -q  (baseline 1003 passed, 10 skipped).
```

---

## 24 — The index can barely be queried

```
In F:\RC-Projects\autocad-ai\autocad-ai there is a SQLite index of a folder of AutoCAD drawings. The
index itself is sound — its spatial correctness was verified across 675 R*Tree vs cKDTree comparisons
with zero mismatches. The problem is that almost nothing can be asked of it.

Only two query shapes exist:
  GET /api/projects/{id}/entities?tag=   (exact match)
  GET /api/projects/{id}/nearby?tag=

There is no "list entities in drawing X", no filter by entity type / layer / block, no free-text
search, and no way to read back drawing_metadata or entity_properties at all.

CHANGES: add those query capabilities.
- src/api/routes/projects.py:57-76 — the route surface
- src/storage/entity_repository.py:70-82 — TAG_QUERY is exact-match only

KEEP QUERIES INDEXED. Do not introduce table scans. Check EXPLAIN QUERY PLAN for anything you add —
tests/project/test_entity_index.py already does this at :29-30 and asserts the expected index is used.
Follow that pattern for your new queries.

TESTS
- scan a multi-entity DXF -> list entities for one drawing -> correct set returned
- filter by entity type -> correct subset
- filter by layer -> correct subset
- read back entity_properties and drawing_metadata for a known entity
- EXPLAIN QUERY PLAN shows an index is used for each new query, not a scan
- results are scoped to the requested project (no cross-project leakage)

VERIFY: venv\Scripts\python.exe -m pytest tests/ -q  (baseline 1003 passed, 10 skipped).
```

---

## 25 — Components labelled with plain TEXT are invisible (do prompt 24 first)

```
In F:\RC-Projects\autocad-ai\autocad-ai, a common real-world drawing convention indexes nothing.

src/cad/extractor/dxf_extractor.py:67-71 extracts a component tag ONLY from a TAG / COMPONENT_TAG /
P_TAG block attribute, or from XData of the form "TAG=...". Real drawings very often label a component
with a plain TEXT or MTEXT entity placed near it instead.

Those components index no tag at all, which makes them invisible to every query AND to every edit —
the whole editing path finds entities by tag.

CHANGES: add proximity-based association between a TEXT/MTEXT entity and the nearest taggable entity.

BE CONSERVATIVE. A WRONG association is worse than none, because edits are driven off this index and a
mis-association means editing the wrong entity in a real drawing. Specifically:
- make the distance threshold configurable, with a documented default and your reasoning for it
- refuse to associate when two candidate entities are comparably close (ambiguous -> no tag)
- mark proximity-derived tags distinctly in the index so a caller can tell them apart from explicit
  XData/attribute tags, and so a future change can weight them differently
- do not let a proximity tag silently override an explicit one

TESTS
- a DXF labelling a pipe with a nearby TEXT entity -> after scan, the component is findable by that tag
- a TEXT entity equidistant from two entities -> NO association is made
- a TEXT entity beyond the threshold -> no association
- an explicit XData tag wins over a nearby TEXT label
- proximity-derived tags are distinguishable from explicit ones in the index

VERIFY: venv\Scripts\python.exe -m pytest tests/ -q  (baseline 1003 passed, 10 skipped).
```

---

## 26 — DWG scanning is unusable and undocumented

```
In F:\RC-Projects\autocad-ai\autocad-ai, the multi-file index is effectively DXF-only.

Scanning a .dwg raises RuntimeError unless the ODA_FILE_CONVERTER environment variable is set. It is
not set in .env, not mentioned in the README, and not handled by setup-and-start.ps1 — so out of the
box, a user pointing the app at a folder of real DWG files gets a failure with no guidance.

CHANGES
1. src/cad/extractor/oda.py — raise a clear, actionable error that names the ODA_FILE_CONVERTER
   variable, says what the ODA File Converter is, and explains how to install and point at it. Not a
   bare RuntimeError.
2. Create .env.example documenting EVERY environment variable the app reads (AI_PROVIDER,
   DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, ODA_FILE_CONVERTER, and any others you find by
   grepping for os.getenv / os.environ). Use placeholder values only — never a real key.
   .gitignore already has a !.env.example negation, so it will be tracked.
3. Document DWG setup wherever the project documents setup.

TESTS
- scanning a .dwg with ODA_FILE_CONVERTER unset produces an error naming the variable
- the error is surfaced as a per-file scan_error, not a crash of the whole scan (verify current
  behaviour first and preserve it)
- .env.example lists every variable the code actually reads — assert this programmatically by grepping
  the source, so the file cannot silently drift

VERIFY: venv\Scripts\python.exe -m pytest tests/ -q  (baseline 1003 passed, 10 skipped).
```

---

## 27 — AUDIT_ROUTE_MAP ignores the HTTP method

```
In F:\RC-Projects\autocad-ai\autocad-ai, the audit log records operations that never happened.

src/api/main.py:34 AUDIT_ROUTE_MAP is keyed by request PATH only, never by method. But /api/projects
has both a GET (list projects) and a POST (register a project), and the map entry is
"/api/projects": "project_register".

Verified: GET /api/projects produces an audit row with use_case="project_register", status="ok".
src/api/static/project-chat.js:61 calls that endpoint on every page load, so every sidebar refresh
forges a record claiming a project was registered.

CHANGES: make AUDIT_ROUTE_MAP method-aware, so a GET and a POST on the same path map to different
use_case values (or so a GET maps to nothing, if you decide list operations should not be audited —
but note that GET /api/autocad/inspect IS deliberately audited, so read-only auditing is the existing
convention; prefer giving the GET its own use_case).

Check every entry in the map for the same collision, not just /api/projects.

TESTS
- GET /api/projects is audit-logged as a list operation, NOT project_register
- POST /api/projects is still audit-logged as project_register
- an existing single-method audited route is unaffected
- a path in the map with no matching method is not audited spuriously

NOTE: tests/api/ currently has no DB isolation. If prompt 12 has been done, use it; otherwise isolate
these tests locally rather than writing to the real jobs.db.

VERIFY: venv\Scripts\python.exe -m pytest tests/ -q  (baseline 1003 passed, 10 skipped).
```

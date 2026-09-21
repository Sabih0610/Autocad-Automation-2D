# Codex Prompts — Grouped (replaces prompts 13–27)

Prompts 1–12 from `CODEX_PROMPTS.md` are done. The remaining 15 issues are consolidated here into
**four** prompts, grouped so each loads one subject area's context and reuses it.

**State when these were written:** 1053 passed, **1 failed**, 10 skipped. The failure is
`tests/framework/test_cad3d_scene_store.py::test_list_records_returns_newest_first` — a pre-existing
latent bug that prompts 1–12 surfaced by shifting test timing. It is task A1 below.

**Run in order: A → B → C → D.** Dependencies are real:
- A fixes the COM fake, without which B/C cannot be properly tested
- B2 depends on B1
- C2 depends on C1
- D2 depends on D1

**Commit after each numbered task inside a group**, not once per group.

---

## GROUP A — COM fidelity and test infrastructure

```
You are working on F:\RC-Projects\autocad-ai\autocad-ai, a Windows-only Python/FastAPI app that drives
AutoCAD through COM (pywin32). Architectural rules you must not violate: the AI layer (src/ai/) only
produces schema-validated JSON plans and never touches AutoCAD; the framework layer (src/framework/)
never calls an LLM; entity edits are in-place COM property assignments, never .Delete() and re-add.

Current suite state: 1053 passed, 1 FAILED, 10 skipped. Five tasks. Commit after each one.

=== A1. Scene-store ordering is non-deterministic (fixes the failing test) ===
tests/framework/test_cad3d_scene_store.py::test_list_records_returns_newest_first fails in a full run
but passes alone. Not a test bug — a real one.
src/framework/cad3d/scene_store.py:19-20 _utc_now_iso() uses datetime.now(timezone.utc).isoformat().
On Windows that clock has ~15.6ms resolution, so consecutive calls return IDENTICAL strings — verified,
5 calls in a row produced the same value. list_records() (:214-221) and get_latest() (:242, :301) sort
by record.updated_at, and Python's sort is stable, so ties preserve insertion order and "newest first"
silently returns OLDEST first.
Real impact: /api/cad3d/edit with no token falls back to get_latest(), so two scenes created in the
same clock tick make it edit — and possibly execute into AutoCAD — the wrong scene.
FIX: make ordering deterministic. A timestamp alone is not enough; add a monotonic sequence number to
the record, or use time.perf_counter_ns / an incrementing counter as a tiebreaker. Persisted records
must still order correctly after a reload from disk, so whatever you add has to survive to_dict/
from_dict round-tripping.
TEST: two records created back-to-back with no sleep order newest-first, both in-memory and after a
reload from disk. Do NOT fix this by adding a sleep to the test.

=== A2. The COM fake cannot exercise the code that writes drawings ===
tests/project/fake_cad.py:100-102 returns ModelSpace as a plain Python list. Real AcadModelSpace is a
COM collection exposing AddLine, AddCircle, AddArc, AddEllipse, AddText, AddMText, AddDimAligned,
AddLightWeightPolyline, Count and Item. So src/framework/commands/executor.py:484 and its ENTIRE
creation surface (lines 204-354) can never run against this fake, and executor.py:281's
hasattr(msp, "AddLightWeightPolyline") fallback is unreachable.
Knock-on: tests/project/test_modification.py:24 does monkeypatch.setattr(engine, "point", tuple) for
ALL 27 tests in that file, because the fake cannot accept a real win32com VARIANT. Real AutoCAD
REQUIRES a VARIANT for point properties and rejects a bare tuple, so src/cad/session.py:63-66's
point() has zero effective coverage.
A partial reference already exists: tests/project/test_pid_component_identity.py has a
_CreatingModelSpace with correct VARIANT unwrapping, but only for AddLine, AddLightWeightPolyline and
AddText. Circles, arcs, ellipses, dimensions and MText have no COM-shaped creation test at all.
FIX: give fake_cad.py a proper COM-shaped ModelSpace supporting the full Add* surface executor.py
uses, plus Count and Item, with correct VARIANT handling (real VARIANTs are NOT iterable; data is in
.value). Then REMOVE the point->tuple stub at test_modification.py:24. Make the fake raise
pywintypes.com_error where real COM would, instead of KeyError.
pywin32 IS installed here (AutoCAD is not running), so verify VARIANT semantics empirically. Scratch
scripts go in the system temp dir, never the repo.
WARNING: removing the stub may surface real failures. Those are genuine bugs the stub was hiding —
report them, do not re-add the stub to make them disappear.

=== A3. edit_executor sends deletions and additions to different drawings ===
src/framework/commands/edit_executor.py:188 delegates additions to execute_commands with
target_dwg_path=None, so src/framework/commands/executor.py:482 resolves acad.ActiveDocument — NOT the
document edit_executor opened at line 42. No doc.Activate() happens before delegation; it only runs at
line 220, AFTER the save.
So with drawing B focused and a request targeting drawing A: deletions land in A, new geometry lands
in B, doc.Save() saves only A. A loses entities, B silently accumulates stray unsaved geometry, and
entity_count_after is read from A so the reported counts lie too.
FIX: make deletions and additions always target the same document. Either pass the resolved target
through, or activate before delegating — choose the approach that does not depend on global focus
state, and say why.
TEST: an explicit target while a DIFFERENT document is active — deletions AND additions both land in
the target, the other document is untouched, and the reported counts match the target.
NOTE: every existing edit test monkeypatches execute_commands away, which is why this survived. Your
test must NOT do that; it has to exercise the real delegation.

=== A4. Opened documents are never closed ===
executor.py:476-480, edit_executor.py:40-47 and src/framework/cad3d/autocad_3d_executor.py:644-647 all
call acad.Documents.Open() directly instead of src/cad/session.py:35 get_document — skipping its
is_file check, already-open lookup and FullName identity check — and none ever calls Close(). Every
approve with a target_dwg_path leaves another drawing open, accumulating across requests.
FIX: route all three through get_document, and close what you open. NEVER close a document the user
already had open — get_document's already-open lookup tells you which case you are in. Close in a
try/finally so it happens on failure too, but AFTER any save.
TEST: N sequential requests with target_dwg_path leave the open-document count flat; a pre-existing
open document is not closed; a failing execution still closes what it opened.

=== A5. Half the suite runtime is real sleep ===
src/parametric/vessel/dwg_export.py:52-73 _com_retry sleeps 0.5+1.0+1.5+2.0 = 5.0s when retries
exhaust. tests/project/test_pid_component_identity.py pays ~10s per test (two exhaustions each);
eight tests in tests/framework/test_autocad_3d_executor.py pay ~5s;
tests/project/test_modification.py::test_inspector_resolves_explicit_document pays 5s.
tests/framework/test_autocad_inspector.py:129,246,261,316 already solves this by stubbing _com_retry.
FIX: apply that same pattern to the files above. Do NOT change _com_retry's production backoff — only
how tests exercise it. Keep at least one test that genuinely verifies the retry/backoff logic (stub
time.sleep there rather than the retry function).
VERIFY with --durations=20 and report the new total runtime.

HARD RULES FOR ALL FIVE
- Never weaken or delete a test to make it pass. If a pre-existing test conflicts with a fix, STOP and
  explain the conflict.
- Every fix needs a test that fails before it and passes after. State how you verified that.
- After each task: venv\Scripts\python.exe -m pytest tests/ -q, report exact pass/fail/skip, commit.
- Target at the end of Group A: 0 failed.
```

---

## GROUP B — One revert mechanism for every workflow

```
You are working on F:\RC-Projects\autocad-ai\autocad-ai, a Python/FastAPI app that edits AutoCAD
drawings via COM. Group A is complete. Three tasks. Commit after each.

Background: this project's stated goal was "every mutating operation can be previewed, kept, or
reverted, consistently, across every workflow." Today there are 8 mutating workflows and only 1 is
revertible, and the ChangeSet mechanism became a FIFTH mechanism alongside four separate token caches
(src/api/routes/sketch.py:40, pid.py:19, cad3d.py:42, vessel.py:37) rather than a unification.

=== B1. ChangeSet has three ways to permanently brick a drawing ===
src/cad/changes.py implements apply -> keep or revert. It is the only revertible workflow, and:

(a) :172, :188-191 — _check_files enforces "current file must still hash to after_hash" for BOTH keep
    and revert. Correct for revert (don't clobber later work), WRONG for keep, which writes nothing.
    So: apply an edit, then open the drawing in AutoCAD and save a note, and keep AND revert both
    refuse forever — after which the conflict check at :99-102 (blocking on status IN
    ('applying','pending','error','reverting')) locks that drawing out of every future edit. Recovery
    needs manual SQL. A rescan does not help.
(b) :109, consumed at :189 — change_set_files is committed with after_hash NULL and backfilled by
    _record_file only AFTER the COM save. A hard kill in that window makes
    `expected = item["after_hash"] or item["before_hash"]` compare the PRE-edit hash against the
    POST-edit file, so revert is refused in exactly the case it exists for.
(c) :187 resuming_revert, :251 already_restored — the resume logic is RENAME-ONLY (requires
    `not current.exists()` / `original != current`). For an in-place edit original == current, so a
    revert interrupted after os.replace but before the DB update leaves the disk correctly restored
    while the DB sticks at 'reverting' forever.

ROOT CAUSE: _check_files has no notion of "the file already matches a state we know is safe."
FIX: drop the freshness check from keep entirely; in revert accept current hashing to EITHER
after_hash OR before_hash, for in-place edits not just renames; make a NULL after_hash an explicit
"interrupted" state rather than a silent fallback; add a route to src/api/routes/changes.py that
resolves a stuck changeset (discard/force-close) without manual SQL.
DO NOT weaken the real safety property — revert must still refuse when the file has genuinely
diverged. tests/project/test_changes.py::test_later_disk_or_unsaved_edits_are_not_overwritten asserts
that and must still pass.
TESTS: apply -> externally modify+save -> keep SUCCEEDS and the drawing is still editable; apply ->
externally modify -> revert refuses -> the new discard route resolves it -> editable; in-place (NOT
rename) revert interrupted after os.replace -> retry SUCCEEDS; KeyboardInterrupt raised inside
_record_file (reproduces the hard-kill DB state) -> revert SUCCEEDS.

=== B2. Give all 8 workflows keep/revert (depends on B1) ===
DESIGN CONSTRAINT — READ CAREFULLY. ChangeSet models per-entity structured operations. The legacy
workflows are additive command batches that do NOT fit that model. Do NOT decompose them into entity
operations; that is a large, unnecessary refactor. Add a FILE-LEVEL changeset item type instead: back
up the file, execute, record the after-hash, revert by restoring the backup. Reuse the existing
change_sets / change_set_files tables and the existing keep/revert routes. Per-entity detail is
explicitly out of scope.
ROUTES: /api/sketch/approve (sketch.py:649), /api/pid/approve (pid.py:106), /api/cad3d/approve
(cad3d.py:432), /api/cad3d/edit with execute=true (cad3d.py:353), /api/generate-vessel/confirm
(vessel.py), /api/place-symbol (place_symbol.py:37), /api/autocad/edit (autocad_edit.py:116). Also
migrate /api/title-block-update off its ad-hoc backup_file() call
(src/use_cases/update_title_block.py:139) onto the same mechanism.
ALSO: update src/api/static/sketch.html so every result bubble shows change_set_id and offers a Revert
control — today only project operations get one. Use the existing escapeText helper for every
interpolated value.
DO NOT remove the token caches. They still hold unexecuted plans between generate and approve; this
task is about what happens AFTER execution.
TESTS: for EACH of the 8 routes, execute against a temp DXF with save=True -> a change_set_id comes
back -> revert -> the file is BYTE-IDENTICAL to before. Plus: revert twice is rejected cleanly;
execute -> externally modify -> revert refuses (B1 semantics hold here too); a failed execution
creates no changeset or one marked failed (implement one, test it, say which).

=== B3. Retire implicit ActiveDocument writes ===
The newer project path resolves every document by absolute path, and the test suite enforces it —
tests/project/fake_cad.py's Acad.ActiveDocument raises AssertionError("Implicit active-document
targeting is forbidden"). The legacy routes never got this: src/api/routes/sketch.py:402, pid.py:108,
cad3d.py:353 and :432, autocad_edit.py:43 all accept an OPTIONAL target_dwg_path and silently fall
back to ActiveDocument.
FIX: make writing to the active document require an explicit opt-in (e.g. use_active_document: bool =
False). With neither a target nor the opt-in, reject BEFORE any COM call with a clear message.
Correctness wins over convenience here — silently writing to the wrong drawing is the bug.
TESTS: no target and no opt-in -> rejected, no COM write attempted; explicit opt-in -> uses
ActiveDocument as before; explicit target -> uses the target regardless of what is active.

HARD RULES
- Never weaken or delete a test to make it pass; if one conflicts, STOP and explain.
- Every fix needs a test that fails before and passes after.
- After each task: venv\Scripts\python.exe -m pytest tests/ -q, report exact numbers, commit.
```

---

## GROUP C — Editing capability

```
You are working on F:\RC-Projects\autocad-ai\autocad-ai, a Python/FastAPI app that generates AutoCAD
drawings AND edits them by engineering tag. Groups A and B are complete. Four tasks, in this order.
Commit after each.

=== C1. No shipped P&ID template tags anything (do this first) ===
A previous fix added a `tag` parameter to the P&ID symbol builders so generated components would carry
recoverable AUTOCAD_AI_TAG XData. But NO SHIPPED TEMPLATE EVER PASSES ONE. Verified: rendering the
default template (choose_pid_component_template("draw me a p&id") -> horizontal_separator) produces
80 commands of which only 5 are tagged — all 5 from the vessel and instrument bubbles. 26 LINEs,
25 POLYLINEs, 2 ARCs and 1 CIRCLE carry no tag.
So the app's own generator produces drawings its own editor cannot address: "generate a P&ID, then
resize pipe P-101" still fails end to end, because the editor finds entities by tag and the generator
emits none. This blocks C2 from being useful.
FIX
- src/framework/pid/component_templates.py:50-124, 154-198, 230-255 — every pipe_run, gate_valve and
  control_valve in every shipped template carries a tag
- src/framework/pid/component_examples.py — same for PipeRunComponent, GateValveComponent,
  ControlValveComponent (all currently built without tag=)
- src/framework/pid/components/piping.py and valves.py — confirm render() passes tag=self.tag through
- src/framework/pid/scene_renderer.py:88, 98-108 — this older path passes no tag at all; it is dormant
  (no caller outside framework/pid) but exported, so either wire tags through or mark it deprecated
- src/ai/pid_component_planner.py — emit tags, auto-generating one following the existing convention
  (P-101, V-201, FT-301) when the model omits it
- audit src/framework/cad3d/ for the same gap and report findings
TESTS: for EVERY shipped template, render and assert ZERO untagged component commands. Full round
trip: generate a P&ID -> execute into a DXF -> scan -> find_by_tag returns the pipe -> plan a resize ->
it validates. Tag uniqueness within a drawing is enforced.
NOTE: tests/framework/test_pid_component_templates.py:18 only checks tags are non-empty WHEN PRESENT,
which is why this survived. Strengthen it.

=== C2. Expand the editable entity set (depends on C1) ===
Today: length resize works on LINE only; radius on CIRCLE/ARC only, XY-plane only. No scale or stretch
operation exists at all, so polylines, block references, 3D solids, ellipses, splines and dimensions
cannot be resized. Colour is ACI integer 0-256 only.
ADD: LWPOLYLINE/POLYLINE scaling; INSERT scaling via XScaleFactor/YScaleFactor/ZScaleFactor; ELLIPSE
axis resize; a generic SCALE_ENTITY about a caller-specified basepoint; RGB/TrueColor alongside ACI.
WHERE: src/framework/commands/modification_executor.py `_resize` (per-type branches);
src/cad/orchestrator.py:120-141 `plan` — plan-time validation MUST be updated in lockstep or plans get
accepted then fail at execute time; src/framework/commands/operation_schema.py:22-24 (colour);
src/ai/project_planner.py OPERATION_VARIANTS.
ALSO FIX: for ARC, plan-time "before radius" comes from the bounding box as (max_x - min_x)/2 while
execute time reads entity.Radius via COM. An arc's bbox spans only the rendered segment, not the full
circle, so they disagree. Make them agree.
HARD RULES: every edit stays an in-place property assignment, never .Delete() and re-add. Keep ALL
existing pre-flight guards for the new types (unsaved-doc, index-freshness hash, live-vs-indexed
geometry, units, post-assignment read-back, post-save re-extraction). Unsupported types are still
rejected at PLAN time, before a job row exists, naming the type and what is supported.
TESTS: for EACH new type — build a DXF, scan, plan, execute, re-extract, assert the new dimension AND
assert the entity handle is UNCHANGED (this proves in-place editing). Unsupported type fails at plan
time with no job row. ARC plan-time before == execute-time before. RGB round-trips through save and
re-extraction.

=== C3. "Header color" is a dead end ===
src/ai/project_planner.py:35-36 tells the model to return CLARIFY for header-colour requests, and
plan_operation at :42 turns CLARIFY into a ValueError, which src/api/routes/projects.py:26 maps to
HTTP 409. A reasonable request always produces a red error instead of an answer.
FIX — pick ONE and explain your choice in a comment:
(a) implement title-block/header colour as a real operation, following how SET_LAYER_COLOR works at
    src/framework/commands/modification_executor.py:185-187; or
(b) make CLARIFY a first-class conversational response with its own response shape — and if you choose
    this, src/api/static/sketch.html MUST render it as a follow-up question, not a red error. Do not
    stop at the backend.
Either way a user asking about header colour gets something actionable, never a bare 409.
TEST: the request returns a structured clarification (or performs the operation), not an unhandled
409. If (b): assert the frontend renders it as a question. If (a): the change is verified after save.

=== C4. The extractor reads no layer table and no SummaryInfo ===
src/cad/extractor/dxf_extractor.py:47-49 `_parse` extracts entities and geometry but never the layer
table or document SummaryInfo. Verified: a DXF with a layer coloured 5 yields
DocumentMetadata(..., properties={}).
Two consequences: layer colours/names and document properties are never queryable from the index; and
layer-colour and document-property edits are the ONLY operations not re-verified after save
(src/framework/commands/modification_executor.py:321-348 covers only RESIZE and SET_ENTITY_PROPERTY),
so those two trust a silent Save().
FIX: extract the layer table (name, colour, linetype, on/off/frozen) and SummaryInfo; store them
(extend src/storage/schema.sql as needed); make them queryable; and extend the post-save verification
at :321-348 to cover layer-colour and document-property edits.
TESTS: a DXF with a coloured layer -> scan -> layer and colour in the index; document properties
(Title/Author) round-trip scan -> edit -> re-extract; a LYING save is caught (make the fake COM double
not persist the change and assert the operation FAILS rather than reporting success); rescanning an
unchanged drawing does not duplicate layer rows.

HARD RULES
- Never weaken or delete a test to make it pass; if one conflicts, STOP and explain.
- Every fix needs a test that fails before and passes after.
- After each task: venv\Scripts\python.exe -m pytest tests/ -q, report exact numbers, commit.
```

---

## GROUP D — Index and API surface

```
You are working on F:\RC-Projects\autocad-ai\autocad-ai, a Python/FastAPI app that maintains a SQLite
index of a folder of AutoCAD drawings. Groups A, B and C are complete. Four tasks. Commit after each.

The index itself is sound — its spatial correctness was verified across 675 R*Tree vs cKDTree
comparisons with zero mismatches. The problem is how little can be asked of it, and what never reaches
it in the first place.

=== D1. The index can barely be queried (do this first) ===
Only two query shapes exist: GET /api/projects/{id}/entities?tag= (exact match) and
GET /api/projects/{id}/nearby?tag=. There is no "list entities in drawing X", no filter by entity
type / layer / block, no free-text search, and no way to read back drawing_metadata or
entity_properties at all.
WHERE: src/api/routes/projects.py:57-76 (route surface); src/storage/entity_repository.py:70-82
(TAG_QUERY is exact-match only).
KEEP QUERIES INDEXED. Do not introduce table scans. Check EXPLAIN QUERY PLAN for everything you add —
tests/project/test_entity_index.py:29-30 already does this and asserts the expected index is used.
Follow that pattern.
TESTS: scan a multi-entity DXF -> list entities for one drawing -> correct set; filter by entity type
-> correct subset; filter by layer -> correct subset; read back entity_properties and drawing_metadata
for a known entity; EXPLAIN QUERY PLAN shows an index (not a scan) for each new query; results are
scoped to the requested project with no cross-project leakage.

=== D2. Components labelled with plain TEXT are invisible (depends on D1) ===
src/cad/extractor/dxf_extractor.py:67-71 extracts a component tag ONLY from a TAG / COMPONENT_TAG /
P_TAG block attribute, or from XData of the form "TAG=...". Real drawings very often label a component
with a plain TEXT or MTEXT entity placed nearby instead. Those components index no tag at all, making
them invisible to every query AND every edit — the whole editing path finds entities by tag.
FIX: add proximity-based association between a TEXT/MTEXT entity and the nearest taggable entity.
BE CONSERVATIVE. A WRONG association is worse than none, because edits are driven off this index and a
mis-association means editing the wrong entity in a real drawing. Specifically:
- make the distance threshold configurable, with a documented default and your reasoning
- refuse to associate when two candidate entities are comparably close (ambiguous -> no tag)
- mark proximity-derived tags distinctly in the index, so callers can tell them from explicit
  XData/attribute tags and a future change can weight them differently
- never let a proximity tag override an explicit one
TESTS: a DXF labelling a pipe with a nearby TEXT entity -> after scan the component is findable by
that tag; a TEXT entity equidistant from two entities -> NO association; beyond the threshold -> no
association; an explicit XData tag wins over a nearby TEXT label; proximity-derived tags are
distinguishable from explicit ones.

=== D3. DWG scanning is unusable and undocumented ===
Scanning a .dwg raises RuntimeError unless ODA_FILE_CONVERTER is set. It is set nowhere — not in .env,
not in the README, not in setup-and-start.ps1 — so the multi-file index is effectively DXF-only and a
user pointing the app at real DWG files gets a failure with no guidance.
FIX
- src/cad/extractor/oda.py — raise a clear, actionable error naming ODA_FILE_CONVERTER, saying what
  the ODA File Converter is and how to install and point at it. Not a bare RuntimeError.
- create .env.example documenting EVERY environment variable the app reads (AI_PROVIDER,
  DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, ODA_FILE_CONVERTER, plus anything else you find
  by grepping os.getenv / os.environ). PLACEHOLDER VALUES ONLY — never a real key. .gitignore already
  has a !.env.example negation so it will be tracked.
- document DWG setup wherever the project documents setup
TESTS: scanning a .dwg with ODA_FILE_CONVERTER unset produces an error naming the variable; that error
surfaces as a per-file scan_error rather than crashing the whole scan (verify current behaviour first
and preserve it); .env.example lists every variable the code actually reads — assert this
programmatically by grepping the source so the file cannot silently drift.

=== D4. The audit log records operations that never happened ===
src/api/main.py:34 AUDIT_ROUTE_MAP is keyed by request PATH only, never by method. /api/projects has
both a GET (list) and a POST (register), and the entry is "/api/projects": "project_register".
Verified: GET /api/projects produces an audit row with use_case="project_register", status="ok". And
src/api/static/project-chat.js:61 calls it on every page load, so every sidebar refresh forges a
record claiming a project was registered.
FIX: make AUDIT_ROUTE_MAP method-aware so a GET and a POST on the same path map to different use_case
values. Note GET /api/autocad/inspect IS deliberately audited, so read-only auditing is the existing
convention — prefer giving the GET its own use_case over dropping it. Check EVERY entry in the map for
the same collision, not just /api/projects.
TESTS: GET /api/projects is logged as a list operation, NOT project_register; POST /api/projects is
still project_register; an existing single-method audited route is unaffected; a path in the map with
no matching method is not audited spuriously.

HARD RULES
- Never weaken or delete a test to make it pass; if one conflicts, STOP and explain.
- Every fix needs a test that fails before and passes after.
- After each task: venv\Scripts\python.exe -m pytest tests/ -q, report exact numbers, commit.
- At the end of Group D, all 27 issues from the audit are closed. Report the final suite numbers and
  confirm 0 failed.
```

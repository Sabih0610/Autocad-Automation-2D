# Project Extension Review — Roadmap Steps 1-8, As Actually Implemented

This reviews the code Codex wrote to implement `roadmap/09_implementation_roadmap.md` (Steps
1-8, commits `7c58cc5`..`6b94090` plus two uncommitted files), against both general correctness
and the specific constraints laid out in `roadmap/`.

**This document went through two review rounds.** Round 1 (below, mostly unchanged) was 7
parallel agents independently verifying every claim in Codex's own `IMPLEMENTATION_LOG.md`
against the actual code. Round 2 was Codex's *own* separate self-audit of the same work, using a
different and complementary method — actual end-to-end reproduction against real generated
output, rather than reading code and running the existing suite. Round 2 found a more important
class of bug than Round 1 did (see below), and made three specific corrections to earlier
documentation in this `docs_analysis/` folder. Four of Round 2's most consequential and most
surprising claims were independently re-verified before accepting them (see "Round 2" section) —
this is not one side's word taken over the other's; both rounds were checked against the source.

**Independently re-verified:** full test suite is **956 passed, 10 skipped, 0 failed** (baseline
before this work was 892/10/0) — matches Codex's own reported number exactly, in both rounds.

---

## Round 2 — Codex's own end-to-end self-audit, reconciled (2026-09-20)

### The one thing Round 1 missed entirely, and it's the most important finding in either round

**Generated P&ID pipes cannot be found or edited by the new indexed-edit workflow at all.**
Round 1 scoped its review to "does the new subsystem work internally" and "did the new work
break old files" — it never tried the single most obvious end-to-end scenario: generate a P&ID
pipe with the *existing* generator, then try to resize it with the *new* system. Codex's own
audit did exactly that, and it fails. **Independently re-verified by reading the render path
directly:**

- `PipeRunComponent` (`src/framework/pid/components/piping.py:42-93`) has a `tag`/`id` field
  inherited from `BasePIDComponent` (`components/base.py:38,53`), but `render()` never threads
  `self.tag`/`self.id` into the emitted command dict.
- `pipe_line_commands()` (`src/framework/pid/symbols.py:128-142`) — the function that actually
  produces the geometry — emits a plain `{"command": "POLYLINE", "points": [...], "layer": ...}`
  dict. No tag, no XData, no attribute, nothing the new extractor can key on.
- The only thing that could carry the name "P-101" onto the drawing is a *separate*, unlinked
  `TEXT` entity, and only if the caller also happened to set the distinct `label` parameter to
  the same string — the new extractor's tag recognition mechanism (block attributes / `TAG=`
  XData) doesn't treat a nearby floating text label as proof of association at all.

So the actual, real-world scenario that motivated this whole roadmap — "generate a P&ID, then
ask to resize pipe P-101" — does not work today, even though every one of the roadmap's own
fixture-based acceptance tests passes. The fixtures all use synthetically-tagged entities
(attached via XData directly in the test), which is why 7 review agents and 956 passing tests
never caught this. **This is the highest-priority fix in the whole project**, because it's the
gap between "the roadmap's definitions of done are met" and "the feature actually works for the
reason it was built."

### Two corrections to earlier `docs_analysis/` documentation — both verified and now fixed in place

1. `docs_analysis/09_known_issues_and_recommendations.md` item 10 claimed
   `src/api/routes/line_list.py` was missing a `SystemExit` catch it needed. **Wrong, and now
   corrected in that file.** `use_cases/line_list_extract.py`'s `get_acad()` never raises
   `SystemExit` — only its CLI `main()` does, wrapping a *different* call site. The route already
   handles the real exception correctly with a plain `except Exception`.
2. `docs_analysis/09...md` item 15 claimed `src/ai/vessel_planner.py` had no test coverage.
   **Wrong, and now corrected.** `tests/parametric/test_vessel_planner.py` directly imports and
   tests `src.ai.vessel_planner` — verified by reading its import statements. The correct list of
   genuinely untested `src/ai/` modules is just `symbol_planner.py` and `consistency_explainer.py`.

A third correction was more of a precision fix than a reversal: item 30's claim that a hung AI
call could block "indefinitely, with no circuit breaker" overstated things — the `openai` SDK's
own default timeout still applies, it's just not one this app chose deliberately. Wording
corrected in place.

### New bugs Round 2 found that Round 1 didn't, organized by severity, with verification status

**Verified directly (see above) — treat as confirmed:**
- The P&ID pipe tag disconnect (above).
- Audit-log status misreporting: `_status_from_result` (`src/api/main.py:112-115`) only checks
  for a literal `ok: False` key. If the new project-execute route reports failure via a `status`
  field instead, this pre-existing, unchanged function silently logs the job as `"ok"`. Confirmed
  by reading the function directly.

**Not independently re-verified in this pass, but specific, falsifiable, and consistent with
everything that *was* checked — treat as credible:**
- Only `RESIZE_COMPONENT` re-verifies the saved value against fresh extraction; other operation
  types (color, layer, `SummaryInfo`, rename) only check that extraction succeeded, not that the
  new value actually persisted. A save that silently no-ops would still be recorded as validated.
- Rename+revert can reach a genuinely stuck state (not just a crash-on-retry, which Round 1 also
  found independently at `changes.py:222`) — a transient failure mid-revert can leave a state
  where retrying refuses to proceed at all ("destination now exists"), needing manual recovery.
- The new single-writer lock only serializes the *new* project/changeset routes against each
  other — legacy sketch/P&ID/CAD3D/title-block writes don't share it, so a legacy write and a new
  project write could still race against the one live AutoCAD session.
- Two registered projects with overlapping root folders (parent + child) break edits, because
  entity lookup during modification is global rather than scoped to the selected project.
- A rename-in-progress "is this file open" flag has no path to clear itself on a normal external
  close — only revert clears it.
- A forward-slash path breaks the filesystem-only rename path with a confusing raw
  `AttributeError` instead of a clean error.
- No crash-recovery/reconciliation for a multi-file job if the process itself dies mid-job — the
  job is left stranded in a "running" state with no automatic resume or cleanup.
- Concurrent requests to the **pre-existing, unmodified** title-block/line-list routes can leak
  each other's parameters through shared module globals — this is a sharper, directly-reproduced
  version of something already listed in `09_known_issues...md` (Tier 2, item 9), not a new class
  of problem, but worth knowing it's concretely exploitable, not just theoretical.
- P&ID/CAD3D approval tokens remaining replayable indefinitely is the same pre-existing,
  already-documented gap from `09_known_issues...md` item 7 — confirmed consistent across both
  audits, not new.

### Where both audits fully agree

- **The schema-contamination bug (Round 1 Tier 1 item 1) is now three-way confirmed** — found
  independently by two Round-1 agents *and* by Codex's own self-audit (which describes the same
  root cause from the executor's error-message side: `validate_command_sequence` accepts
  `SET_LAYER_COLOR` etc., then `_execute_one_command` rejects it as unsupported at runtime). Three
  independent investigations landing on the same bug is about as high-confidence as a finding
  gets without a live production incident. Fix this first.
- **Step 9 (COM vs. `.NET`): both audits independently concluded "stay on COM, provisional 9A."**
  No disagreement here at all — neither found anything requiring the dynamic-block, constraint-
  graph, or Plant 3D conditions from `roadmap/08_com_vs_dotnet_decision.md`.
- Both confirmed the pre-existing, intentionally-out-of-scope gaps (no backup in the legacy
  executor, replayable PID/CAD3D tokens) are genuinely untouched — neither accidentally fixed nor
  confusingly half-masked.

### Combined fix priority, superseding the Round 1 list below

1. **Connect generated component identity to the index** — without this, nothing else in the new
   subsystem is reachable from real usage. This is not "a bug to fix," it's "the integration the
   whole roadmap was for," and it's currently missing.
2. **Fix the three-way-confirmed schema contamination** (keep `OPERATION_SCHEMA` fully separate
   from `COMMAND_SCHEMA`).
3. **Fix save-verification for non-resize operations** and **the revert stuck-state bug** —
   both are "an edit can silently not actually happen, or can't be recovered when it fails."
4. **Unify the write-serialization boundary** across legacy and new routes, and **fix the
   audit-status mismatch** for the new routes.
5. Everything in Round 1's Tier 2/3 lists, plus the remaining Round-2-only medium items
   (overlapping projects, path normalization, stuck open-flags, job crash-recovery) — genuinely
   lower urgency than 1-4, worth batching together.

---

## Round 1 (original review, 2026-09-20, mostly unchanged below)

Every claim in this section was independently verified against the actual code by 7 parallel
review agents — none of it was taken on faith from Codex's own `IMPLEMENTATION_LOG.md`, which was
treated as a hypothesis to check, not a source of truth. Two of the findings below (item 1) were
reached independently by two different agents using different methods, which is strong
corroboration they're real — and, per Round 2 above, a *third*, independent method found the same
root cause again.

## What's genuinely solid (verified, not assumed)

- **The original motivating complaint — excessive AI tokens — is actually fixed.** The planner's
  actual prompt-construction code (`src/ai/project_planner.py`) sends one compact record (under
  500 JSON characters) for the one matching entity, never a drawing dump. Verified by reading the
  code directly and the test that parses the real prompt string.
- **No delete-and-recreate anywhere in the new modification engine** — grepped for
  `.Delete()`/`AddLine`/`AddCircle`/etc., zero matches. Every edit is a direct property
  assignment on a `HandleToObject`-retrieved object.
- **No silent "whatever's active" fallback in the new path** — every new operation type requires
  an explicit target file; the legacy inspector/edit routes correctly preserve their old default
  behavior when no target is given (with one narrow exception, see Tier 2 below).
- **Backup genuinely always precedes mutation** in the new engine — the earlier `_backup=False`
  escape hatch mentioned in Codex's own log was actually removed; no remaining path skips it.
- **Revert is genuinely byte-exact** — atomic `os.replace`, verified via hash comparison and
  re-extraction, not just "no exception was raised."
- **Locking is real**, not just a class name — single-worker thread pool plus a `BEGIN IMMEDIATE`
  SQLite transaction around the pending-conflict check.
- **No second LLM-calling module** snuck in anywhere outside `project_planner.py` (grepped the
  whole new codebase for `ask_ai`/`openai`).
- **No duplicate/third `AutoCADNotRunningError` class** — new code correctly reuses the existing
  one from `dwg_export.py` rather than redefining it (see `docs_analysis/09...md` item 4 for why
  this mattered).
- **No second production database** — same `jobs.db`, same connection function, `jobs` table
  schema byte-identical, WAL mode preserved.
- **Unit conversion (mm↔inches) is mathematically correct**, verified by hand and by dedicated
  tests.
- **The pre-existing known issues are confirmed untouched**, as intended: no backup in the old
  `execute_command_sequence`/`execute_edit_plan` path, and the inconsistent PID/CAD3D token-cache
  lifetimes — neither accidentally fixed nor confusingly half-masked by the new work.

## Tier 1 — Real bugs worth fixing

1. **Schema contamination leaks new operation types into the OLD AI prompts and validators.**
   `src/framework/commands/schema.py` mutates the *shared* `COMMAND_SCHEMA`/`_COMMAND_TYPES`
   objects at import time to add the 5 new operation command types. Since `edit_schema.py` derives
   its schema from the same shared object, and `src/ai/client.py` dumps the full JSON schema
   verbatim into every LLM system prompt, the **pre-existing** `/api/sketch/generate`,
   `command_repairer.py`, and `/api/autocad/edit` flows now tell the LLM these 5 new types are
   valid `commands` — but the old `executor.py`'s handler dict has no entry for them. Verified
   two ways independently: (a) by reading the mutation + downstream consumption, and (b) by
   directly calling `validate_command_sequence`/`validate_edit_plan` with a `RESIZE_COMPONENT`
   command and confirming they now incorrectly accept it. No dangerous execution results — it
   fails per-command with `CommandExecutionError` at runtime — but it directly conflicts with the
   instruction to leave the old path untouched, and weakens the "schema validation is a hard
   gate" invariant the whole architecture relies on. **Fix:** keep `OPERATION_SCHEMA` (which
   already exists as a separate object in `operation_schema.py`) fully independent instead of
   splicing its types into `COMMAND_SCHEMA`'s shared list.

2. **Backup-folder scanner exclusion is incomplete.** The uncommitted fix in `src/cad/scanner.py`
   only excludes the project-root `backups/` folder, not the separate, older `src/backups/`
   folder (which still contains real, stale `.dwg` files). If a project's root path ever includes
   this repo itself, the scanner would index those stale backups as live drawings. Fix: exclude
   any directory literally named `backups`, not one hardcoded path.

3. **Revert can fail on retry after a crash.** `src/cad/changes.py:222`'s `current.unlink()` has
   no `missing_ok=True`. If the process is interrupted right after a successful `os.replace` but
   before this cleanup line, retrying `revert()` re-does the (harmless) replace but then crashes
   on deleting an already-gone file — making an already-successful revert look like a failure.

4. **Rollback-during-rollback isn't exception-safe.** In `modification_executor.py`, if a second
   COM failure occurs while undoing a partially-applied multi-property edit, the reversal loop
   aborts partway, leaving some changes un-reverted in the live (unsaved) document and masking the
   original error with the new one. No test exercises a rollback with more than one applied
   change (e.g. a resize that also moves a connected valve).

5. **Property-verification checks can produce false-negative rollbacks.** The "did AutoCAD
   actually keep this value" check uses exact equality — a case-preserving-but-case-insensitive
   layer name (`"PIPES"` assigned, `"Pipes"` read back) or a `Normal` vector COM returns as
   `0.9999999999999998` instead of `1.0` would spuriously trigger a full rollback of an otherwise
   legitimate edit. The test suite's fake COM double always returns exact values, so this isn't
   caught by any existing test.

## Tier 2 — Dormant/edge-case bugs, not currently triggered but real

6. **R\*Tree `rowid` staleness under `VACUUM`.** The spatial index stores `entities.rowid`
   directly, and `entities` uses a `TEXT PRIMARY KEY` (a non-aliased rowid), which SQLite's own
   docs say `VACUUM` may renumber. Nothing calls `VACUUM` today — but if any future maintenance
   script does, spatial queries would silently return wrong results with no error.
7. **`BrokenProcessPool` cascades false per-file errors.** If one worker process crashes outright
   (not a normal exception) during parallel scanning, every *other* pending file in that batch
   gets incorrectly marked as errored too.
8. **Cross-process race in tag-based relationship derivation** — safe under the app's assumed
   single-worker deployment, would silently drop a `represented_in` edge under multiple workers.
9. Radius-based resize is validated later (at execute time) than length-based resize (at plan
   time) — an inconsistency, not a safety bug, but a planned job can be doomed to fail after
   sibling jobs in the same batch already executed.
10. **No COM busy-retry in the new engine** (unlike the legacy executor's `_com_retry`) — a
    transient AutoCAD-busy error aborts with a full rollback instead of retrying.
11. **An explicitly-sent empty-string `target_dwg_path`** in `autocad_edit.py`/`autocad_inspect.py`
    is treated the same as "absent," silently falling back to `ActiveDocument` — a narrow
    violation of "never silently fall back."
12. **Rename-open-guard has a narrow race** — no protection against AutoCAD opening the file
    externally between the check and the actual `os.rename`; also the "is this file open" flag
    can get stuck if `execute_operation` is ever called directly outside `ChangeManager` (fails
    closed, not unsafe, just a usability rough edge).

## Tier 3 — Style / minor / inert

13. An `UPDATE`-trigger on `entity_geometry` can never fire because every write is delete+insert
    in practice — untested, unexercised code, not currently a live bug.
14. Whitespace-only tags (`" "`) aren't filtered the same way `None`/`""` are in cross-drawing
    tag-relationship derivation.
15. A relationship referencing an unknown entity handle raises a raw `KeyError` instead of a
    descriptive `ValueError` (transaction still rolls back correctly either way).
16. A missing `layout` property on an entity produces a misleading "no geometry" error from
    `nearby()` when the real cause is the missing property.
17. Full schema/DDL re-execution on every single `connection()` call — idempotent, just wasteful.
18. A redundant case-sensitive tag index sits alongside the case-insensitive one that's actually
    used for lookups.
19. New read-only routes (`GET .../drawings`, `/entities`, `/nearby`, `/change-sets`, job lookup)
    aren't in `AUDIT_ROUTE_MAP`, inconsistent with the pre-existing convention that
    `GET /api/autocad/inspect` *is* audited. The mutating new routes are correctly audited.
20. Two near-identical `respond()` error-mapping helpers (`routes/projects.py`,
    `routes/changes.py`) disagree slightly on which exception types they catch; neither catches
    `sqlite3.OperationalError` (e.g. a lock timeout), which would surface as a raw 500 instead of
    a clean 409 in that specific case.

## Overall verdict (superseded by "Round 2" above for priority — kept for the record)

This is a genuinely careful, well-tested implementation — the two riskiest properties (does
backup/revert actually work byte-for-byte, and is the token-cost fix real) both came back clean
under adversarial review, and the constraint checklist from `roadmap/HANDOFF_PROMPT.md` (no
delete/recreate, no active-document fallback, no second LLM caller, extend-not-replace) holds for
everything except item 1. Fix item 1 before relying on the pre-existing sketch/edit/repair flows
in the same environment as this new work; the rest are worth cleaning up but aren't urgent.

## Final overall verdict, after both rounds

Both audits agree the *architecture* is sound and Step 9 is settled (stay on COM). Where Round 1
fell short was scope, not rigor: it verified the new subsystem thoroughly in isolation and against
its own fixtures, but never tried feeding it something the *existing*, unmodified app actually
generates. That single gap — P&ID pipes carry no recoverable identity once drawn — means the
roadmap's fixture-level "definition of done" is met everywhere, while the feature doesn't yet work
for its own motivating use case. Fix the priority list under "Round 2" above, in that order, before
treating Steps 1-8 as done rather than "structurally complete, integration pending."

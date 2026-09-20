# Roadmap implementation log

Baseline (Windows, Python 3.11.9, installed pywin32): **892 passed, 10 skipped**
in 81.52 seconds. No running AutoCAD or ODA converter discovered. Existing user
changes in `src/api/static/sketch.html` and untracked reference docs/launchers are
preserved. No Step 9 implementation is planned.

## Step 1 — Project registration + SQLite schema
Added src/storage/{database.py,project_repository.py,schema.sql} and tests/project storage coverage. Registration validates and canonicalizes folders without scanning; all roadmap tables live beside the unmodified jobs table through its existing connection function. WAL, foreign keys, repeat initialization, duplicate roots, invalid roots, registration and listing were verified. Full suite: 895 passed, 10 skipped. Reviewed: no CAD/LLM/deletion paths introduced. Definition of done fully met. No roadmap deviation; added lookup indexes and unique project/drawing paths for integrity.

## Step 2 — DrawingExtractor
Added `src/cad/extractor/` with the six-method abstract interface, shared dataclasses,
DXF implementation, isolated/injectable ODA adapter and a JSON-printing CLI.
`tests/project/test_extractor.py` exercises real generated DXF geometry, blocks,
attributes, XData tags, paper space, conversion injection/cache/cleanup and invalid
input. CLI extraction of existing `outputs/previews/manual_preview_test.dxf`
returned six entities and property records without SQLite or AutoCAD. Full suite:
899 passed, 10 skipped. Definition of done met for a real DXF; actual DWG-to-DXF
conversion remains environment-limited (ODA absent), tested through a fake adapter.
Review found no COM/LLM imports. No architecture deviation; unsupported dynamic
block/constraint semantics and proxy entities are surfaced as metadata warnings.

## Step 3 — Multi-file offline scanner
Added `src/cad/scanner.py` and `tests/project/test_scanner.py`: recursive project
inventory, parent-only database writes, process-pool extraction, stat/hash-based
incremental skips, per-file errors/retries, disappeared-file marking and changed-
during-read rejection. Three actual DXF files were scanned in two OS workers;
a folder of two DWG test files used the injected converter and a second scan
extracted zero files. Full suite: 904 passed, 10 skipped. Reviewed that the scan
path imports neither COM nor an LLM and only traverses the registered root.
Definition of done verified with real DXF and injected DWG conversion; production
DWG conversion remains unverified without ODA. Additive scope detail: native DXF
files are scanned as well as DWG, enabling offline use without conversion.

## Step 4 — Persistent entity/component index
Added `src/storage/entity_repository.py`, wired atomic snapshot persistence into
the scanner, and added `tests/project/test_entity_index.py`. Entities have stable
drawing/handle IDs; properties and geometry refresh transactionally; removed
entities disappear from queries without destroying changeset history. Case-
insensitive, project-scoped tag lookup uses one indexed SQL query (verified with
EXPLAIN QUERY PLAN) and opens no drawing. Full suite: 907 passed, 10 skipped.
Definition of done fully met. Review confirmed no CAD/LLM calls. Schema addition:
`drawing_metadata` stores units and document metadata/warnings absent from the
roadmap's entity-only tables; units are essential for correct millimetre edits.

## Step 5 — Relationships + spatial index
Added endpoint/insertion-point connection inference in `src/cad/relationships.py`,
same-tag cross-file appearance edges, unit conversion, and `src/storage/spatial.py`.
RTree is probed by creating the virtual table, maintained transactionally by
triggers; cKDTree provides a versioned fallback rebuilt only after index changes.
`tests/project/test_spatial.py` verifies 100 mm searches, drawing/layout isolation,
rescan invalidation, relationship types, missing-extension fallback and the RTree
query plan. Full suite: 912 passed, 10 skipped. Definition of done fully met.
Review: no LLM/COM calls. Proximity means Euclidean distance between axis-aligned
bounds, not exact solid collision or associative constraints. Added a one-row
`spatial_version` table for fallback cache invalidation; no platform change.

## Step 6 — Structured modification engine
Added strict operation schemas (also exposed through `commands/schema.py`),
`modification_executor.py`, pure geometry/unit calculations and explicit COM
session targeting. LINE length and XY CIRCLE/ARC radius edits use existing handles;
connected lines/block insertions/attributes move in place. Property, SummaryInfo,
layer-color and filesystem-rename operations are supported. Stale index/unsaved
state, nonfinite/nonpositive dimensions, unsupported dependencies and new bounding-
box overlaps fail before mutation. Inspector and inspect/edit HTTP routes now
forward explicit targets; legacy no-target behavior remains for compatibility.
Added `drawing_sessions` for conservative rename guards. New tests use a COM-shaped
adapter that saves actual DXF: 1000→1050 mm and connected-valve movement preserve
handles, then offline extraction verifies saved geometry. Also tested inches,
rollback on save failure, invalid contracts, properties, rename, inspector targeting
and overlap rejection. Full suite: 927 passed, 10 skipped; strengthened existing
route target-forwarding assertion also passed. Review: no delete/recreate or LLM
in the new engine, no active-document fallback in the new path. Definition of done
met with a file-backed test adapter; live licensed AutoCAD/DWG verification remains
unexecuted, so the real-COM acceptance criterion is only partially verified.
Roadmap compatibility interpretation: additive project edits replace neither the
legacy delete/add API contract nor the four existing generation pipelines. Unsupported
constraint graphs are rejected, not used as a reason to introduce Step 9.

## Step 7 — ChangeSet + KEEP/REVERT
Extended `backup_file()` with unique backup directories; the structured executor
backs up by default. Added `src/cad/changes.py`, changeset API routes and a shared
chat Keep/Revert card. Changes, before/after values, validation and file hashes
persist in jobs.db; `change_set_files` tracks file-level backup/rename/recovery
state missing from the roadmap's per-field item table. Pending changesets lock
their files against overlapping edits; failures retain backups and a revert action.
Revert checks later work and backup integrity, closes only explicit targets, restores
exact bytes and refreshes the index. Rename/revert stays filesystem-only. Tests
cover backup collisions, exact byte restoration, index refresh, persistence,
one-shot finalization, pending conflicts, later edits, partial multi-file failure,
rename rollback and HTTP actions. Full suite: 935 passed, 10 skipped; JS syntax
check passed. Definition of done fully met using real file I/O plus the COM adapter;
live AutoCAD close/restore remains unverified. Review: no delete/recreate, implicit
target or LLM additions. Existing generation approval caches remain compatible;
new project operations use the shared mechanism. Only our added script include
is staged in sketch.html; the user's pre-existing changes remain uncommitted.

## Step 1 follow-up — explicit project-ID return contract (2026-09-20)
The latest request narrowed this pass to Step 1. The actual checkout already had
Steps 1–7 committed and unfinished Step 8 work; that work was preserved rather
than rebuilt or removed. Windows and installed pywin32 were confirmed. Fresh
baseline: **935 passed, 10 skipped, 0 failed** (111.75 seconds). Corrected
`register_project(name, root_path)` to return the project ID string, as explicitly
requested; callers needing a record use `get_project(project_id)`. Added three
storage regression tests proving all eleven required tables share the existing
jobs connection/database, existing jobs schema/indexes/rows and logging survive
initialization, and multiple registrations persist. The original registration
test now explicitly asserts the string-ID contract. Full suite after changes:
**938 passed, 10 skipped, 0 failed** (93.25 seconds). Step 1 definition of done met.

No files were created in this follow-up. Exact changed-file inventory:

- `src/storage/project_repository.py` — return the ID instead of the row.
- `tests/project/test_storage.py` — contract and additive-schema/audit regression tests.
- `tests/project/test_changes.py` — consume the returned ID directly.
- `tests/project/test_entity_index.py` — consume the returned ID directly.
- `tests/project/test_modification.py` — consume the returned ID directly.
- `tests/project/test_scanner.py` — consume the returned ID directly.
- `tests/project/test_spatial.py` — consume the returned ID directly.
- `src/api/routes/projects.py` — preserve the existing work-in-progress API response
  shape by fetching the registered record by ID; this file remains part of the
  uncommitted Step 8 work, not the Step 1 follow-up commit.
- `IMPLEMENTATION_LOG.md` — this record.

The pre-existing Step 1 implementation files were created in commit `7c58cc5`:
`src/storage/__init__.py`, `src/storage/database.py`,
`src/storage/project_repository.py`, `src/storage/schema.sql`,
`tests/project/conftest.py`, `tests/project/test_storage.py`, and this log.
That initial Step 1 ran from 892 passed/10 skipped to 895 passed/10 skipped.

Review: no changes to `src/logging/db.py` or `src/api/main.py` in this follow-up;
their SHA256 hashes remained respectively
`2A072529843BBE289252C40B29C4F20855BDB21991CCF68422B5FD53BCB2B091` and
`CD46C28F39AEE2A9A26BD605AE6446C3CA63E4AEFA83E06975ED1A02DD4106A6`.
No second production database, no jobs-table alterations, no new audit middleware
behavior. Previously authored later-step middleware edits remain in the working
tree and are outside this follow-up. Step 8 is not claimed complete; Step 9 has
not been implemented or measured.

## Step 2 follow-up — explicit converter interface (2026-09-20)
The six-method `DrawingExtractor` ABC and working `DXFExtractor` were already
committed in `f849631`. The latest Step 2 request exposed one contract gap:
conversion was injectable but had no named interface. Added
`src/cad/extractor/converter.py` with a `DWGToDXFConverter` protocol, typed
`DXFExtractor` against it, and made `ODAConverter` implement it. Updated the
synthetic on-disk DXF fixture to include a custom document property and asserted
the fake converter and optional ODA adapter satisfy the interface. Focused tests:
4 passed. Full suite before: 938 passed, 10 skipped, 0 failed (92.62 seconds);
after: 938 passed, 10 skipped, 0 failed (90.30 seconds). The extractor package
has no imports of COM/pywin32, SQLite, or `src.storage`; direct DXF extraction
requires neither ODA nor a running AutoCAD process. Real ODA conversion was not
executed. Changed files: `src/cad/extractor/__init__.py`,
`src/cad/extractor/dxf_extractor.py`, `src/cad/extractor/oda.py`,
`tests/project/test_extractor.py`, and this log; created
`src/cad/extractor/converter.py`. The pre-existing Step 8 worktree changes
remain untouched.

## Step 3 follow-up — direct extraction-call proof and COM-free scan lock (2026-09-20)
The incremental scanner from commit `f1395ef` already implemented stat →
conditional SHA-256 → conditional extraction, process-based offline reads and
parent-only database writes. Added a test in `tests/project/test_scanner.py`
that spies on `DXFExtractor.extract`: four calls for four fixture DXFs on the
first scan and zero more on an unchanged second scan. Moved the shared lock to
new `src/cad/locks.py`; `src/cad/session.py` re-exports it for existing writers,
and `src/cad/scanner.py` imports only that neutral module. A source check found
no win32com, pythoncom, AutoCAD session, or document-opening call in the scanner
or lock module. Focused scanner tests: 6 passed. Full suite before: 938 passed,
10 skipped, 0 failed (85.56 seconds); after: 939 passed, 10 skipped, 0 failed
(93.64 seconds). The existing uncommitted Step 8 backup-directory exclusion in
`scanner.py` was preserved but not staged in this Step 3 commit.

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

# Implementation Roadmap

Build in this order. Each step depends on the ones before it — do not skip ahead. Every step
stays on Python + `pywin32` COM; none of them require the platform decision in
[08_com_vs_dotnet_decision.md](08_com_vs_dotnet_decision.md) to be made first.

## Step 1 — Project registration + SQLite schema

- Create the new tables from [03_sqlite_schema.md](03_sqlite_schema.md) in the existing
  `jobs.db` database, using the same connection pattern as `src/logging/db.py` (same file, WAL
  mode already on — don't create a second database).
- New module, e.g. `src/storage/` (`database.py`, `project_repository.py`).
- **Definition of done:** can register a project (a root folder + name) and list registered
  projects back out.

## Step 2 — `DrawingExtractor` abstraction

- New package, e.g. `src/cad/extractor/` — `base.py` (the interface from
  [04_drawing_extractor_design.md](04_drawing_extractor_design.md)) and `dxf_extractor.py` (the
  first real implementation: ODA File Converter + `ezdxf`).
- **Definition of done:** `DXFExtractor` can pull entities/blocks/properties out of one real
  file and print them — no SQLite involved yet, just proving the extraction path works.

## Step 3 — Multi-file offline scanner

- Wires `DXFExtractor` + `project_repository` together; walks a project's `root_path`; applies
  the incremental hash/mtime check from [03_sqlite_schema.md](03_sqlite_schema.md).
- **Definition of done:** pointing it at a real folder of N DWGs populates the `drawings` table;
  re-running immediately with no file changes re-extracts 0 files.

## Step 4 — Persistent entity/component index

- The scanner (step 3) now also populates `entities`/`entity_properties`/`entity_geometry`.
- **Definition of done:** "which file(s) contain a component tagged P-101" is answerable with one
  SQL query, no file opened.

## Step 5 — Relationships + spatial index

- Populate `relationships` during extraction (e.g. proximity/connectivity heuristics — a pipe
  endpoint coincident with a valve's connection point implies `connected_to`).
- Build the `spatial_index` table (R\*Tree, with the `scipy.spatial.cKDTree` fallback noted in
  [03_sqlite_schema.md](03_sqlite_schema.md) if R\*Tree isn't available).
- **Definition of done:** "what's within 100mm of pipe P-101" is answerable without a full table
  scan.

## Step 6 — Structured modification engine

- Add the new command/operation types from
  [05_structured_operations_and_editing.md](05_structured_operations_and_editing.md)
  (`RESIZE_COMPONENT`, `SET_ENTITY_PROPERTY`, `SET_DOCUMENT_PROPERTY`, `SET_LAYER_COLOR`,
  `RENAME_FILE`) to `src/framework/commands/schema.py`.
- Add a new executor path (extend `src/framework/commands/executor.py` or add a sibling module)
  that uses `HandleToObject` + in-place property assignment — no delete/recreate.
- Extend `src/framework/autocad/inspector.py` to accept an explicit target path (mirroring the
  `target_dwg_path` pattern `executor.py:391-399` already has), so metadata extraction stops
  being active-document-only.
- **Definition of done:** "resize P-101 by 50mm" modifies the existing entity in place, in the
  correct explicitly-named file (never the active-document fallback), verified by re-extracting
  the file afterward and seeing the new value.

## Step 7 — ChangeSet + KEEP/REVERT

- Wire `src/backup.py`'s `backup_file()` into the new executor path from step 6 (currently
  missing entirely from `execute_command_sequence`/`execute_edit_plan` — a real existing bug
  worth fixing regardless of this roadmap).
- Add `change_sets`/`change_set_items`/`validation_results` tables (already in the step 1
  schema); wire the chat UI to show Keep/Revert per [07_changeset_and_revert.md](07_changeset_and_revert.md).
- **Definition of done:** an edit can be reverted to the exact pre-edit file state via one action.

## Step 8 — Project-aware AI orchestration

- The AI planner now queries SQLite for the specific relevant entity/entities instead of
  receiving a full drawing dump (fixes the token-cost issue directly).
- The chatbot gains a "selected project" context instead of implicitly operating on "whatever's
  active."
- One AI plan can fan out to multiple `job_items` (per [03_sqlite_schema.md](03_sqlite_schema.md)'s
  `jobs_multi_file`/`job_items` tables), consumed by the write queue described in
  [06_multi_project_and_scanning.md](06_multi_project_and_scanning.md).
- **Definition of done:** "increase P-101 by 50mm in all affected drawings" produces one AI
  planning call, touches only the actually-affected files (confirmed via the SQLite index, not
  by opening everything), and offers KEEP/REVERT at the end.

## Step 9 — Measure, then decide (not scheduled)

Once steps 1-8 are real and in use against real project files, revisit
[08_com_vs_dotnet_decision.md](08_com_vs_dotnet_decision.md)'s decision table with actual
evidence:
- **9A** — COM remains sufficient (the expected, default outcome).
- **9B** — introduce a thin `.NET` engine behind the `DrawingExtractor` interface, only if
  constraint manipulation or measured write-path performance actually demands it.
- **9C** — introduce a Plant 3D-specific engine, only if real files turn out to use Plant 3D
  intelligent objects.

This step is intentionally not scheduled with a date or file list — it's conditional, and
building it before there's evidence would be exactly the premature architecture bet this whole
roadmap was designed to avoid.

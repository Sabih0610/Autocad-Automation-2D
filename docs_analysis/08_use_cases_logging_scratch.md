# `src/use_cases/`, `src/logging/`, `src/scratch/` — Deep Reference

This document exhaustively covers three areas of the AutoCAD AI Automation codebase
(project root `F:\RC-Projects\autocad-ai\autocad-ai`):

- `src/use_cases/` — higher-level workflow functions, originally the CLI-style entry
  points for each project "phase". Some are still imported and driven by the FastAPI
  routes (`src/api/routes/*.py`); others have been superseded by logic written
  directly into the routes and are now reachable only by running the module directly
  (`python -m src.use_cases.<name>`).
- `src/logging/` — a tiny SQLite-backed job/audit trail (`jobs.db` at the project
  root) used both by the CLI decorator `@log_job(...)` and by the FastAPI audit
  middleware in `src/api/main.py`.
- `src/scratch/` — ad-hoc developer scripts and one-off smoke tests written while
  building each phase. None of them are imported by production code (routes, use
  cases, ai, framework); they are only ever run directly with `python -m
  src.scratch.<name>`.

All file paths below are relative to the project root unless given in full.

---

## 1. Role in the system

**`src/use_cases/`** is the original "vertical slice" layer of this project: before
the FastAPI web app (`src/api/`) existed, each phase of development produced a
standalone script under `src/use_cases/` that could be run from the command line
with `python -m src.use_cases.<module>`, talking to a running AutoCAD instance over
COM (`win32com.client`) and/or an AI planner module under `src/ai/`. When the FastAPI
layer was added (Phase 7 onward, per in-code comments), some routes were wired to
literally `import` and call functions/module-level state from these use_cases
modules (a thin wrapper pattern — see `src/api/routes/consistency.py`,
`title_block.py`, `line_list.py`, `place_symbol.py`). Later, more sophisticated
routes (`vessel.py`, `sketch.py`) were built that call the lower-level `src.ai.*`
and `src.parametric.*` / `src.framework.*` modules **directly**, bypassing their
corresponding use_cases modules (`generate_vessel.py`, `sketch_drawing.py`,
`ai_place_symbol.py`) entirely. Those bypassed use_cases modules still work if run
from the CLI, but are dead code from the web app's point of view.

**`src/logging/`** is a minimal, dependency-free SQLite audit trail. It has no
relationship to Python's standard `logging` module (despite the package name) — it
records structured "job" records (one row per CLI invocation or API call) into a
single `jobs` table in `jobs.db` at the project root. It is used two ways: (1) the
`@log_job(...)` decorator in `decorators.py` wraps use_cases `main()`/entry-point
functions for CLI runs; (2) the `AuditJobMiddleware` ASGI middleware in
`src/api/main.py` wraps whitelisted API routes (via `AUDIT_ROUTE_MAP`) for web runs.
Both paths write into the same `jobs` table and are visible through the `/api/jobs`
and `/api/jobs/{job_id}` endpoints in `src/api/main.py`.

**`src/scratch/`** is a scratch pad of throwaway/experimental scripts written while
building and debugging each phase (COM connectivity smoke tests, AI provider smoke
tests, batch symbol-insertion stress tests, a mismatch-data generator for testing
the consistency checker, and library smoke tests for `openpyxl`, `ezdxf`, and
`fluids`). None of it is imported by anything else in `src/`; it is purely
developer tooling / historical scratch work, safe to ignore or delete without
affecting the app, though a couple of scripts (`make_mismatch_line_list.py`,
`execute_ai_symbol_batch_small.py`/`_full.py`) remain handy for manually re-testing
`consistency_check` and `place_symbol` respectively.

---

## 2. `src/use_cases/` — per-file reference

### 2.1 `ai_place_symbol.py`

- **Purpose**: Phase 5 "AI-driven symbol placer" CLI. Pipeline: natural-language
  prompt → `src.ai.symbol_planner.plan_symbol_placement()` → validated JSON spec →
  `src.use_cases.place_symbol.insert_symbol()` executes against AutoCAD.
- **Key function**: `main()` (module-level, decorated `@log_job("place_symbol")`,
  `ai_place_symbol.py:36`). Not a reusable function — it's an `argparse` CLI
  entrypoint only (`--prompt`, `--execute`).
- **Inputs**: `--prompt` (str, defaults to a canned pump-placement sentence),
  `--execute` (flag; without it, runs dry-run only via `insert_symbol(..., dry_run=True)`).
- **Outputs / side effects**: Prints the planned JSON and result dict to stdout;
  if `--execute` is passed and insertion succeeds, calls `acad.ZoomExtents()`. No
  files are written directly by this module (the AI call may hit an external LLM
  API through `src.ai.symbol_planner`).
- **AutoCAD calls**: Via `place_symbol.connect_to_autocad()` / `place_symbol.insert_symbol()` (COM).
- **Live vs legacy**: **Legacy / CLI-only.** Grepping `src/api/**` for
  `from src.use_cases` shows the API's `/api/place-symbol` route
  (`src/api/routes/place_symbol.py:12-13`) imports `plan_symbol_placement` from
  `src.ai.symbol_planner` and `connect_to_autocad`/`insert_symbol` from
  `src.use_cases.place_symbol` **directly**, re-implementing this same
  plan→insert flow inline rather than calling `ai_place_symbol.main()` (which isn't
  even importable as a normal function — it's an argparse-driven `main()`). So this
  module is only reachable by running it as a script.

### 2.2 `consistency_check.py`

- **Purpose**: Phase 6 deterministic P&ID-vs-Excel consistency checker (no AI). Reads
  `LINE_BLOCK_TEST` block attributes from a P&ID DWG via AutoCAD COM, reads a
  generated line-list Excel workbook, normalizes and compares both datasets, and
  writes an Excel mismatch report.
- **Config constants**: `RPC_E_CALL_REJECTED = -2147418111`; `PROJECT_ROOT` (2
  parents up from file); `OUTPUT_FOLDER = PROJECT_ROOT/"outputs"`; `DRAWINGS_FOLDER
  = Path(r"E:\RC-Projects")`; `DEFAULT_PID_DWG = DRAWINGS_FOLDER/"pid_001.dwg"`;
  `LINE_BLOCK_NAME = "LINE_BLOCK_TEST"`; `LINE_COLUMNS = ["LINE_NO","SIZE","SPEC","SERVICE","FROM","TO"]`;
  `COMPARE_COLUMNS = ["SIZE","SPEC","SERVICE","FROM","TO"]` (LINE_NO is matched on,
  not "compared", hence excluded).
- **Key functions** (all module-level, all imported directly by the API route):
  - `is_autocad_busy_error(error) -> bool`, `is_stale_proxy_error(error) -> bool`:
    classify transient COM failures.
  - `com_retry(operation: Callable[[], Any], description: str, attempts=5, delay_seconds=0.5)`:
    generic retry wrapper for flaky AutoCAD COM calls.
  - `get_acad()`: `win32com.client.GetActiveObject("AutoCAD.Application")`, exits
    the process (`sys.exit(1)`) on failure — **not safe to call from a long-lived
    server process without try/except**, though the API route only calls the other
    functions, not this one directly, for the P&ID/AutoCAD path (it calls
    `deterministic.extract_pid_lines`, which internally calls `get_acad()` and would
    hard-exit the whole FastAPI worker process if AutoCAD isn't reachable — see
    Cross-cutting Observations).
  - `open_drawing_with_retry(acad, drawing_path: Path)`: opens a DWG with up to 3
    outer retries, each internally retrying via `com_retry`, re-acquiring `acad` if
    stale.
  - `get_block_name(block_ref) -> str`, `extract_attributes(block_ref) -> Dict[str,str]`,
    `find_line_blocks(model_space, block_name)` (generator over `AcDbBlockReference`
    entities matching `block_name` via `EffectiveName`).
  - `clean_value`, `normalize_line_no` (strips everything except `[A-Z0-9]`,
    uppercased), `normalize_compare_value` (uppercase + collapse whitespace),
    `normalize_row`.
  - `extract_pid_lines(pid_path: Path) -> List[Dict[str,str]]`: opens the P&ID DWG,
    finds all `LINE_BLOCK_TEST` refs, extracts+normalizes their attributes, tags
    each row with `_SOURCE="P&ID"` / `_SOURCE_INDEX`, closes the doc (`doc.Close(False)`)
    in a `finally`.
  - `find_latest_line_list_excel() -> Path`: globs `outputs/line_list_pid_001_*.xlsx`
    (falls back to `outputs/line_list_*.xlsx`), filters out report/mismatch/AI-output
    files by filename pattern, returns the most recently modified match; `sys.exit(1)`
    if none found.
  - `find_header_row(ws) -> Tuple[int, Dict[str,int]]`: scans first 30 rows for a row
    containing all of `LINE_COLUMNS`.
  - `read_excel_line_list(excel_path: Path) -> List[Dict[str,str]]`: reads rows below
    the header, tags each with `_SOURCE="EXCEL"`.
  - `index_rows_by_line_no(rows, source_name) -> (index, issues)`: groups by
    `normalize_line_no`, flags `MISSING_LINE_NO` and `DUPLICATE_LINE_NO` issues.
  - `compare_pid_vs_excel(pid_rows, excel_rows) -> List[Dict[str,str]]`: produces a
    flat list of mismatch dicts with `type` ∈ `{MISSING_LINE_NO, DUPLICATE_LINE_NO,
    MISSING_IN_EXCEL, MISSING_IN_PID, FIELD_MISMATCH}`, each with `line_no`, `field`,
    `pid_value`, `excel_value`, `details`.
  - `style_header_row`, `auto_width`, `write_rows_sheet`, `write_report(report_path,
    pid_path, excel_path, pid_rows, excel_rows, mismatches)`: builds a 4-sheet
    workbook (`Summary`, `Mismatches`, `P&ID Lines`, `Excel Lines`) via `openpyxl`
    and saves it to `report_path`.
  - `main()` (decorated `@log_job("consistency_check")`): argparse CLI
    (`--pid`, `--excel`, `--report`), orchestrates the whole flow, prints a text
    summary, writes the report.
- **Side effects**: Opens/closes DWG documents in AutoCAD (read-only, closes with
  `doc.Close(False)` so no DWG is ever saved/modified); writes an `.xlsx` report file
  under `outputs/`.
- **Live vs legacy**: **Live.** `src/api/routes/consistency.py:24-119` (`POST
  /api/consistency-check`) imports this module as `deterministic` and calls
  `find_latest_line_list_excel`, `extract_pid_lines`, `read_excel_line_list`,
  `compare_pid_vs_excel`, `write_report`, and reads `OUTPUT_FOLDER` directly — i.e.
  nearly the entire public surface of this module is exercised by the web API. Only
  its own `main()`/CLI parsing is unused by the API (the route re-implements the CLI
  orchestration itself).

### 2.3 `consistency_check_ai.py`

- **Purpose**: Phase 6 AI-explanation wrapper around `consistency_check.py`. Runs the
  same deterministic P&ID-vs-Excel comparison, writes the same Excel report, then
  calls `src.ai.consistency_explainer.explain_consistency_mismatches(mismatches)` to
  produce a plain-English explanation, and writes that explanation to disk as JSON
  and a manager-friendly `.txt`. Explicit design note in the docstring: "AI does NOT
  decide whether something matches. AI only explains the mismatches already found by
  code."
- **Key functions**:
  - `write_ai_outputs(explanation: dict, base_name: str) -> tuple[Path, Path]`:
    writes `outputs/{base_name}_ai_explanation.json` (raw JSON dump of the
    explanation dict) and `outputs/{base_name}_manager_summary.txt` (a formatted
    text report built from `overall_status`, `issue_count`, `summary`, `issues[]`
    (each with `line_no`, `field`, `problem`, `likely_impact`, `recommended_action`),
    and `manager_message`). Returns `(json_path, txt_path)`.
  - `main()` (decorated `@log_job("consistency_check_ai")`): argparse CLI (`--pid`,
    `--excel`, `--report`) that re-derives `pid_rows`/`excel_rows`/`mismatches` by
    calling the imported functions from `consistency_check` (re-exported at module
    top: `DEFAULT_PID_DWG`, `OUTPUT_FOLDER`, `compare_pid_vs_excel`,
    `extract_pid_lines`, `find_latest_line_list_excel`, `read_excel_line_list`,
    `write_report`), then calls `explain_consistency_mismatches` and
    `write_ai_outputs`.
- **Side effects**: Same DWG open/close as `consistency_check.py`; writes an `.xlsx`
  report, a `.json` explanation file, and a `.txt` manager summary, all under
  `outputs/`; makes an external AI call via `src.ai.consistency_explainer`.
- **Live vs legacy**: **Partially live.** `src/api/routes/consistency.py:29,96-99`
  imports this module as `ai_wrapper` and calls **only** `ai_wrapper.write_ai_outputs(...)`
  when `request.use_ai_explanation` is true — the route re-implements the
  orchestration (extract → compare → write_report → explain → write_ai_outputs)
  itself using functions from both `consistency_check` and
  `src.ai.consistency_explainer` directly, so this module's own `main()` and its
  re-exported orchestration logic are not invoked by the API; only the leaf
  `write_ai_outputs` helper is reused.

### 2.4 `generate_vessel.py`

- **Purpose**: Phase 20 end-to-end vessel generator. Pipeline: natural-language
  vessel request → `src.ai.vessel_planner.plan_vessel()` extracts structured
  parameters → interactive user review/confirmation (`input(...)`) →
  `src.parametric.vessel.parameters.validate_parameters()` → 
  `src.parametric.vessel.render.render_vessel()` writes a DXF or DWG.
- **Key function**: `generate_vessel(user_prompt: str, output_format: str = "dwg",
  auto_confirm: bool = False) -> dict[str, Any]` (`generate_vessel.py:65`, decorated
  `@log_job("generate_vessel")`). This one, unlike most use_cases files, is a real
  reusable function (not just a CLI `main()`), returning a structured result dict
  with keys `ok`, `format`, `path`, `dxf_intermediate`, `scale`, `sheet`,
  `vessel_tag`, `extracted`, `message` (or `ok=False` + `reason`/`errors` on
  failure/validation error/user cancellation).
- **Fallback logging shim**: Defines `_identity_log_job(name)` (a no-op decorator
  factory) and only uses the real `log_job` if `from src.logging.decorators import
  log_job` succeeds — i.e. this module is written to run even if `src/logging` is
  broken/missing, unlike the other use_cases modules which import `log_job`
  unconditionally.
- **Side effects**: Writes an AI-generated-and-validated vessel drawing to
  `outputs/vessels/{safe_tag}_ai_{timestamp}.{dxf|dwg}`; DWG output requires AutoCAD
  running (via `render_vessel`); blocks on `input()` for confirmation unless
  `auto_confirm=True`.
- **Also has** `_cli()` (module `argparse` entrypoint: `--prompt`, `--format
  {dxf,dwg}`, `--yes`) that calls `generate_vessel(...)` and prints the result.
- **Live vs legacy**: **Legacy — NOT called by the API.** `src/api/routes/vessel.py`
  implements the same conceptual pipeline as two separate endpoints
  (`POST /api/generate-vessel/extract`, `POST /api/generate-vessel/confirm`) but
  calls `src.ai.vessel_planner.plan_vessel/format_for_review/extracted_to_vessel_parameters`,
  `src.parametric.vessel.parameters.validate_parameters`, and
  `src.parametric.vessel.render.render_vessel` **directly** — it does not import
  `src.use_cases.generate_vessel` at all (confirmed by grep; no
  `from src.use_cases` or `use_cases\.` hit in `vessel.py`). The web route replaces
  the interactive `input()` confirmation with a token-cache
  extract→confirm two-step flow (`_token_cache`, 10-minute TTL) instead. So
  `generate_vessel()` (the function) and `_cli()` are only reachable by running
  `python -m src.use_cases.generate_vessel` directly.

### 2.5 `line_list_extract.py`

- **Purpose**: Phase 3 line-list extractor. Opens a fixed target P&ID DWG
  (`E:\RC-Projects\pid_001.dwg`), finds every `LINE_BLOCK_TEST` block, extracts
  attributes, prints a console table, and writes a styled Excel line list.
- **Config**: `DRAWINGS_FOLDER = Path(r"E:\RC-Projects")`; `LINE_BLOCK_NAME =
  "LINE_BLOCK_TEST"`; `TARGET_FILE = "pid_001.dwg"`; `LINE_LIST_COLUMNS =
  ["LINE_NO","SIZE","SPEC","SERVICE","FROM","TO"]`; `OUTPUT_FOLDER =
  <project_root>/outputs`.
- **Key functions**:
  - `get_acad()`: plain `win32com.client.GetActiveObject(...)`, no retry logic
    (simpler/older than the retry-hardened versions in `consistency_check.py`/`place_symbol.py`).
  - `find_blocks_by_name(model_space, block_name)`: generator, matches on raw
    `entity.Name` (not `EffectiveName` — a difference from `consistency_check.py`'s
    `find_line_blocks`, which is more robust to dynamic/anonymous blocks).
  - `extract_attributes(block_ref) -> dict`; `normalize_row(attrs, expected) -> dict`.
  - `write_line_list_xlsx(rows, source_dwg_name, output_path)`: writes a styled
    workbook with a title row (merged), a metadata row (source + timestamp,
    merged), a styled header row at row 4, data starting row 5, freeze panes at
    `A5`, auto-fit column widths.
  - `main()` (decorated `@log_job("line_list_extract")`): opens the DWG, extracts
    blocks, prints an aligned console table, writes the Excel file
    (`outputs/line_list_pid_001_{timestamp}.xlsx`), and prints any rows with missing
    attribute values.
- **Side effects**: Opens/closes (`doc.Close(False)`) the target DWG; writes one
  `.xlsx` file per run under `outputs/`.
- **Live vs legacy**: **Live, but only as a shared-state module.**
  `src/api/routes/line_list.py:33` imports the module as `use_case` and calls its
  `get_acad`, `find_blocks_by_name`, `extract_attributes`, `normalize_row`,
  `write_line_list_xlsx` functions directly, plus reads/writes the module-level
  globals `DRAWINGS_FOLDER`, `TARGET_FILE`, `LINE_BLOCK_NAME`, `OUTPUT_FOLDER`,
  `LINE_LIST_COLUMNS` — the route's `_temporary_module_settings()` context manager
  monkey-patches `DRAWINGS_FOLDER`/`TARGET_FILE`/`LINE_BLOCK_NAME` onto the imported
  module object for the duration of one request, then restores the originals in a
  `finally` (explicit comment: "wrap the existing module-level constants without
  editing the use case itself"). `main()` itself is not called by the route (the
  route re-implements the orchestration inline), but every helper function is.

### 2.6 `place_symbol.py`

- **Purpose**: Phase 5 deterministic symbol-placement **executor**. Docstring is
  explicit: "This executor does NOT call AI. It only executes already-planned
  JSON." Takes a plan dict (as produced by `src.ai.symbol_planner`) and inserts a
  block reference into AutoCAD's active document, then reads the result back and
  verifies it matches the spec.
- **Config**: `RPC_E_CALL_REJECTED = -2147418111`; `VALID_BLOCKS = {"GATE_VALVE",
  "CHECK_VALVE", "CONTROL_VALVE", "PUMP", "VESSEL", "INSTRUMENT_BUBBLE"}`;
  `TEST_SPEC` (a canned gate-valve spec used only by this module's own `main()`).
- **Key functions**:
  - `point(x,y,z=0.0)`: builds an AutoCAD COM `VARIANT(VT_ARRAY|VT_R8, [x,y,z])`.
  - `is_autocad_busy_error`, `com_retry`, `safe_com_get(obj, property_name, default=None)`
    (wraps `com_retry` + `getattr`, swallows failures, returns `default`).
  - `connect_to_autocad() -> (acad, doc)`: `GetActiveObject("AutoCAD.Application")`
    + `acad.ActiveDocument`; `sys.exit(1)` with a printed error if either fails —
    **this is imported and called directly by `src/api/routes/place_symbol.py`**, so
    an unreachable AutoCAD instance will call `sys.exit(1)` inside a live FastAPI
    request (see Cross-cutting Observations); the route only wraps this in a
    `try/except SystemExit` to convert it to an HTTP 503, which works but is a code
    smell (uses `SystemExit` as a control-flow signal from a "library" function).
  - `block_exists`, `layer_exists`, `ensure_layer` (creates the layer via
    `doc.Layers.Add` if missing).
  - `almost_equal(a,b,tolerance=0.001)`; `normalize_point(raw_point) -> List[float]`.
  - `get_block_name`, `get_block_attributes`, `get_block_handle`.
  - `validate_symbol_spec(doc, spec) -> List[str]`: checks `task_type ==
    "place_symbol"`, `block_name` is one of `VALID_BLOCKS` and exists as a block
    definition in `doc`, `insertion_point.{x,y,z}` present/numeric,
    `rotation_degrees`/`scale` numeric (`scale>0`), `layer` non-empty string,
    `attributes.{TAG,SIZE,SERVICE}` non-empty strings. Returns a list of human
    -readable error strings (empty = valid).
  - `set_block_attributes(block_ref, values) -> List[str]` (warnings for
    tags present in `values` but not found on the block, and vice versa via
    `found_tags`), calls `att.Update()` per attribute and `block_ref.Update()`.
  - `readback_from_block_ref(block_ref, handle, source) -> dict`: reads back
    `insertion_point`, `layer`, `rotation_degrees` (converted from radians),
    `scale.{x,y,z}`, `object_name`, `block_name`, `attributes` directly off the COM
    object just returned by `InsertBlock`.
  - `readback_from_handle(doc, handle) -> dict`: same, but via
    `doc.HandleToObject(handle)` — used as a fallback strategy.
  - `evaluate_readback(readback, expected_spec) -> dict` with keys `ok`,
    `readback`, `mismatches` (a list of human-readable mismatch strings comparing
    block name, layer, x/y/z, rotation, x/y/z scale, and each expected attribute).
  - `verify_inserted_symbol(doc, handle, expected_spec, block_ref=None) -> dict`:
    tries the fresh `block_ref` proxy first, falls back to
    `HandleToObject`-based readback if the first fails or mismatches; returns
    `{ok, readback, mismatches, attempts}`.
  - `insert_symbol(doc, spec: Dict[str,Any], dry_run: bool = True) -> Dict[str,Any]`
    (`place_symbol.py:614`) — **the main reusable entrypoint**, imported directly by
    both `ai_place_symbol.py` and the API route. Validates the spec; if invalid,
    returns `{ok:False, dry_run, inserted:False, verified:False, errors, warnings:[]}`
    without touching AutoCAD. If `dry_run=True` and spec is valid, returns
    `{ok:True, dry_run:True, inserted:False, verified:False, message, planned_insert:{...}}`
    with no AutoCAD side effects. Otherwise: ensures the target layer exists, sets
    `doc.ActiveLayer`, calls `model.InsertBlock(point(x,y,z), block_name, scale,
    scale, scale, rotation_radians)`, sets attributes via `set_block_attributes`,
    calls `block_ref.Update()`/`doc.Regen(1)`, sleeps 0.5s, reads back the handle,
    runs `verify_inserted_symbol`, restores the previous `ActiveLayer`, and returns a
    result dict with `ok`, `dry_run:False`, `inserted:True`, `verified`, `message`,
    `handle`, `block_name`, `layer`, `attributes`, `verification`, `errors`,
    `warnings`.
  - `main()`: CLI (`--execute` flag) that runs `insert_symbol` against the canned
    `TEST_SPEC`.
- **Side effects**: Inserts/modifies block references (and possibly creates layers)
  in the **active** AutoCAD document (does not open/close/save any DWG itself — it
  operates on whatever document is already active).
- **Live vs legacy**: **Live** (the executor half). `src/api/routes/place_symbol.py:13`
  imports `connect_to_autocad` and `insert_symbol` directly and is the sole caller
  from the web app. `ai_place_symbol.py`, `execute_ai_symbol_batch_full.py`,
  `execute_ai_symbol_batch_small.py`, `test_ai_symbol_batch.py`, and
  `test_symbol_verification_fix.py` (the latter four all in `src/scratch/`) also
  import from this module for CLI/manual testing. `main()` itself and `TEST_SPEC`
  are CLI-only.

### 2.7 `setup_symbol_test_blocks.py`

- **Purpose**: One-time Phase 5 setup script. Creates 6 hand-drawn AutoCAD block
  **definitions** (`GATE_VALVE`, `CHECK_VALVE`, `CONTROL_VALVE`, `PUMP`, `VESSEL`,
  `INSTRUMENT_BUBBLE`), each with `TAG`/`SIZE`/`SERVICE` attributes, directly via
  COM drawing primitives (`AddLine`, `AddCircle`, `AddArc`, `AddAttribute`), then
  inserts one preview instance of each on a dedicated layer (`P-SYMBOL-TEST`) so a
  human can visually confirm the shapes before saving the drawing as
  `symbol_test.dwg`.
- **Key functions**: `point`, `connect_to_autocad`, `block_exists`, `layer_exists`,
  `ensure_layer`, `add_common_attributes(block)` (adds `TAG`/`SIZE`/`SERVICE` text
  attributes at fixed offsets), one `create_<symbol>(doc)` function per block type
  (each is idempotent — skips creation if the block name already exists),
  `set_block_attributes(block_ref, values)`, `clear_old_preview_symbols(doc)`
  (deletes prior preview instances on `P-SYMBOL-TEST` before re-inserting, so
  re-running the script doesn't stack duplicate previews),
  `insert_preview_symbols(doc)` (lays the 6 previews out left-to-right, 80-unit
  spacing), `main()` (creates all 6 block defs, inserts previews, regens, zooms
  extents, and prints a reminder to save the file as
  `E:\RC-Projects\symbol_test.dwg`).
- **Side effects**: Mutates the currently-active AutoCAD document's block table and
  ModelSpace (new block definitions + preview instances); does not save the drawing
  itself (leaves that to the human).
- **Live vs legacy**: **Legacy — dev/setup-only.** Not imported anywhere in
  `src/api/**` or elsewhere in `src/`. It exists purely to prepare the
  `symbol_test.dwg` fixture that `place_symbol.py`/`ai_place_symbol.py` and the
  `/api/place-symbol` route depend on being open in AutoCAD; it is not itself part
  of any runtime request path.

### 2.8 `sketch_drawing.py`

- **Purpose**: "Mode 2" sketch-drawing CLI. Pipeline: natural-language prompt →
  `src.ai.command_generator.generate_commands()` → optional
  `src.ai.command_verifier.verify_commands()` AI review → optional DXF preview via
  `src.framework.commands.preview.render_preview_sequence()` → interactive
  confirmation (`input(...)`) → `src.framework.commands.executor.execute_command_sequence()`.
- **Key function**: `sketch_drawing(prompt, auto_confirm=False, save=True,
  target_dwg_path=None, run_verifier=True, create_preview=True,
  preview_output_path=None) -> dict` (`sketch_drawing.py:115`, decorated
  `@log_job("sketch_drawing")`). Like `generate_vessel.py`, this module defines the
  same `_identity_log_job` fallback pattern so it still works if `src.logging` is
  unavailable.
- Helper printers: `_print_review(command_sequence)`, `_print_verifier_review(verifier_result)`,
  `_confirmation_prompt_for(verifier_verdict)`, `_default_preview_output_path()`
  (`outputs/previews/sketch_preview_{timestamp}.dxf`).
- **Also has** `_cli()`: argparse entrypoint (`--prompt`, `--yes`, `--no-save`,
  `--target-dwg`, `--skip-verifier`, `--skip-preview`, `--preview-output`).
- **Return dict shape**: `{ok, executed, prompt, summary, estimated_drawing_type,
  assumptions, command_count, verifier_result, verifier_verdict, preview_path,
  preview_created, execution_result}` (or an early-return failure dict on empty
  prompt / preview failure / user cancellation).
- **Side effects**: Writes a DXF preview file under `outputs/previews/`; if
  confirmed, executes AutoCAD commands and optionally saves the drawing (via
  `execute_command_sequence`).
- **Live vs legacy**: **Legacy — NOT called by the API.**
  `src/api/routes/sketch.py` implements `/api/sketch/generate` and
  `/api/sketch/approve` but imports `generate_commands` from
  `src.ai.command_generator`, `generate_verified_command_sequence` /
  `CommandOrchestrationError` from `src.ai.command_orchestrator`,
  `generate_chunked_verified_command_sequence` / `ChunkedCommandOrchestrationError`
  from `src.ai.chunked_command_orchestrator`, and `execute_command_sequence` /
  `render_preview_sequence` from `src.framework.commands.*` **directly** — no import
  of `src.use_cases.sketch_drawing` anywhere in the route (confirmed by grep). The
  web route is materially more advanced than this use_case: it adds a
  verify-and-repair orchestration loop and a "chunked" strategy for complex prompts
  (`_looks_complex_prompt()` heuristic switches between
  `generate_verified_command_sequence` and `generate_chunked_verified_command_sequence`),
  none of which exist in `sketch_drawing.py`. So `sketch_drawing()` and `_cli()` are
  reachable only via `python -m src.use_cases.sketch_drawing`.

### 2.9 `update_title_block.py`

- **Purpose**: Phase 2 batch title-block updater. Iterates every DWG matching
  `drawing_*.dwg` in a folder, finds `TITLE_BLOCK_TEST` block references, updates a
  fixed set of attribute values, backs up each file before modifying it, and saves.
  Supports a `DRY_RUN` module-level flag for preview-only runs.
- **Config**: `DRAWINGS_FOLDER = Path(r"E:\RC-Projects")`; `TITLE_BLOCK_NAME =
  "TITLE_BLOCK_TEST"`; `FILE_PATTERN = "drawing_*.dwg"`; `UPDATES = {"REV":"F",
  "DATE":"2026-06-01", "DRAWN_BY":"S. AAMIR"}`; `DRY_RUN = False`;
  `PAUSE_BETWEEN_FILES_SEC = 1.5`; `FILE_MAX_RETRIES = 3`; `FILE_RETRY_DELAY_SEC =
  2.0`; `RPC_E_CALL_REJECTED`/`RPC_E_SERVERCALL_RETRYLATER` HRESULT constants.
- **Key functions**:
  - `is_busy_error(exc)`: true for the two RPC HRESULTs above or any `AttributeError`
    (treated as a stale-COM-proxy symptom).
  - `get_acad()`: explicit comment that it must NOT be cached across files because
    "pywin32's proxy goes stale after enough open/close cycles."
  - `find_title_blocks(model_space, block_name)`: generator matching on raw
    `entity.Name` (not `EffectiveName`).
  - `update_attributes(block_ref, updates) -> list[(tag, old, new)]`: only changes
    attributes whose tag is in `updates` and whose value actually differs.
  - `_do_one_file(dwg_path, updates)`: single attempt — fresh `get_acad()`, opens
    the file, finds blocks, applies updates, `doc.Save()` if any changes and not
    `DRY_RUN`, closes. Returns `{blocks_found, changes, status}` where `status` ∈
    `{"no_title_block","dry_run","ok"}`.
  - `process_one_file(dwg_path, updates) -> dict`: wraps `_do_one_file` with
    up to `FILE_MAX_RETRIES` retries (only retried if `is_busy_error`), and — unless
    `DRY_RUN` — calls `backup_file(dwg_path)` from `src/backup.py` (copies the file
    into a `<BACKUP_ROOT>/<timestamp>/` folder) **before** attempting any
    modification. Returns `{file, backup, blocks_found, changes, status, error}`.
  - `print_summary(results)`: console table + counts by status.
  - `main()` (decorated `@log_job("title_block_update")`): globs
    `DRAWINGS_FOLDER/FILE_PATTERN`, pings AutoCAD, iterates files with
    `PAUSE_BETWEEN_FILES_SEC` delay between each, calls `process_one_file`, prints
    summary.
- **Side effects**: Backs up (copies) each DWG before modifying it; opens, edits
  attributes on, saves, and closes each matching DWG; **this is the only use_case
  that mutates/persists DWGs on disk as its core purpose** (vs. read-only checks or
  new-object insertion into an already-open doc).
- **Live vs legacy**: **Live, as a shared-state module** (same pattern as
  `line_list_extract.py`). `src/api/routes/title_block.py:44` imports it as
  `use_case` and, via the same `_temporary_module_settings()` monkey-patch pattern,
  overrides `DRAWINGS_FOLDER`, `FILE_PATTERN`, `TITLE_BLOCK_NAME`, `UPDATES`,
  `DRY_RUN` from the request body for the duration of one call, then calls
  `use_case.get_acad()`, and `use_case.process_one_file(file_path, use_case.UPDATES)`
  per matched file directly. `main()` is not called by the route.

### 2.10 `verify_title_blocks.py`

- **Purpose**: Read-only diagnostic script — opens every `drawing_*.dwg` in
  `E:\RC-Projects`, prints each file's `TITLE_BLOCK_TEST` attribute values
  (`REV`, `DATE`, `DRAWN_BY`, `DRAWING_NO`) to the console. No writes, no backups,
  no AI.
- **Key functions**: `get_acad()`, `read_one_file(f)` (opens, scans ModelSpace for
  the title block, builds a `{tag: value}` dict, closes with `doc.Close(False)`,
  returns `None` if no block found), `main()` (iterates files with a 1.0s pause
  between each, prints a formatted line per file or an error).
- **Side effects**: None persistent — purely diagnostic console output. No
  `@log_job` decorator at all (unlike every other use_cases module except
  `setup_symbol_test_blocks.py`) — this one is not audit-logged even when run from
  the CLI.
- **Live vs legacy**: **Legacy — CLI-only.** No references anywhere under
  `src/api/**`; not wired to any route. Purely a manual verification tool a
  developer runs after `update_title_block.py` to eyeball the result.

---

## 3. `src/logging/` — deep dive

### 3.1 `db.py` — connection + schema

```python
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "jobs.db"          # SQLite file at the project root
```

Exact schema (verbatim from `SCHEMA_SQL`, `src/logging/db.py:8-27`):

```sql
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL UNIQUE,
    timestamp_start TEXT NOT NULL,
    timestamp_end TEXT,
    duration_seconds REAL,
    source TEXT NOT NULL,
    use_case TEXT NOT NULL,
    request_data TEXT,
    ai_output TEXT,
    result_data TEXT,
    status TEXT NOT NULL,
    error_message TEXT,
    user_agent TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_timestamp ON jobs(timestamp_start DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_use_case ON jobs(use_case);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
```

Column semantics (inferred from usage in `jobs.py`):
- `id` — SQLite autoincrement surrogate key (not exposed via the public API
  functions, which all key off `job_id`).
- `job_id` — a `uuid.uuid4().hex` string generated in `log_job_start`; the public
  identifier used everywhere (URL path param `/api/jobs/{job_id}`, decorator
  return value).
- `timestamp_start` / `timestamp_end` — `datetime.now().isoformat(timespec="milliseconds")`
  strings (naive, local time, no timezone).
- `duration_seconds` — computed in `log_job_end` as
  `round((ended_at - started_at).total_seconds(), 3)`, only if the row's
  `timestamp_start` could be found and parsed; `None` otherwise.
- `source` — free text, but in practice always `"cli"` (from `decorators.log_job`)
  or `"api"` (from `AuditJobMiddleware` in `src/api/main.py`).
- `use_case` — a short slug identifying which workflow ran; for CLI runs this is the
  decorator's `use_case_name` argument (e.g. `"place_symbol"`, `"consistency_check"`);
  for API runs this is the value side of `AUDIT_ROUTE_MAP` (e.g.
  `"title_block_update"`, `"generate_vessel_extract"`, `"cad3d_edit"` — see §3.4).
  Note this is a **label chosen by the caller**, not necessarily the literal
  `use_cases` module name — several API-side labels (`generate_vessel_extract`,
  `sketch_generate`, `autocad_inspect`, `pid_generate`, `cad3d_generate`, etc.) do
  not correspond 1:1 to any file in `src/use_cases/` at all, since those routes
  don't call into `src/use_cases/` (see §5).
  `request_data` / `ai_output` / `result_data` — JSON-encoded (`json.dumps(...,
  default=str)`) blobs, decoded back to Python via `json.loads` on read; any of the
  three can be `NULL`/`None`.
- `status` — one of `"started"` (set at insert time by `log_job_start`), then
  overwritten at `log_job_end` time to `"ok"` or `"error"`. (A row that never
  reaches `log_job_end` — e.g. process killed — stays `"started"` forever; there is
  no timeout/reconciliation job.)
- `error_message` — free text (`str(exc)`), `NULL` on success.
- `user_agent` — `"cli"` for CLI jobs; the HTTP `User-Agent` request header for API
  jobs (empty string if absent).

`get_connection() -> sqlite3.Connection` (`db.py:31-41`): opens a **new connection
every call** (no pooling/singleton), sets `row_factory = sqlite3.Row`, turns on WAL
journal mode (`PRAGMA journal_mode=WAL;` — allows concurrent readers while a writer
holds a short write lock, appropriate for a low-throughput local app), and
**re-runs the full `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`
schema script on every single connection** (idempotent but slightly wasteful — every
job-log write or read pays a schema-verification cost). `timeout=2.0` means a
connection will wait up to 2 seconds for a lock before raising
`sqlite3.OperationalError`. Every function in `jobs.py` opens a connection, does its
work, and closes it in a `finally` — there is no persistent/shared connection
object anywhere in this package.

### 3.2 `jobs.py` — public logging API

All four public functions live in `src/logging/jobs.py` and are individually
wrapped in `try/except Exception` that prints a `WARNING: audit logging failed: ...`
to stderr via `_warn()` (`jobs.py:12-13`) rather than raising — **logging failures
are designed to never crash the caller** (CLI use_case or API route).

- **`log_job_start(use_case: str, source: str, request_data: dict, user_agent: str = "") -> str`**
  (`jobs.py:50-90`): generates `job_id = uuid.uuid4().hex`, computes
  `timestamp_start`, `INSERT`s a row with `status="started"` and
  `request_data=json.dumps(request_data or {}, default=str)`, commits, closes the
  connection, and **returns the `job_id` string** (even if the insert silently
  failed — callers always get a job_id back, which just won't correspond to a real
  row if writing failed).

- **`log_job_end(job_id: str, status: str, result_data: dict | None = None,
  ai_output: dict | None = None, error_message: str | None = None) -> None`**
  (`jobs.py:93-142`): looks up the row's `timestamp_start` to compute
  `duration_seconds`, then `UPDATE`s `timestamp_end`, `duration_seconds`,
  `ai_output`, `result_data`, `status`, `error_message` for that `job_id`. If no row
  is found (e.g. `log_job_start` silently failed earlier), the `UPDATE` simply
  affects 0 rows — no error is raised either way.

- **`list_recent_jobs(limit: int = 50, use_case: str | None = None, status: str |
  None = None) -> list[dict[str, Any]]`** (`jobs.py:145-186`): builds a dynamic
  `WHERE use_case = ? AND status = ?` clause from whichever of `use_case`/`status`
  are non-`None`, always orders `ORDER BY timestamp_start DESC LIMIT ?`, and returns
  a list of dicts via `_parse_job_row` (which JSON-decodes `request_data`,
  `ai_output`, `result_data` back into Python objects). Returns `[]` on any
  exception (including "table doesn't exist yet" — though `get_connection()` always
  creates it).

- **`get_job(job_id: str) -> dict[str, Any] | None`** (`jobs.py:189-207`): single-row
  lookup by exact `job_id`; returns `None` if not found or on any exception.

These four functions are exactly what `src/api/main.py` imports at
`main.py:23` (`from src.logging.jobs import get_job, list_recent_jobs, log_job_end,
log_job_start`) and exposes via `GET /api/jobs` (→ `list_recent_jobs`, query params
`limit` (1–200, default 50), `use_case`, `status`) and `GET /api/jobs/{job_id}` (→
`get_job`, 404 if `None`).

### 3.3 `decorators.py` — `@log_job` CLI decorator

```python
def log_job(use_case_name: str):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            ...
        return wrapper
    return decorator
```

Behavior (`decorators.py:13-62`):
1. Uses a `threading.local()` singleton `_state` with a `logging_active` flag to
   **prevent nested double-logging** — if a `@log_job`-wrapped function calls another
   `@log_job`-wrapped function (or itself) on the same thread, the inner call just
   runs `func(*args, **kwargs)` directly with no additional job row. This matters
   because, e.g., `consistency_check_ai.main()` (`@log_job("consistency_check_ai")`)
   internally reuses functions from `consistency_check.py`, though it doesn't call
   `consistency_check.main()` itself, so this guard is mostly a defensive measure
   rather than something actively exercised today, except in the case of
   `ai_place_symbol.main()` calling into un-decorated helper functions only, so this
   guard is precautionary.
2. On the outer call: sets `_state.logging_active = True`, calls
   `log_job_start(use_case=use_case_name, source="cli", request_data={"argv":
   sys.argv}, user_agent="cli")` to get a `job_id`.
3. Runs the wrapped function. On normal return: `log_job_end(job_id, status="ok",
   result_data={"completed": True})` (note: the **actual return value of the
   wrapped function is never recorded** — `result_data` is always the constant
   `{"completed": True}` for CLI jobs, unlike the API path, which records the real
   response body — see §3.4/§5).
4. On `SystemExit`: if `exc.code` is `None` or `0`, logs `status="ok"`; otherwise
   logs `status="error"` with `error_message=str(exc)`; re-raises either way. This
   is why exit-on-error via `sys.exit(1)` patterns (used throughout `place_symbol.py`,
   `consistency_check.py`, etc.) are correctly captured as failed jobs.
5. On any other `Exception`: logs `status="error"`, `error_message=str(exc)`,
   re-raises.
6. `finally`: resets `_state.logging_active = False`.

**Usage sites** (confirmed by grep for `log_job` across `src/`): every
`use_cases/*.py` `main()` **except** `verify_title_blocks.py` and
`setup_symbol_test_blocks.py` is decorated with `@log_job("<name>")`:
`ai_place_symbol.main` → `"place_symbol"`, `consistency_check.main` →
`"consistency_check"`, `consistency_check_ai.main` → `"consistency_check_ai"`,
`generate_vessel.generate_vessel` → `"generate_vessel"`, `line_list_extract.main` →
`"line_list_extract"`, `sketch_drawing.sketch_drawing` → `"sketch_drawing"`,
`update_title_block.main` → `"title_block_update"`. No file under `src/scratch/`
or `src/api/` imports `decorators.log_job` — the API path uses the middleware
described below instead, not this decorator.

### 3.4 Audit trail wiring in `src/api/main.py`

`src/api/main.py` does **not** use the `@log_job` decorator at all for API traffic;
it implements a separate, middleware-based audit path that writes to the exact same
`jobs` table via the same `log_job_start`/`log_job_end` functions:

- **`AUDIT_ROUTE_MAP`** (`main.py:30-46`) is a `dict[str, str]` mapping exact request
  paths to `use_case` labels for the `jobs` table:
  ```python
  {
      "/api/title-block-update": "title_block_update",
      "/api/line-list-extract": "line_list_extract",
      "/api/place-symbol": "place_symbol",
      "/api/consistency-check": "consistency_check",
      "/api/generate-vessel/extract": "generate_vessel_extract",
      "/api/generate-vessel/confirm": "generate_vessel_confirm",
      "/api/sketch/generate": "sketch_generate",
      "/api/sketch/approve": "sketch_approve",
      "/api/autocad/inspect": "autocad_inspect",
      "/api/autocad/edit": "autocad_edit",
      "/api/pid/generate": "pid_generate",
      "/api/pid/approve": "pid_approve",
      "/api/cad3d/generate": "cad3d_generate",
      "/api/cad3d/edit": "cad3d_edit",
      "/api/cad3d/approve": "cad3d_approve",
  }
  ```
  Only requests whose exact path is a key in this dict are audited; every other
  route (`/health`, `/api/autocad-status`, `/api/download/*`, `/api/jobs*`, static
  file serving) is not logged.

- **`AuditJobMiddleware`** (`main.py:203-274`) is a raw ASGI middleware class (added
  via `app.add_middleware(AuditJobMiddleware)`) that: buffers the full request body
  (accumulating `http.request` messages), looks up `AUDIT_ROUTE_MAP[path]`, decodes
  the body as JSON if `Content-Type` contains `application/json` (else records
  `{"_unsupported": True, ...}`; truncates to `{"_truncated": True, "size_bytes":
  ...}` if over `MAX_AUDIT_BYTES = 100*1024` bytes), calls `log_job_start(use_case=...,
  source="api", request_data=..., user_agent=<User-Agent header>)`, stores the
  returned `job_id` in a `ContextVar` (`CURRENT_AUDIT_JOB_ID`), replays the buffered
  body to the downstream app via a `replay_receive()` closure (since ASGI request
  bodies can only be read once), and on any exception escaping the downstream app
  that wasn't already logged (tracked via a second ContextVar,
  `CURRENT_AUDIT_COMPLETED`), calls `log_job_end(job_id, status="error",
  error_message=str(exc))` before re-raising.

- **`_install_audit_wrappers()`** (`main.py:164-200`) is called once at import time
  (right after `app.add_middleware(...)`). It walks `app.routes`, and for every
  `APIRoute` whose `path` is in `AUDIT_ROUTE_MAP`, it monkey-patches the route's
  `endpoint` with a wrapper (async or sync, matching the original) that calls the
  original endpoint, then calls `_log_wrapped_route_success(result)` on success or
  `_log_wrapped_route_error(exc)` on exception, and reassigns
  `route.dependant.call` and rebuilds `route.app = request_response(route.get_route_handler())`
  so FastAPI's routing machinery picks up the wrapped endpoint. This is how the
  **actual JSON response body** (not just a static `{"completed": True}` like the
  CLI path) ends up in the `jobs.result_data` column for API-originated jobs:
  `_log_wrapped_route_success` (`main.py:131-149`) truncates the payload via
  `_truncate_payload` (same 100KB cap), extracts a curated `ai_output` sub-object via
  `_extract_ai_output` (pulls out `planned_spec`, `ai_explanation`, `extracted` keys
  if present in the response dict — this is why those three keys appear
  specifically in `place_symbol`/`consistency_check`/`generate-vessel` responses),
  determines `status` via `_status_from_result` (`"error"` if the response dict has
  `ok: False`, else `"ok"`), and calls `log_job_end(job_id, status=..., result_data=...,
  ai_output=..., error_message=payload.get("detail") if dict else None)`, then sets
  `CURRENT_AUDIT_COMPLETED.set(True)` so the middleware's own exception handler
  doesn't double-log.

- **Net effect**: every POST to one of the 15 paths in `AUDIT_ROUTE_MAP` produces
  exactly one row in `jobs.db`'s `jobs` table with `source="api"`, request body as
  `request_data`, and (assuming the endpoint returns rather than raises) the real
  response body as `result_data` plus any `planned_spec`/`ai_explanation`/`extracted`
  pulled into `ai_output`. CLI runs of `use_cases/*.py` produce rows with
  `source="cli"`, `request_data={"argv": sys.argv}`, and a synthetic
  `result_data={"completed": True}` regardless of what the function actually
  returned. Both paths are visible identically through `GET /api/jobs` and `GET
  /api/jobs/{job_id}`.

---

## 4. `src/scratch/` — summary table

| File | One-line purpose | Used by production code? |
|---|---|---|
| `demo_shapes.py` | Draws a circle, line, rectangle, and text via the higher-level `src.autocad_client.safe_connect()` wrapper, as a demo of that reusable client. | N |
| `draw_circle.py` | Earliest COM smoke test: connects via `comtypes` (not `win32com`, unlike the rest of the codebase) and draws one circle. | N |
| `draw_safe.py` | Slightly hardened version of `draw_circle.py` with a `connect_to_autocad()` helper that prints friendly errors and `sys.exit(1)`s if AutoCAD/drawing isn't available; still uses `comtypes`. | N |
| `draw_shapes.py` | Draws a line, a closed lightweight polyline "rectangle", and text in one script, via `comtypes`; no functions, top-level script only. | N |
| `excel_hello.py` | Smoke test confirming `openpyxl` is installed and can write a workbook (`excel_hello.xlsx` at project root). | N |
| `execute_ai_symbol_batch_full.py` | Stress test: plans and **actually inserts** 12 AI-generated symbols into the live `symbol_test.dwg` via `src.ai.symbol_planner` + `src.use_cases.place_symbol.insert_symbol(dry_run=False)`, verifying each; still useful as a manual regression script. | N |
| `execute_ai_symbol_batch_small.py` | Same as above but only 3 prompts — a "controlled" smaller version meant to run before the full 12-symbol batch. | N |
| `make_mismatch_line_list.py` | Utility that copies the latest generated line-list Excel file and deliberately corrupts two cells (`SERVICE`, `SIZE`) to produce a test fixture for exercising `consistency_check.py`'s mismatch detection; prints the follow-up CLI command to run. Still useful as a manual test-data generator. | N |
| `read_title_block.py` | Read-only Phase 2 smoke test: opens `drawing_001.dwg` and prints its `TITLE_BLOCK_TEST` attributes via `win32com` (predates/parallels `use_cases/verify_title_blocks.py`, which generalizes this to all matching files). | N |
| `test.py` | Minimal one-shot connectivity check (`comtypes.client.GetActiveObject`, print caption + active doc name); no `main()`, just top-level statements. | N |
| `test_ai.py` | Phase 4 smoke test of `src.ai.client.ask_ai()` against a simple valve-placement JSON schema; does not touch AutoCAD. | N |
| `test_ai_provider.py` | Confirms the `AI_PROVIDER` env var is read from `.env` and that `ask_ai()` still works through whichever provider is configured; does not touch AutoCAD. | N |
| `test_ai_symbol_batch.py` | Dry-run-only batch test of 12 prompts through `plan_symbol_placement` + `insert_symbol(dry_run=True)`; requires AutoCAD open (for block-existence validation) but makes no drawing changes. | N |
| `test_ai_symbols.py` | Tests `ask_ai()` directly against the full symbol-placement JSON schema/system prompt (a hand-inlined duplicate of what became `src.ai.symbol_planner`); does not touch AutoCAD. | N |
| `test_consistency_explainer.py` | Feeds two hand-written mismatch dicts into `src.ai.consistency_explainer.explain_consistency_mismatches()` and pretty-prints the result; does not touch AutoCAD. | N |
| `test_ezdxf_hello.py` | Smoke test confirming `ezdxf` is installed/working: writes a minimal DXF (`outputs/scratch/ezdxf_hello.dxf`) with a circle and a line. | N |
| `test_fluids_lookup.py` | Smoke test confirming the `fluids` library's `piping.nearest_pipe()` lookup works for a few nominal pipe sizes (NPS 2/6/8, Sch 40); prints OD/ID/wall thickness in mm. | N |
| `test_symbol_planner.py` | Phase 4 "final" test of the real `src.ai.symbol_planner.plan_symbol_placement()` reusable module (as opposed to the ad-hoc schema in `test_ai_symbols.py`) across 5 prompts; does not touch AutoCAD. | N |
| `test_symbol_verification_fix.py` | Targeted regression test for two specific readback/verification bugs (gate valve handle readback, vessel layer/insertion-point readback) found during the full-batch test; inserts 3 real symbols into AutoCAD. | N |

None of these 19 files are imported by anything under `src/api/`, `src/use_cases/`,
`src/ai/`, or `src/framework/` — confirmed by grepping the whole `src/` tree for
`from src.scratch` and `scratch\.`, which only matches these files' own
module-docstring "how to run me" instructions (`python -m src.scratch.<name>`), not
actual imports.

---

## 5. Cross-cutting observations

- **Two independent, overlapping audit-logging mechanisms write to the same table.**
  CLI runs go through `@log_job` (`src/logging/decorators.py`) with
  `source="cli"` and a synthetic `result_data={"completed": True}` that discards
  the function's actual return value. API runs go through
  `AuditJobMiddleware`/`_install_audit_wrappers()` (`src/api/main.py`) with
  `source="api"` and the real response payload. There is no code sharing between
  the two beyond both ultimately calling `log_job_start`/`log_job_end` from
  `src/logging/jobs.py`. A future maintainer adding a new use_case + route pair must
  remember to (a) decorate the CLI `main()`/entrypoint with `@log_job(...)` **and**
  (b) add the route's path to `AUDIT_ROUTE_MAP` in `main.py` — nothing enforces or
  cross-checks that both happen.

- **Half of the "wired to a route" use_cases are only *partially* wired.**
  `consistency_check.py` is almost fully reused by its route (every helper function
  except `main()`); `consistency_check_ai.py` is reused for exactly one helper
  (`write_ai_outputs`) while its comparison/report/explain orchestration is
  duplicated inline in `src/api/routes/consistency.py`; `line_list_extract.py` and
  `update_title_block.py` are reused via a monkey-patching pattern
  (`_temporary_module_settings`) that temporarily overwrites module-level global
  constants (`DRAWINGS_FOLDER`, `UPDATES`, `DRY_RUN`, etc.) for the duration of one
  HTTP request — this is stated explicitly in code comments as a deliberate
  decision to avoid editing the use_case files, but it means these two modules are
  **not thread-safe / not safe under concurrent requests**: two simultaneous
  `POST /api/line-list-extract` or `POST /api/title-block-update` calls with
  different parameters would race on the same shared module globals (`use_case.DRAWINGS_FOLDER`
  etc.), and one request's `finally`-block restore could clobber values another
  concurrent request is still relying on. Uvicorn's default single-worker,
  single-threaded-per-request-await model likely masks this in practice, but it is
  a latent bug if the app is ever run with multiple workers or a threaded server.

- **Three use_cases modules are fully superseded, not just partially wired:**
  `ai_place_symbol.py`, `generate_vessel.py`, and `sketch_drawing.py` each represent
  an earlier, simpler CLI implementation of a pipeline that the corresponding
  FastAPI route (`place_symbol.py`, `vessel.py`, `sketch.py` respectively) later
  reimplemented directly against the lower-level `src.ai.*`/`src.framework.*`/
  `src.parametric.*` modules, in every case with materially more capability than
  the original use_case function (`vessel.py`'s two-step extract/confirm token flow
  vs. `generate_vessel.py`'s blocking `input()`; `sketch.py`'s
  verify-and-repair-with-chunking orchestration vs. `sketch_drawing.py`'s single-pass
  generate→verify→preview→confirm). These three files are effectively dead code
  from the web app's perspective — still functional and runnable as standalone
  CLIs, but no longer on any maintenance path the API exercises. A future refactor
  could either delete them or explicitly document them as "CLI-only reference
  implementations."

- **Two use_cases modules are pure dev tooling with zero external callers:**
  `setup_symbol_test_blocks.py` (creates the `symbol_test.dwg` fixture's block
  definitions) and `verify_title_blocks.py` (read-only diagnostic printer). Neither
  is decorated with `@log_job`, so even a CLI run of these two produces **no** audit
  trail row — every other use_cases module's CLI entrypoint is logged.

- **List of use_cases NOT reachable from the web API** (i.e., only runnable via
  `python -m src.use_cases.<name>`):
  - `ai_place_symbol.py`
  - `generate_vessel.py`
  - `setup_symbol_test_blocks.py`
  - `sketch_drawing.py`
  - `verify_title_blocks.py`

  **Reachable from the web API** (imported directly by a route in `src/api/routes/`):
  - `consistency_check.py` (via `src/api/routes/consistency.py`)
  - `consistency_check_ai.py` (via `src/api/routes/consistency.py`, `write_ai_outputs` only)
  - `line_list_extract.py` (via `src/api/routes/line_list.py`)
  - `place_symbol.py` (via `src/api/routes/place_symbol.py`)
  - `update_title_block.py` (via `src/api/routes/title_block.py`)

- **`sys.exit()` calls buried inside "library" functions that the API now calls
  directly.** `place_symbol.connect_to_autocad()`, `consistency_check.get_acad()`
  (indirectly, via `extract_pid_lines`), and `line_list_extract.get_acad()` (called
  directly by its route) all call `sys.exit(1)` on failure to reach AutoCAD, rather
  than raising a normal exception. Since these are now called from inside a live
  FastAPI request handler, a `sys.exit(1)` raises `SystemExit`, which the routes
  catch with `except SystemExit as exc: raise HTTPException(503, ...)` — this
  *works* (FastAPI/Starlette will not let an unhandled `SystemExit` actually kill the
  worker process because the route wraps it), but it's fragile: any code path that
  doesn't explicitly catch `SystemExit` (e.g. `line_list_extract`'s route doesn't
  wrap `use_case.get_acad()` in a `try/except SystemExit` — it only wraps it in a
  broad `except Exception as exc`, which does **not** catch `SystemExit` since
  `SystemExit` inherits from `BaseException`, not `Exception`) will let the
  `SystemExit` propagate up through Starlette's exception-handling middleware. In
  practice Starlette/Uvicorn will likely turn this into a 500 rather than killing
  the process, but it is inconsistent with the sibling routes' explicit
  `except SystemExit` handling and worth normalizing to ordinary exceptions.
  (See `src/api/routes/line_list.py:59-65` vs. `src/api/routes/place_symbol.py:29-35`
  and `src/api/routes/consistency.py:60-66` for the inconsistency.)

- **Inconsistent block-matching strategy across modules that do conceptually the
  same thing.** `consistency_check.find_line_blocks` and `place_symbol.get_block_name`
  match on `block_ref.EffectiveName` (correct for dynamic/anonymous blocks), while
  `line_list_extract.find_blocks_by_name`, `update_title_block.find_title_blocks`,
  and `verify_title_blocks.read_one_file` all match on raw `entity.Name`. This is a
  latent correctness gap: if any target DWG's `LINE_BLOCK_TEST`/`TITLE_BLOCK_TEST`
  blocks are ever inserted as dynamic blocks or anonymous block instances,
  `line_list_extract.py`/`update_title_block.py`/`verify_title_blocks.py` would
  silently find zero matches while `consistency_check.py`'s equivalent logic would
  still work.

- **`generate_vessel.py` and `sketch_drawing.py` both independently implement the
  exact same "fallback no-op `log_job` if `src.logging` import fails" pattern**
  (`_identity_log_job`), while every other use_cases module (`ai_place_symbol.py`,
  `consistency_check.py`, `consistency_check_ai.py`, `line_list_extract.py`,
  `update_title_block.py`) imports `log_job` unconditionally and would raise
  `ImportError` at import time if `src/logging` broke. This inconsistency suggests
  the fallback pattern was added later (both files are the two most recently-dated
  "Phase 20"/"Mode 2" additions) but never back-ported to the earlier modules.

- **Hard-coded, developer-machine-specific paths.** `consistency_check.py`,
  `line_list_extract.py`, `update_title_block.py`, and `verify_title_blocks.py` all
  hard-code `DRAWINGS_FOLDER = Path(r"E:\RC-Projects")` (a drive that only exists on
  the original developer's machine) as a module-level default; the API routes that
  wrap `line_list_extract.py`/`update_title_block.py` override this via request
  parameters, but running any of these four modules directly as a CLI on a machine
  without an `E:\RC-Projects` folder will simply fail at the "folder not found"
  check in each `main()`.

- **`src/scratch/` is safe to delete or archive wholesale.** No file in `src/api/`,
  `src/use_cases/`, `src/ai/`, `src/framework/`, or `src/logging/` imports anything
  from `src/scratch/`. Three scripts remain genuinely useful as manual test
  tooling — `make_mismatch_line_list.py` (generates a corrupt-data fixture for
  `consistency_check`), `execute_ai_symbol_batch_small.py`/`_full.py` (regression
  tests for `place_symbol.insert_symbol`) — the rest (library smoke tests for
  `openpyxl`/`ezdxf`/`fluids`/AI client/AI provider, and the very first
  `comtypes`-based COM connectivity experiments in `draw_circle.py`, `draw_safe.py`,
  `draw_shapes.py`, `test.py`) are historical artifacts from early phases and have
  been superseded by more robust equivalents elsewhere (e.g. `win32com`-based COM
  helpers with `com_retry` logic in the `use_cases/` modules vs. these raw
  `comtypes` one-shots).

- **No TODO/FIXME comments were found in any file across `src/use_cases/`,
  `src/logging/`, or `src/scratch/`** — the code is generally complete for its
  intended (small, single-developer) scope; the "inconsistencies" above are latent
  design gaps rather than flagged unfinished work.

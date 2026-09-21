# Cross-Cutting Known Issues & Recommendations

This file synthesizes the "cross-cutting observations" sections from every subsystem doc in this
folder, plus environment-level findings from rebuilding and testing the project, into one ranked
list. Each item links back to the subsystem doc with full detail — this file is the summary, not
the source of truth. Nothing here is a hypothesis; every item was either read directly in the
source or reproduced by executing the code.

Ranked roughly by "how much this could actually hurt someone using the app," most severe first.

## Tier 1 — Can corrupt or lose real work

1. **No automatic backup before live AutoCAD mutation, in the most-used execution paths.**
   `execute_commands`/`execute_command_sequence` and `execute_edit_plan` (the functions behind
   `/api/sketch/approve`, `/api/pid/approve`, `/api/autocad/edit`) never call `src/backup.py`'s
   `backup_file`. Backup is currently wired into exactly one workflow
   (`update_title_block.py`). Combined with issue 2 below, a bad AI-generated command sequence
   executed with the default `save=True` can permanently alter a live `.dwg` with no built-in
   rollback. → [04_command_and_autocad_framework.md](04_command_and_autocad_framework.md) §9.3.
   **Recommendation:** call `backup_file()` at the top of `execute_command_sequence`/
   `execute_edit_plan` before the first mutating COM call, gated by the same `save` flag.

2. **Partial/best-effort execution is the default, not opt-in.** Both executors default
   `continue_on_error=True`: one bad command in a batch still lets every other command execute
   and save, reporting `ok: False` with a list of per-command errors — but the drawing is already
   changed. A caller that only checks a top-level `ok` boolean (rather than the `errors` array)
   can't tell "fully succeeded" from "half-applied." → [04](04_command_and_autocad_framework.md) §9.4.
   **Recommendation:** at minimum, surface "N of M commands failed" prominently in every UI that
   calls these endpoints (`sketch.html`, `jobs.html`), not just in the raw JSON.

3. **Two independent, already-drifted implementations of CAD3D port geometry.** The OOP
   `components/*.py` `ports()` methods and `routing.py`'s `component_ports()` dispatch chain
   compute the same thing for the same component types but have diverged — `routing.py`'s version
   has strictly more port aliases (`inlet`/`outlet`/`drain`/`vent` etc.) for 6 of 10 component
   types. A scene built via the OOP component classes directly (as in `component_examples.py`)
   exposes fewer connectable ports than the same component type authored as raw AI-planner JSON.
   → [05_cad3d_framework.md](05_cad3d_framework.md) §9 item 1.
   **Recommendation:** make `routing.py` call into `components/*.py`'s `ports()` (or vice versa) so
   there is one source of truth; add a test that asserts port-name parity between the two paths.

## Tier 2 — Silent inconsistencies that will eventually cause a confusing bug report

4. **Duplicate, same-named exception classes that don't actually match.** `src/autocad_client.py`
   defines its own `AutoCADNotRunningError`; the class every real framework module actually raises
   and catches is a *different* class of the same name defined in
   `src/parametric/vessel/dwg_export.py`. `except autocad_client.AutoCADNotRunningError` anywhere
   would silently fail to catch the real exception. → [04](04_command_and_autocad_framework.md) §9.1.
   **Recommendation:** delete or clearly deprecate `src/autocad_client.py` (see Tier 3 item 12), or
   make it import/re-export the `dwg_export` exception instead of redefining it.

5. **`src/api/chat_routing.py` (Python) and the inline JS router in `sketch.html` are two
   independent implementations of the same decision tree, and they are not fully equivalent.**
   `chat_routing.py` is never imported by any FastAPI route — it exists purely as a spec that a
   test checks the JS against, and that test **skips silently (not fails) if Node.js isn't
   installed**, so drift between the two can go undetected indefinitely in a Node-less environment.
   Worse, the two are already *intentionally* different for CAD3D-edit routing: the JS gates on
   "is there a CAD3D scene in the current browser session" (`hasCAD3DContext()`), the Python
   version has no such gate. → [02_api_layer.md](02_api_layer.md) §7 items 1-2.
   **Recommendation:** confirm `node` is available wherever CI/tests actually run (or make the test
   fail, not skip, when Node is missing); consider making `chat_routing.py` the thing the frontend
   calls (via a small `/api/chat/route` endpoint) instead of maintaining two implementations.

6. **Two parallel, non-interoperating P&ID pipelines exist; only one is live.**
   `scene_schema.py`/`scene_renderer.py` (flat scene) look like production code but are not called
   by `/api/pid/generate` or any route — only `component_schema.py`/`component_builder.py`/
   `components/` is. → [06_pid_framework.md](06_pid_framework.md) §9 item 1.
   **Recommendation:** confirm with whoever owns this repo whether the flat pipeline can be
   deleted; if it must stay (e.g. for a future non-AI API), document that explicitly at the top of
   `scene_schema.py`.

7. **Inconsistent AI-provider request cache semantics across the four generate/approve workflows.**
   Sketch and vessel tokens expire after 10 minutes and self-invalidate on successful approve; P&ID
   and CAD3D tokens (`_PID_CACHE`, `_CAD3D_CACHE`) never expire and are **never invalidated even on
   success** — the same P&ID or CAD3D token can be replayed into AutoCAD indefinitely while the
   server process is alive. → [02](02_api_layer.md) §7 item 5.
   **Recommendation:** decide on one policy (TTL + pop-on-success is the safer default) and apply
   it uniformly; at minimum, document the difference for anyone building a client against these
   APIs.

8. **HTTP status codes for the same exception type are inconsistent, even within one endpoint.**
   In `sketch.py`'s `/generate`, a `ValueError` maps to 400 on the verified path but 502 on the
   direct (`run_verifier=False`) path. Separately, `vessel.py`'s `/generate-vessel/confirm` never
   raises `HTTPException` for domain failures at all — it always returns HTTP 200 with
   `{"ok": false, "error_type": ...}`, the opposite convention from every other route.
   → [02](02_api_layer.md) §7 items 6-7.
   **Recommendation:** pick one convention (prefer real HTTP status codes) and normalize
   `vessel.py`'s confirm route to match the rest of the app; document the exception either way.

9. **Not thread-safe under concurrent requests.** `line_list.py` and `title_block.py` routes
   monkey-patch module-level globals on their corresponding `use_cases` modules
   (`_temporary_module_settings`) for the duration of one request, then restore them — two
   overlapping requests with different parameters will race on the same shared state. Currently
   masked by Uvicorn's default single-worker mode. → [08_use_cases_logging_scratch.md](08) §5.
   **Recommendation:** either accept the single-worker constraint explicitly in the README/ops
   notes, or refactor those two use_cases to accept parameters instead of reading module globals.

10. **`SystemExit`-based error signaling — narrower than originally documented here; corrected
    2026-09-20.** The original claim that `src/api/routes/line_list.py` was missing a
    `SystemExit` catch it needed was **wrong** and has been verified and corrected: `sys.exit(1)`
    in `use_cases/line_list_extract.py` lives only inside that module's CLI `main()`
    (`line_list_extract.py:114-126`); the plain `get_acad()` helper the route actually calls
    (`line_list_extract.py:39-40`) never raises `SystemExit` at all, and the route's existing
    `except Exception` (`routes/line_list.py:61`) already handles it correctly. This specific
    example is retracted. The broader pattern may still exist elsewhere (`place_symbol.py`'s
    `connect_to_autocad()`, `consistency_check.py`'s `get_acad()` path were flagged with the same
    concern originally but were not independently re-verified when this correction was made —
    treat those two as unconfirmed rather than assuming they're right just because this one
    example turned out wrong).
    → [08](08_use_cases_logging_scratch.md) §5.

## Tier 3 — Dead code / orphaned paths worth knowing about before you go looking for "the real implementation"

11. **`src/autocad_client.py` is legacy/orphaned.** Every real COM connection in the framework
    layer goes through `src/parametric/vessel/dwg_export.py`'s private helpers instead, despite
    the misleading name. → [04](04_command_and_autocad_framework.md) §9.2.
12. **5 of 10 `src/use_cases/*.py` modules are unreachable from the web API**: `ai_place_symbol.py`,
    `generate_vessel.py`, `sketch_drawing.py`, `setup_symbol_test_blocks.py`,
    `verify_title_blocks.py`. The routes that "should" use them (`place_symbol.py`, `vessel.py`,
    `sketch.py`) were rewritten to call `src.ai`/`src.framework`/`src.parametric` directly with
    more capability than the original CLI version. → [08](08_use_cases_logging_scratch.md) §2, §5.
13. **`src/scratch/` (19 files) has zero production callers** — confirmed by grep across the whole
    `src/` tree. Safe to ignore when tracing real behavior; still useful as historical dev notes.
    → [08](08_use_cases_logging_scratch.md) §4.
14. **Several fields/functions are computed but never consumed**: `default_projection_mm()` in
    `parameters.py`; `extends_negative_x`, `pipe_id_mm`, and nozzle `wall_thickness_mm` in
    `geometry.py`; `COMMAND_SCHEMA`'s `common_optional` definition in `schema.py`; `JobResultResponse`
    in `schemas.py`. → [07](07_parametric_vessel.md) §9.3, [04](04_command_and_autocad_framework.md)
    §9.9, [02](02_api_layer.md) §7 item 10.

## Tier 4 — Test coverage gaps

15. **Two `src/ai/` modules have no meaningful test coverage**: `symbol_planner.py` and
    `consistency_explainer.py`. **Correction, 2026-09-20:** `vessel_planner.py` was originally
    included in this list too — that was wrong. `tests/parametric/test_vessel_planner.py` directly
    imports and tests `src.ai.vessel_planner` (confirmed by reading its imports), so the largest,
    most complex file in the AI layer (619 lines, including the hand-written duplicate-nozzle
    repair logic) does have dedicated test coverage, contrary to what was originally stated here.
    The remaining two modules also skip the post-AI-call schema-validation step every other AI
    module performs, and silently use `client.py`'s default `max_retries=1` instead of the
    `max_retries=2` every other generator uses. → [03_ai_layer.md](03_ai_layer.md) §7.
    **Recommendation:** if `vessel_planner.py`'s repair logic is ever touched, write tests for it
    first — it's the least-covered, most-complex code in the layer.
16. **`client.py`'s actual retry loop, `AIConfigError` paths, and `_build_system_prompt` are never
    tested directly** — only exercised indirectly through other modules' happy-path mocks of
    `ask_ai` itself. → [03](03_ai_layer.md) §2.
17. **No test covers `_PID_CACHE`/`_CAD3D_CACHE`'s unbounded growth** (no TTL, no eviction, no
    size cap) — low real-world impact for a local single-user tool, but worth knowing if this is
    ever deployed as a shared/long-running server. → [05](05_cad3d_framework.md) §9.

## Tier 5 — Documentation drift (parametric vessel)

The vessel agent actually *ran* the code to check its own reference docs (`docs/vessel_*.md`)
against current behavior rather than trusting either source. Findings:

18. `docs/vessel_known_issues.md` describes a "wrong scale" bug (drawings picking 1:50 instead of
    1:20) as current — **it is already fixed**; all 5 example vessels now correctly select 1:20.
    → [07](07_parametric_vessel.md) §9.1.
19. **Dimensioning is front-view-only** — side and top views have no dimension lines at all. This
    is a real functional gap not mentioned in any of the four vessel docs. → [07](07) §9.2.
20. NPS (nozzle size) support is defined redundantly in **three places** with no single source of
    truth: `ANSI_B16_5_150_RF_FLANGE_OD_MM` in `geometry.py`, the enum in
    `src/ai/vessel_planner.py`'s JSON schema, and whatever `fluids`'s own schedule-40 table
    supports. → [07](07) §9.8.

## Tier 6 — Cosmetic / low-risk cleanup candidates

21. `console.log` debugging trace left in production `sketch.html` (fires on every chat message).
    → [02](02_api_layer.md) §7 item 9.
22. `jobs.html`'s use-case filter dropdown is missing 11 of the ~15 audited use-case values (only
    the original 4 pre-chat-UI workflows are selectable). → [02](02_api_layer.md) §7 item 3.
23. `index.html` landing page has no card/link for the P&ID or CAD3D workflows, and its body copy
    still says "Phase 7 thin web wrapper" (stale). → [02](02_api_layer.md) §7 item 4.
24. Audit log's `error_message` column only populates from a `detail` key — routes that return
    ad-hoc `message`/`error_type` shapes (chiefly `vessel.py`) log `status="error"` with a blank
    `error_message`, even though `jobs.html` renders that column as "the error." → [02](02) §7 item 8.
25. Several near-identical helper functions are copy-pasted across 2-4 files rather than shared:
    `_format_path`/`_format_error` (4 schema modules), orchestration scaffolding (`command_orchestrator.py`
    vs `chunked_command_orchestrator.py`), `_ALLOWED_UPDATE_FIELDS` (`edit_schema.py` vs
    `scene_editor.py`), 3D point/vector normalization helpers (3 different modules in `cad3d/`).
    None of these are currently bugs, but each is a place where a fix applied to one copy and not
    the other would silently create a real bug. See each subsystem doc's own cross-cutting section
    for the full list.

## Environment / operational issues (found while setting this project up, not in the code itself)

26. **Both pre-existing `venv/` and `venv-broken-20260902-165925/` folders were non-functional**
    (stale interpreter path; incompatible Python 3.14 build) and had to be rebuilt from scratch with
    Python 3.11.9 before anything would run. → [01_environment_and_setup.md](01_environment_and_setup.md) §1-2.
27. **`setup-and-start.ps1` and `start-autocad-ai.bat` both hardcode `C:\RC-Projects\autocad-ai\autocad-ai`**,
    but the project is checked out at `F:\RC-Projects\autocad-ai\autocad-ai` on this machine — neither
    script will find the project until that path is edited or the project is moved to `C:\`.
    → [01](01_environment_and_setup.md) §1.
28. **The live-AI-test opt-in env var is spelled two different ways**: most test files check
    `RUN_LIVE_AI_TESTS`, but `tests/parametric/test_vessel_planner_live.py` checks `RUN_LIVE_AI`
    (no `_TESTS` suffix) — set both if you want every live test to run. → [01](01) §3.
29. **A live, real DeepSeek API key is present in the local `.env`** — rotate it before ever
    sharing this project folder, zipping it, or pushing it anywhere (it's gitignored, so it was
    never committed, but it exists in plaintext on disk right now). → [01](01) §4.
30. **No project-specific request timeout in `src/ai/client.py`** — no `timeout=` is passed to
    `OpenAI(...)` or `.create(...)`, so a slow DeepSeek call relies entirely on the `openai`
    SDK's/`httpx`'s own default timeout rather than a value chosen for this app. **Correction,
    2026-09-20:** the original wording here ("could block... indefinitely, with no circuit
    breaker") overstated this — the SDK's default timeout still applies and will eventually fire,
    it's just not a value this project chose deliberately. Worth setting an explicit,
    app-appropriate timeout regardless, especially since an orchestration chain can make several
    sequential LLM calls (generate, verify, repair×N), each of which would separately wait out
    the full default before the chain gives up — but "no timeout at all" was not accurate.
    → [03](03_ai_layer.md) §7.

## What's *not* a problem (documented so it isn't rediscovered as a bug)

- Zoom/regen failures never make command/edit execution report `ok: False` — this is a deliberate,
  tested design choice (cosmetic viewport ops shouldn't fail an otherwise-good edit), not a gap.
- 3D coordinates being silently truncated to 2D in the P&ID framework's `normalize_point()` is
  intentional (P&ID is inherently flat) — just undocumented at the call site.
- The vessel subsystem's symbol sizing is deliberately non-physical/oversized "for demo videos and
  client presentation screenshots" per its own docstring — every generated vessel's `assumptions`
  list already discloses this.

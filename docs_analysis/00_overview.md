# AutoCAD AI Automation — Project Overview

**Read this file first.** It orients a new agent (human or AI) in the codebase and points to the
detailed per-subsystem references in this folder. This analysis was produced on **2026-09-19** by
reading every source file in the project (not sampling), running the project's own test suite, and
rebuilding its Python environment from scratch. Everything stated as fact below was verified by
either reading the code directly or executing it — see [01_environment_and_setup.md](01_environment_and_setup.md)
for exactly what was run.

## What this project is

A local, Windows-only FastAPI application that lets a person describe AutoCAD drawings and edits in
plain English through a chat-style web UI, and have them actually appear in a running AutoCAD
session. It covers four drawing domains:

1. **Generic 2D sketches** ("Mode 2") — arbitrary shapes/annotations from a free-text prompt.
2. **P&ID diagrams** — Piping & Instrumentation Diagrams using a catalog of deterministic
   engineering symbols (vessels, pumps, valves, instruments).
3. **3D piping/equipment scenes** ("CAD3D") — tanks, pumps, pipe runs, supports laid out in 3D
   space as AutoCAD solids/placeholders.
4. **Parametric pressure vessels** — fully deterministic (no AI) engineering-grade multi-view
   vessel drawings from a pressure-vessel parameter set.

Plus supporting workflows that predate/sit alongside the chat UI: title-block batch updates, P&ID
line-list extraction to Excel, P&ID-vs-Excel consistency checking, and single-symbol placement.

## The one idea that explains almost everything

**AI never touches AutoCAD.** Every AI-assisted feature follows the same shape:

```
natural-language prompt
   -> src/ai/*            (LLM call, JSON-schema-constrained, DeepSeek via an OpenAI-compatible API)
   -> src/framework/*      (jsonschema Draft7Validator — hard validation gate)
   -> src/framework/*      (deterministic builder/executor — the ONLY code that calls win32com.client)
   -> live AutoCAD document (via COM)
```

The AI layer (`src/ai/`) is not allowed to call AutoCAD, execute anything, or render previews — every
module's docstring says so explicitly, and it's true in practice (verified by reading every file).
The framework layer (`src/framework/`) is not allowed to call an LLM. This split is deliberate and
consistent across all four drawing domains, though each domain re-implements the split slightly
differently (see the per-subsystem docs for the specific mechanics and where the pattern is bent).

Most write workflows are also split into two HTTP calls — **generate** (AI plans, nothing touches
AutoCAD, result cached server-side under a token) then **approve/confirm** (the cached, already-
validated plan is executed into the live drawing). This lets the chat UI show a preview/summary
before anything destructive happens.

## Architecture map

| Layer | Path | AI? | Touches AutoCAD? | Detailed doc |
|---|---|---|---|---|
| HTTP API + chat UI | `src/api/` | no (routes call into `ai`) | some routes (edit/inspect/approve) | [02_api_layer.md](02_api_layer.md) |
| AI planning | `src/ai/` | **yes — only place `openai`/DeepSeek is called** | never | [03_ai_layer.md](03_ai_layer.md) |
| Generic command schema/exec | `src/framework/commands/` | no | yes (`executor.py`, `edit_executor.py`) | [04_command_and_autocad_framework.md](04_command_and_autocad_framework.md) |
| Read-only drawing inspection | `src/framework/autocad/` | no | yes (read-only) | [04_command_and_autocad_framework.md](04_command_and_autocad_framework.md) |
| 3D scene components/executor | `src/framework/cad3d/` | no | yes (`autocad_3d_executor.py`) | [05_cad3d_framework.md](05_cad3d_framework.md) |
| 2D P&ID symbols/components | `src/framework/pid/` | no | no (produces command JSON only; execution is via `src/framework/commands/executor.py`) | [06_pid_framework.md](06_pid_framework.md) |
| Parametric vessel geometry | `src/parametric/vessel/` | no (pure engineering math + `ezdxf`) | only `dwg_export.py` (DXF→DWG conversion) | [07_parametric_vessel.md](07_parametric_vessel.md) |
| CLI-era workflow scripts | `src/use_cases/` | some | some | [08_use_cases_logging_scratch.md](08_use_cases_logging_scratch.md) |
| Audit trail (SQLite) | `src/logging/` | no | no | [08_use_cases_logging_scratch.md](08_use_cases_logging_scratch.md) |
| Dev scratch scripts | `src/scratch/` | some | some (not production code) | [08_use_cases_logging_scratch.md](08_use_cases_logging_scratch.md) |

`src/autocad_client.py` and `src/backup.py` sit at the repo root, outside `src/framework/` — see
[04_command_and_autocad_framework.md](04_command_and_autocad_framework.md) §6-7; the first is largely
dead code (the real COM connection helper everything actually depends on lives in
`src/parametric/vessel/dwg_export.py`), the second is a manual backup utility wired into exactly one
use case.

## The four drawing domains, one level deeper

- **Sketch (Mode 2)** — `src/ai/command_generator.py` (+ verifier/repairer/orchestrator, and a
  "chunked" variant for large prompts) produces a flat command list (`LAYER`, `LINE`, `CIRCLE`,
  `ARC`, `ELLIPSE`, `POLYLINE`, `TEXT`, `INSERT`, `DIM_LINEAR`). No deterministic fallback exists here
  — if the AI/verifier/repair chain fails, the request just fails. Routes: `/api/sketch/generate`,
  `/api/sketch/approve`.
- **P&ID** — `src/ai/pid_component_planner.py` produces a "component scene" (11 component types:
  vessels, pumps, valves, instruments, piping, etc.), validated and expanded to the same flat
  command-list shape by `src/framework/pid/`. If the AI fails, a deterministic **template fallback**
  (`horizontal_separator`, `vertical_vessel`, `pump_tank`) keeps the endpoint usable. Routes:
  `/api/pid/generate`, `/api/pid/approve`. Note: there is a second, older "flat scene" P&ID pipeline
  (`scene_schema.py`/`scene_renderer.py`) that still exists in the codebase but is **not wired to any
  route** — see [06_pid_framework.md](06_pid_framework.md).
- **CAD3D** — `src/ai/cad3d_scene_planner.py` produces a 3D "scene" (14 component types) executed via
  `win32com.client` `AddCylinder`/`AddBox`/`AddLine`/`AddText` calls (no meshes/solids/extrusions).
  Scenes persist to `outputs/cad3d/scenes/*.json` via a `CAD3DSceneStore` and can be edited
  incrementally (`src/ai/cad3d_edit_planner.py` + `src/framework/cad3d/scene_editor.py`), with its own
  deterministic regex-based fallback if the AI edit plan fails to apply. Routes:
  `/api/cad3d/generate`, `/api/cad3d/state*`, `/api/cad3d/edit`, `/api/cad3d/approve`.
- **Parametric vessel** — no AI in the geometry/drawing path at all. `src/ai/vessel_planner.py` only
  turns a prompt into the input parameter JSON; `src/parametric/vessel/` computes exact geometry
  (ASME/ANSI-style formulas, `fluids` schedule-40 lookups) and renders a 3-view engineering drawing
  with title block and BOM via `ezdxf`, then optionally converts to `.dwg` through a live AutoCAD COM
  session. Routes: `/api/generate-vessel/extract`, `/api/generate-vessel/confirm`.

## Supporting workflows (pre-chat-UI, partially superseded)

`src/use_cases/` holds the original CLI-era functions. Only **5 of 10** are actually reachable from
the web API today (`consistency_check`, `consistency_check_ai`, `line_list_extract`, `place_symbol`,
`update_title_block` — imported by `src/api/routes/{consistency,line_list,place_symbol,title_block}.py`).
The other 5 (`ai_place_symbol`, `generate_vessel`, `sketch_drawing`, `setup_symbol_test_blocks`,
`verify_title_blocks`) are orphaned from the API's point of view — the `vessel.py` and `sketch.py`
routes were rewritten to call `src.ai`/`src.framework`/`src.parametric` directly instead. Full detail
in [08_use_cases_logging_scratch.md](08_use_cases_logging_scratch.md).

## Audit trail

Every important route logs a start/end row to a local SQLite database (`jobs.db` at the repo root)
via `src/logging/jobs.py`, wired in through `AuditJobMiddleware` + endpoint-wrapping in
`src/api/main.py`. `jobs.html` and `GET /api/jobs`/`GET /api/jobs/{id}` expose this history. Full
schema and mechanism in [08_use_cases_logging_scratch.md](08_use_cases_logging_scratch.md) §3.

## Environment status (verified 2026-09-19)

The project's Python virtual environment was **broken** at the start of this analysis (stale
interpreter path, and a second abandoned rebuild attempt using an incompatible Python version) and
was rebuilt from scratch with Python 3.11.9. After rebuilding: **the app imports cleanly and the full
test suite passes — 892 passed, 10 skipped (all intentionally, gated behind `RUN_LIVE_AI_TESTS`/
`RUN_LIVE_AI` env vars that make real DeepSeek API calls), 0 failed.** AutoCAD-COM-dependent behavior
(anything that actually opens/edits a drawing) could not be exercised end-to-end in this environment
since no licensed AutoCAD install is available here — those code paths are documented from source +
their mocked unit tests only. Full detail in [01_environment_and_setup.md](01_environment_and_setup.md).

## How to use this folder

| File | Contents |
|---|---|
| [00_overview.md](00_overview.md) | This file |
| [01_environment_and_setup.md](01_environment_and_setup.md) | Verified setup steps, what was broken and how it was fixed, test results |
| [02_api_layer.md](02_api_layer.md) | FastAPI app, every route, every static HTML page, the audit middleware |
| [03_ai_layer.md](03_ai_layer.md) | Every `src/ai/*` module — prompts, schemas, retry/repair logic |
| [04_command_and_autocad_framework.md](04_command_and_autocad_framework.md) | Generic command schema/executor, AutoCAD inspector, `autocad_client.py`, `backup.py` |
| [05_cad3d_framework.md](05_cad3d_framework.md) | 3D scene schema, components, editor, store, COM executor |
| [06_pid_framework.md](06_pid_framework.md) | 2D P&ID symbols, components, builder, templates |
| [07_parametric_vessel.md](07_parametric_vessel.md) | Vessel parameters, geometry formulas, multi-view drawing generation |
| [08_use_cases_logging_scratch.md](08_use_cases_logging_scratch.md) | CLI-era use cases, SQLite audit trail, scratch scripts |
| [09_known_issues_and_recommendations.md](09_known_issues_and_recommendations.md) | Cross-cutting bugs/inconsistencies/risks found across every subsystem, ranked |

Each subsystem doc was produced by fully reading every source file and every corresponding test file
in that subsystem (file lists are given at the top of each doc), and cross-references the routes/AI
modules/use_cases that call into it. Together they total roughly 6,000 lines of reference material —
treat them as a substitute for re-reading the source, not a summary of it.

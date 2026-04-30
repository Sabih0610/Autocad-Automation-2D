# AutoCAD AI Automation

Local FastAPI application for AI-assisted AutoCAD drafting workflows.

The project combines:

- deterministic CAD/math logic for repeatable geometry
- schema-validated AI planners for natural-language intent
- AutoCAD COM execution through `pywin32`
- a dark chat-style web UI for new drawings, P&IDs, and live edits

AutoCAD must be installed locally and running for any workflow that executes
into an active drawing.

## Current Capabilities

- Batch title block update and verification
- Line list extraction and consistency checks
- AI-assisted symbol placement
- Parametric vessel drawing generation
- Mode 2 sketch generation from natural-language prompts
- Multi-agent command generation, verification, repair, and chunked generation
- Read-only active drawing inspection through AutoCAD COM
- Live edit planning and execution against the active AutoCAD drawing
- Deterministic P&ID symbols, scene rendering, component architecture, templates,
  and AI component planning with template fallback
- Chat routing between generic sketch generation, P&ID generation, and live edit

## Requirements

- Windows 10 or 11
- Full AutoCAD installed and licensed
- Python 3.11+
- AutoCAD open with an active drawing for execution/edit/inspection routes
- Optional: Node.js, only for the static JavaScript routing test

AutoCAD LT is not supported because it does not expose the COM API required by
this project.

## Setup

```powershell
cd E:\RC-Projects\autocad-ai

python -m venv venv
.\venv\Scripts\activate

python -m pip install --upgrade pip
pip install -r requirements.txt
```

Create a local `.env` file for AI-backed workflows:

```text
AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=your_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

The AI client uses OpenAI-compatible chat completions. The DeepSeek settings
above are the currently supported provider path in this repo.

## Run The Web App

Start the local server from the project root:

```powershell
python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

Useful URLs:

- Home: `http://127.0.0.1:8000/`
- Chat Mode 2: `http://127.0.0.1:8000/sketch.html`
- Jobs/audit history: `http://127.0.0.1:8000/jobs.html`
- Swagger API docs: `http://127.0.0.1:8000/docs`

## Chat Workflows

The chat UI routes messages deterministically before calling the backend:

- new generic drawings -> `POST /api/sketch/generate`, then `/api/sketch/approve`
- new P&ID drawings -> `POST /api/pid/generate`, then `/api/pid/approve`
- edits to the current AutoCAD drawing -> `POST /api/autocad/edit`

Examples:

```text
Draw a rectangle 1000mm wide and 500mm high with a circle in the center.
Create a detailed P&ID for a small process unit with vessels, pumps, valves, and instruments.
Delete the title text.
```

Generation endpoints do not modify AutoCAD. Approval/build endpoints execute the
cached command sequence into AutoCAD.

## Main API Endpoints

Sketch / Mode 2:

- `POST /api/sketch/generate`
- `POST /api/sketch/approve`

P&ID component pipeline:

- `POST /api/pid/generate`
- `POST /api/pid/approve`

Live AutoCAD inspection and edit:

- `GET /api/autocad/inspect`
- `POST /api/autocad/edit`

Existing workflow routes:

- `POST /api/title-block-update`
- `POST /api/line-list-extract`
- `POST /api/place-symbol`
- `POST /api/consistency-check`
- `POST /api/generate-vessel/extract`
- `POST /api/generate-vessel/confirm`

Downloads are served through:

- `GET /api/download/{filename:path}`

## P&ID Component Pipeline

The P&ID path uses a safer hybrid approach:

```text
user prompt
-> AI component scene planner
-> deterministic schema validation
-> deterministic component builder/renderer
-> command sequence
-> AutoCAD approval execution
```

If the AI planner fails or returns invalid JSON, the resilient planner chooses a
deterministic component template such as:

- `horizontal_separator`
- `vertical_vessel`
- `pump_tank`

This keeps `/api/pid/generate` usable even when the AI response is malformed.

## Project Layout

```text
autocad-ai/
  src/
    ai/                         AI clients, planners, command repair/orchestration
    api/                        FastAPI app, schemas, routes, static pages
    framework/
      autocad/                  read-only active drawing inspector
      commands/                 command schema, executor, verifier schemas, edit executor
      pid/                      P&ID symbols, scenes, components, templates
    logging/                    SQLite job audit trail
    parametric/vessel/          vessel geometry and DXF/DWG rendering
    use_cases/                  CLI/workflow wrappers
  tests/
    api/                        FastAPI and chat routing tests
    framework/                  schemas, AI orchestration, executor, P&ID tests
    parametric/                 vessel geometry/rendering tests
  docs/                         vessel notes and reference docs
  outputs/                      generated reports/previews/drawings, gitignored
```

## Testing

Use the venv Python from the project root:

```powershell
.\venv\Scripts\python.exe -m pytest tests/api/test_chat_routing.py -q
.\venv\Scripts\python.exe -m pytest tests/api/test_pid_routes.py -q
.\venv\Scripts\python.exe -m pytest tests/api/test_sketch_routes.py -q
.\venv\Scripts\python.exe -m pytest tests/framework/test_command_executor.py -q
.\venv\Scripts\python.exe -m pytest tests/framework/test_pid_component_planner.py -q
.\venv\Scripts\python.exe -m pytest tests/framework/test_pid_component_templates.py -q
.\venv\Scripts\python.exe -m pytest tests/parametric/ -q
.\venv\Scripts\python.exe -c "from src.api.main import app; print('api import OK')"
```

Live AI tests are skipped by default. Enable them explicitly:

```powershell
$env:RUN_LIVE_AI_TESTS='1'
.\venv\Scripts\python.exe -m pytest tests/framework/test_pid_component_planner.py -q
```

Live AutoCAD behavior should be tested manually with AutoCAD open and an active
drawing.

## Generated Files

The app can create:

- SQLite audit database: `jobs.db`
- logs: `*.log`
- reports, previews, DXFs, and rendered vessel outputs under `outputs/`
- AutoCAD temporary sidecar files such as `*.dwl` and `*.dwl2`
- backups under `backups/` and `src/backups/`

These are intentionally gitignored.

## Architectural Notes

- AutoCAD COM calls use `pywin32`. Routes that touch AutoCAD initialize COM in
  the route thread with `pythoncom.CoInitialize()`.
- Command execution is deterministic and schema-driven. AI modules generate or
  repair JSON plans but do not call AutoCAD directly.
- P&ID generation prefers component scenes over raw low-level geometry so common
  engineering symbols render consistently.
- The audit middleware records important API workflow requests and responses in
  SQLite without blocking the job if logging fails.

## License / Disclaimer

Internal project. Built and tested with AutoCAD Education/Commercial style COM
automation. Drawings produced by an Education license may carry an Autodesk
educational watermark and should not be used as production deliverables.

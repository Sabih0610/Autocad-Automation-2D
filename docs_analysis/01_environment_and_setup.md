# Environment & Setup — Verified State (2026-09-19)

This file documents the *actual, verified* steps to get this project running, what was broken when this analysis started, and what fixing it involved. Everything here was executed for real on the machine at `F:\RC-Projects\autocad-ai\autocad-ai` (Windows 11, PowerShell/Git Bash), not inferred from reading code.

## 1. What was broken

The project root contained **two dead virtual environments**, both non-functional:

- `venv/` — its `pyvenv.cfg` pointed at `C:\Users\SabihAamir\AppData\Local\Programs\Python\Python312\python.exe`. That path no longer exists on this machine (the Windows user profile is now `sabih`, not `SabihAamir` — looks like a machine/profile rename or a copy from another machine). Every venv Python invocation failed immediately with `No Python at ...`.
- `venv-broken-20260902-165925/` — a previous self-repair attempt (see `setup-and-start.ps1` below) that rebuilt the venv using **Python 3.14.2**. The project pins `pywin32==311` and several other exact versions in `requirements.txt` for **Python 3.11+**; a 3.14 interpreter is outside the range the pinned wheels were built/tested for and this venv was left named "broken", i.e. a previous session (human or AI) already gave up on it.

Both were gitignored (`venv/`, `.venv/` in `.gitignore`), so neither was ever a source-control concern — just local disk state.

There is also a repo-root **path mismatch** worth knowing: `setup-and-start.ps1` and `start-autocad-ai.bat` both hardcode `$Proj = 'C:\RC-Projects\autocad-ai\autocad-ai'`, but the project actually lives at `F:\RC-Projects\autocad-ai\autocad-ai` on this machine. Neither script will find the project as-is; either edit the `PROJ`/`$Proj` line in both files, or run them from a checkout that really is at `C:\RC-Projects\autocad-ai\autocad-ai`.

## 2. What was done

```bash
# From the project root
rm -rf venv "venv-broken-20260902-165925"
py -3.11 -m venv venv
venv/Scripts/python.exe -m pip install --upgrade pip
venv/Scripts/python.exe -m pip install -r requirements.txt
```

Python interpreters available on this machine (via the `py` launcher): 3.14.2 and **3.11.9**. 3.11.9 was used, matching the README's stated requirement ("Python 3.11+") and matching what the pinned `requirements.txt` wheels expect for Windows (`cp311` wheel tags — e.g. `pywin32-311-cp311-cp311-win_amd64.whl`, `numpy-2.4.4-cp311-cp311-win_amd64.whl`, `scipy-1.17.1-cp311-cp311-win_amd64.whl`).

All 41 pinned dependencies installed cleanly with no compilation needed (all had prebuilt `win_amd64`/`py3-none-any` wheels available for 3.11) — total install time ~2-3 minutes, dominated by `scipy` (36.6 MB download).

## 3. Verification performed

**App import:**
```bash
venv/Scripts/python.exe -c "from src.api.main import app; print('api import OK')"
```
Result: `api import OK` (preceded by a harmless `fonttools`/`ezdxf` warning — `'name' table stringOffset incorrect. Expected: 222; Actual: 224` — this comes from `ezdxf` parsing a bundled font on import and does not affect functionality).

**Full test suite:**
```bash
venv/Scripts/python.exe -m pytest tests/ -q
```
Result: **892 passed, 10 skipped, 0 failed** (~73-150s depending on disk cache).

The 10 skips are all intentional and are exactly the "live AI" tests the README describes — each is gated behind an environment variable and prints its own skip reason, e.g.:
```
SKIPPED tests\parametric\test_vessel_planner_live.py:27: Skipping live AI tests. Set RUN_LIVE_AI=1 to run.
SKIPPED tests\framework\test_cad3d_scene_planner.py:389: Set RUN_LIVE_AI_TESTS=1 to run live AI CAD3D planner tests.
SKIPPED tests\framework\test_chunked_command_generator.py:347: Set RUN_LIVE_AI_TESTS=1 to run live AI chunked command tests.
SKIPPED tests\framework\test_chunked_command_orchestrator.py:415: ...
SKIPPED tests\framework\test_command_generator.py:123: ...
SKIPPED tests\framework\test_command_repairer.py:230: ...
SKIPPED tests\framework\test_command_verifier.py:138: ...
SKIPPED tests\framework\test_drawing_task_planner.py:160: ...
SKIPPED tests\framework\test_edit_generator.py:215: ...
SKIPPED tests\framework\test_pid_component_planner.py:241: Set RUN_LIVE_AI_TESTS=1 to run live AI P&ID component planner tests.
```
Note the env var is **not** consistently named: most modules check `RUN_LIVE_AI_TESTS`, but `test_vessel_planner_live.py` checks `RUN_LIVE_AI` (no `_TESTS` suffix). If you intend to enable *all* live AI tests, set both:
```bash
export RUN_LIVE_AI_TESTS=1
export RUN_LIVE_AI=1
```
Enabling either will make real network calls to the DeepSeek API using the key in `.env` and will consume API credits.

**Not verified (requires Windows COM + a licensed AutoCAD install, neither available in this analysis environment):**
- `GET /api/autocad-status`, `GET /api/autocad/inspect`, `POST /api/autocad/edit`, and every "approve/build" endpoint that actually calls into `win32com.client.GetActiveObject("AutoCAD.Application")`.
- Actually running `python -m uvicorn src.api.main:app` and clicking through the chat UI end-to-end against a live drawing.
- All AutoCAD-COM-dependent unit tests mock `win32com.client` rather than touching real AutoCAD — see [04_command_and_autocad_framework.md](04_command_and_autocad_framework.md) for exactly which tests do this and how.

## 4. `.env` — AI provider configuration

A `.env` file already exists at the project root with a **live DeepSeek API key** committed to local disk (never to git — `.env` and `.env.*` are gitignored). Shape (values redacted here deliberately — see the real file, do not paste its contents into any doc, chat log, or issue tracker):
```
AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=<redacted, present and non-placeholder>
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```
Because a real key is present, `/api/sketch/generate`, `/api/pid/generate`, `/api/cad3d/generate`, and the AI-assisted use_cases will attempt real DeepSeek calls if exercised. The P&ID and CAD3D generate paths degrade gracefully to deterministic templates if the AI call fails (see [03_ai_layer.md](03_ai_layer.md) and [06_pid_framework.md](06_pid_framework.md)); the generic sketch/command-generator path does not have the same template fallback (see [04_command_and_autocad_framework.md](04_command_and_autocad_framework.md)).

**Security note:** treat the existing `.env` value as a real, live secret. If this repository or its local folder is ever shared, zipped, or pushed anywhere, rotate the DeepSeek key first.

## 5. Local generated state already on disk

None of this is source-controlled (all gitignored), but it exists locally and is worth knowing about before assuming a "clean" checkout:

| Path | Size | Contents |
|---|---|---|
| `jobs.db` | 3.2 MB | SQLite audit trail from prior runs — see [08_use_cases_logging_scratch.md](08_use_cases_logging_scratch.md) for schema |
| `outputs/` | 8.3 MB, 188 files | Prior generated scenes/drawings/previews, including `outputs/cad3d/scenes/*.json` (persisted CAD3D scenes) |
| `backups/` | 840 KB, 19 `.dwg` files | Timestamped pre-edit drawing backups from `src/backup.py` |
| `src/backups/` | 132 KB, 3 `.dwg` files | A second, separate backup location (see known-issues doc for why there are two) |
| `ErrorReports/` | 8 KB | An AutoCAD crash/error report folder (`cer.log`) — evidence AutoCAD itself has crashed at least once during prior use of this project |
| `uvicorn.stdout.log` / `uvicorn.stderr.log` | small | Logs from a previous `uvicorn` run left at the repo root |

None of this was deleted — it's prior work product / evidence of prior real usage, not build artifacts, so it was left untouched (unlike the two broken `venv` folders, which were purely disposable and unusable).

## 6. How to run the app for real (once AutoCAD is available)

```powershell
cd F:\RC-Projects\autocad-ai\autocad-ai
.\venv\Scripts\python.exe -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```
Then open `http://127.0.0.1:8000/sketch.html` (chat UI), `http://127.0.0.1:8000/jobs.html` (audit history), or `http://127.0.0.1:8000/docs` (Swagger). AutoCAD must be running with an active drawing for anything that executes/inspects/edits to succeed; generate-only calls (sketch/pid/cad3d `/generate`) work without AutoCAD open since they only produce a cached plan, not COM calls.

The repo also has two convenience launchers (`setup-and-start.ps1`, `start-autocad-ai.bat`) that auto-detect a Python interpreter, rebuild the venv if needed, and open the browser automatically — but both currently have the hardcoded `C:\...` path problem described in §1. `setup-and-start.ps1` is otherwise a reasonable self-healing script and was clearly written to fix exactly the kind of venv rot found in §1.

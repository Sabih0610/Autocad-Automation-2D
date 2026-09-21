# API Layer — `src/api/` (FastAPI app + static web UI)

This document is an exhaustive reference to the FastAPI application layer and the
static chat-style web UI of the "AutoCAD AI Automation" project. It is written so a
future agent can work in this code without re-reading the source.

---

## 1. Role in the system

`src/api/` is the HTTP boundary of the application. It is a "thin wrapper" (the
FastAPI app's own `description` field literally says so) around pre-existing
non-web use-case modules (`src/use_cases/*`), AI planners (`src/ai/*`), and a
deterministic COM executor framework (`src/framework/*`). Routes never talk to
AutoCAD or an LLM directly for anything destructive without going through a
generate→(cache token)→approve/confirm pattern: an AI/deterministic planner
produces a JSON plan (schema-validated further down the stack), the plan is
cached server-side (in-memory dict, keyed by a `uuid4().hex` token, with a TTL
for sketch/vessel flows), and a second endpoint (`/approve`, `/confirm`, or the
`auto_execute=True` default of `/api/autocad/edit`) takes the token and actually
drives AutoCAD via `pythoncom`/`win32com`. A middleware
(`AuditJobMiddleware`) + endpoint-wrapping mechanism (`_install_audit_wrappers`)
transparently logs every request/response of the routes listed in
`AUDIT_ROUTE_MAP` into a local SQLite `jobs.db` (via `src/logging/jobs.py`), so
that `/api/jobs` and `/api/jobs/{job_id}` (and the `jobs.html` / `vessel.html`
pages) can show history. Static HTML pages under `src/api/static/` are plain
server-rendered-by-fetch single-page-ish views (no build step, no framework) that
call these JSON APIs directly with `fetch()`.

---

## 2. App wiring — `src/api/main.py`

File: `F:\RC-Projects\autocad-ai\autocad-ai\src\api\main.py` (361 lines).

### 2.1 Constants & app object
- `PROJECT_ROOT = Path(__file__).resolve().parents[2]` → repo root.
- `OUTPUTS_DIR = PROJECT_ROOT / "outputs"` — where all generated files
  (previews, vessels, reports, line lists) live and are served from.
- `STATIC_DIR = Path(__file__).resolve().parent / "static"` — the HTML/JS UI.
- `MAX_AUDIT_BYTES = 100 * 1024` (100 KB) — cap for both request and response
  payloads stored in the audit log; anything bigger is replaced with
  `{"_truncated": True, "size_bytes": N}`.
- `app = FastAPI(title="AutoCAD AI Automation", description="Thin FastAPI wrapper over the existing AutoCAD AI use case modules.")`.
- Routers included, in this exact order (`app.include_router(...)`, main.py:56-65):
  `title_block_router`, `line_list_router`, `place_symbol_router`,
  `consistency_router`, `vessel_router`, `sketch_router`,
  `autocad_inspect_router`, `autocad_edit_router`, `pid_router`, `cad3d_router`.

### 2.2 `AUDIT_ROUTE_MAP` (main.py:30-46)
Exact path → use_case string mapping used both by the middleware (to start a
job) and indirectly by `_install_audit_wrappers` (matches routes by `route.path`,
which is the *router-relative-prefixed* path FastAPI stores, e.g.
`/api/autocad/edit` not just `/edit`):

| Path | use_case string |
|---|---|
| `/api/title-block-update` | `title_block_update` |
| `/api/line-list-extract` | `line_list_extract` |
| `/api/place-symbol` | `place_symbol` |
| `/api/consistency-check` | `consistency_check` |
| `/api/generate-vessel/extract` | `generate_vessel_extract` |
| `/api/generate-vessel/confirm` | `generate_vessel_confirm` |
| `/api/sketch/generate` | `sketch_generate` |
| `/api/sketch/approve` | `sketch_approve` |
| `/api/autocad/inspect` | `autocad_inspect` |
| `/api/autocad/edit` | `autocad_edit` |
| `/api/pid/generate` | `pid_generate` |
| `/api/pid/approve` | `pid_approve` |
| `/api/cad3d/generate` | `cad3d_generate` |
| `/api/cad3d/edit` | `cad3d_edit` |
| `/api/cad3d/approve` | `cad3d_approve` |

Every other route (health, autocad-status, download, jobs, and the CAD3D
`/api/cad3d/state*` GET routes) is **not** audited.

### 2.3 Audit mechanism — two cooperating pieces

**(a) `AuditJobMiddleware` (ASGI middleware class, main.py:203-274)**, added via
`app.add_middleware(AuditJobMiddleware)`. For every HTTP request:
1. If `scope["path"]` is not in `AUDIT_ROUTE_MAP`, pass through untouched
   (`await self.app(scope, receive, send)`), no job row created.
2. Otherwise it **fully drains the request body** by looping on `receive()`
   until `more_body` is `False`, concatenating chunks into `request_body: bytes`.
3. It builds a `replay_receive()` closure that replays the buffered body back
   as a single `http.request` message the first time it's awaited, then returns
   an empty terminating message — this is required because the body stream can
   only be consumed once, but the downstream route/`_install_audit_wrappers`
   layer (which is really just FastAPI's normal request parsing) also needs to
   read it.
4. Decodes headers into a `dict[str, str]` (lower-cased keys), extracts
   `content-type` and `user-agent`.
5. Calls `_decode_request_payload(body, content_type)`: empty body → `{}`;
   body over `MAX_AUDIT_BYTES` → truncation marker; non-JSON content-type →
   `{"_unsupported": True, "content_type": ..., "size_bytes": ...}`; JSON parse
   failure → `{"_invalid_json": True, "size_bytes": ...}`; otherwise the parsed
   JSON object.
6. Calls `_truncate_payload(...)` again on that result (double gate — belt and
   suspenders on size).
7. Calls `log_job_start(use_case=..., source="api", request_data=..., user_agent=...)`
   → returns a `job_id` (uuid4 hex) that gets INSERTed into the `jobs` SQLite
   table with `status` presumably `"started"` (see `src/logging/jobs.py`).
8. Stores `job_id` and a `False` "completed" flag into two `ContextVar`s:
   `CURRENT_AUDIT_JOB_ID` and `CURRENT_AUDIT_COMPLETED` (module-level in
   main.py, so they're only visible within this async task's context — safe
   under concurrent requests because ContextVars are per-task).
9. Calls `await self.app(scope, replay_receive, send_wrapper)` — i.e. runs the
   *rest* of the ASGI chain (FastAPI's routing/exception handling) with the
   replayable receive channel. `send_wrapper` currently does nothing extra
   (just forwards) — it's a no-op hook point, not used to capture response body
   at the middleware layer.
10. If an exception propagates out of `self.app(...)` and no wrapped endpoint
    already marked the job completed (`CURRENT_AUDIT_COMPLETED.get()` is
    `False`), the middleware itself calls `log_job_end(job_id, status="error",
    error_message=str(exc))` as a fallback safety net — this covers unhandled
    exceptions that occur *before* reaching (or bypassing) the endpoint wrapper,
    e.g. Pydantic validation errors on the request body (422s) that never even
    call the route function.
11. `finally`: resets both ContextVars to their prior tokens.

**(b) `_install_audit_wrappers()` (main.py:164-200)**, called once at import
time right after the middleware is registered. It walks `app.routes`, and for
every `APIRoute` whose `.path` is a key in `AUDIT_ROUTE_MAP`, it:
- Grabs `original_endpoint = route.endpoint`.
- Builds either an `async_wrapper` or `sync_wrapper` (chosen via
  `inspect.iscoroutinefunction`) that calls the original endpoint, and on
  success calls `_log_wrapped_route_success(result)`; on exception calls
  `_log_wrapped_route_error(exc)` then re-raises.
- Monkey-patches `route.endpoint`, `route.dependant.call`, **and**
  `route.app = request_response(route.get_route_handler())` — this last step is
  necessary because FastAPI pre-compiles the ASGI-callable `route.app` at
  route-registration time from `route.endpoint`; simply reassigning
  `route.endpoint` would not be picked up otherwise. This is a somewhat fragile,
  implementation-detail-dependent technique tied to the installed FastAPI
  version's internals (`fastapi.routing.APIRoute`, `request_response`).

`_log_wrapped_route_success(result)` (main.py:131-149):
- No-ops if no `CURRENT_AUDIT_JOB_ID` is set (i.e., route wasn't reached via the
  audited middleware path — shouldn't normally happen since wrapping only
  applies to audited paths, but this guards against being called without the
  middleware, e.g. in some test configurations).
- Truncates `result` via `_truncate_payload`.
- `_status_from_result(payload)`: `"error"` if `payload` is a dict with
  `ok is False`, else `"ok"`. Note: this means a 200-status JSON response with
  `{"ok": false, ...}` (e.g. vessel confirm's AutoCAD-not-running branch, or
  edit/approve routes where execution partially failed) is logged as job
  status `"error"` even though the HTTP status code was 200.
- `_extract_ai_output(payload)`: pulls out `planned_spec`, `ai_explanation`,
  `extracted` keys (if present and non-null) into a separate `ai_output` column
  — used by e.g. `place_symbol` (`planned_spec`), `consistency_check`
  (`ai_explanation`), and the vessel extract/confirm flow (`extracted`).
- Calls `log_job_end(job_id, status=..., result_data=..., ai_output=...,
  error_message=payload.get("detail") if dict else None)`. Note:
  `error_message` here only picks up a `detail` key, which is the FastAPI/
  HTTPException convention, not `message`/`error_type` used by some routes
  (e.g. vessel confirm uses `message` on failure, not `detail` — so those
  error messages won't appear in the audit log's `error_message` field even
  though `status` will still be `"error"`).
- Sets `CURRENT_AUDIT_COMPLETED` to `True` so the middleware's own
  exception-fallback `log_job_end` call is skipped.

`_log_wrapped_route_error(exc)` (main.py:152-161): logs `status="error"`,
`error_message=str(exc)`, and also flags completed — this covers
`HTTPException`s raised inside the route body (400/404/500/502/503 etc.), since
those exceptions are re-raised by the wrapper *before* FastAPI's exception
handler turns them into a JSON response, so the wrapper sees the raw exception.

**Net effect:** almost every outcome (success, `HTTPException`, or truly
unhandled exception) produces exactly one `log_job_end` call — either from the
wrapper or, only for exceptions that occur outside the wrapped endpoint (e.g.
request validation errors), from the middleware's fallback.

### 2.4 System routes (all defined directly in `main.py`, undecorated by the audit wrappers since their paths aren't in `AUDIT_ROUTE_MAP`)

- **`GET /health`** (tags=["system"]) → `{"status": "ok"}`. No side effects.
- **`GET /api/autocad-status`** (tags=["system"]) → calls
  `pythoncom.CoInitialize()`, tries `win32com.client.GetActiveObject("AutoCAD.Application")`.
  On success: `{"reachable": True, "caption": acad.Caption, "active_drawing": doc.Name or None}`
  (drawing-name lookup wrapped in its own try/except → `None` on failure).
  On any exception connecting to AutoCAD: `{"reachable": False, "caption": None,
  "active_drawing": None, "error": "ExcType: msg"}`. Always
  `pythoncom.CoUninitialize()` in `finally`. Never raises an HTTP error — always
  200.
- **`GET /api/download/{filename:path}`** (tags=["system"]) → serves files out of
  `OUTPUTS_DIR` only. Path-traversal guards: rejects empty filename, any `..`
  segment, or an absolute path with 400; then resolves
  `(OUTPUTS_DIR / filename).resolve()` and requires it stay under
  `OUTPUTS_DIR.resolve()` (via `relative_to`, catching `ValueError` → 400); 404
  if not an existing file. Returns `FileResponse(..., media_type="application/octet-stream")`
  — note the media type is always octet-stream regardless of real content type
  (so e.g. `.dwg`/`.xlsx`/`.dxf` downloads all present as generic binary).
- **`GET /api/jobs`** (tags=["jobs"]) — query params `limit` (1–200, default 50),
  `use_case` (optional), `status` (optional) → `list_recent_jobs(...)` from
  `src/logging/jobs.py`. Returns a bare JSON array (not wrapped in `{"ok":...}`).
- **`GET /api/jobs/{job_id}`** (tags=["jobs"]) → `get_job(job_id)`; 404 if `None`;
  else the full stored job row as JSON.
- Mounts, in this order (order matters for path-conflict resolution — first
  match wins per FastAPI/Starlette routing? actually for `StaticFiles` mounts,
  order among *different* mount prefixes doesn't conflict since prefixes
  differ, but note `/static` and `/` both point at the same `STATIC_DIR`,
  so every static asset is reachable at two different URLs):
  - `app.mount("/outputs", StaticFiles(directory=OUTPUTS_DIR, check_dir=False), name="outputs")`
    — `check_dir=False` means this won't fail at startup even if `outputs/`
    doesn't exist yet; direct browser access to `/outputs/...` bypasses the
    `/api/download` filename-sanitization entirely (though `StaticFiles`
    has its own path-traversal protections internally).
  - `app.mount("/static", StaticFiles(directory=STATIC_DIR, html=True), name="static-files")`.
  - `app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")`
    — catches everything not otherwise routed, serving `index.html` at `/`,
    `sketch.html` at `/sketch.html`, etc. (`html=True` enables directory-index
    and extensionless lookups).

---

## 3. `src/api/chat_routing.py` — chat intent router

Pure functions, no I/O, no FastAPI dependency. This module's logic is
**duplicated line-for-line in JavaScript** inside `src/api/static/sketch.html`
(see §6.2) — a test (`test_static_ui_javascript_routing_matches_expected_endpoints`)
literally extracts the JS block and runs it under Node to assert the two stay
behaviorally identical. Whenever `chat_routing.py` changes, the JS block in
`sketch.html` must be changed to match, or that test breaks (if Node.js is
unavailable in the environment, the test is skipped rather than failing —
`pytest.skip` when `shutil.which("node")` is `None`).

### 3.1 Route constants
`CHAT_ROUTE_CAD3D = "cad3d_generate"`, `CHAT_ROUTE_CAD3D_EDIT = "cad3d_edit"`,
`CHAT_ROUTE_PID = "pid_generate"`, `CHAT_ROUTE_SKETCH = "sketch_generate"`,
`CHAT_ROUTE_EDIT = "autocad_edit"`.

### 3.2 Helpers (all operate on `normalize_prompt(prompt)` — lower-cased,
whitespace-collapsed, stripped; `_normalize_prompt` is just an alias)

- **`is_new_drawing_request(prompt)`** — `True` if the normalized prompt
  *starts with* one of: `"draw "`, `"create "`, `"generate "`, `"build "`,
  `"make "`, `"design "`, `"prepare "`, `"draft "`.
- **3D/2D intent regex sets:**
  - `_THREE_D_INTENT_PATTERNS`: `\b3d\b`, `\b3-d\b`, `\b3 dimensional\b`,
    `\b3-dimensional\b`, `\bthree dimensional\b`, `\bthree-dimensional\b`,
    `\bsolid model\b`, `\bisometric model\b`.
  - `_NEGATED_3D_PATTERNS`: five regexes covering `"not a 3d..."`, `"no 3d..."`,
    `"do not/don't/dont [verb] a 3d..."`, `"2d, not a 3d..."`, and
    `"3d ... is not"`.
  - `_TWO_D_INTENT_PATTERNS`: `\b2d\b`, `\b2-d\b`, `\btwo dimensional\b`,
    `\btwo-dimensional\b`, `\bflat\b`, `\bflat diagram\b`, `\b2d drawing\b`,
    `\b2d process layout\b`, `\b2d autocad drawing\b`.
  - `has_negated_3d_intent`, `has_explicit_3d_intent`, `has_explicit_2d_intent`
    are direct regex-search wrappers.
  - **`is_3d_request(prompt) = has_explicit_3d_intent(prompt) and not
    has_negated_3d_intent(prompt)`.**
- **`is_pid_request(prompt)`**:
  1. `True` if the normalized prompt contains standalone token `pid` (regex
     `(^|[^a-z0-9])pid([^a-z0-9]|$)`).
  2. `True` if it contains any "strong" signal substring: `"p&id"`,
     `"p and id"`, `"piping and instrumentation"`, `"piping & instrumentation"`,
     `"instrumentation diagram"`, `"process diagram"`, `"process unit"`.
  3. Otherwise, scores +1 for each of ~30 "weighted" signal substrings present
     (`separator`, `horizontal separator`, `vertical vessel`, `storage tank`,
     `vessel`, `scrubber`, `tank`, `pump`, `pumps`, `exchanger`,
     `heat exchanger`, `3 phase`, `three phase`, `vapor outlet`, `oil outlet`,
     `water outlet`, `feed inlet`, `liquid outlet`, `suction`, `discharge`,
     `gate valve`, `control valve`, `valves`, `instrument`, `instruments`,
     `instrument bubble`, `level control`, `pressure control`, `pi-`, `pt-`,
     `lt-`, `lc-`, `fi-`, `ti-`) — `True` if score ≥ 2. Note some substrings
     overlap (e.g. `"instrument"` also matches inside `"instruments"` and
     `"instrument bubble"`, so a phrase like "instrument bubble" alone can
     contribute up to 2 hits by itself: `"instrument"` + `"instrument bubble"`).
- **`is_edit_request(prompt)`**:
  - Returns `False` immediately if `is_new_drawing_request(prompt)` is `True`
    (creation always wins over edit-verb false positives like "build and
    change the...").
  - `direct_edit_verbs` = `delete, remove, erase, move, shift, change, rename,
    modify, update, replace, resize, extend, trim, rotate, edit`.
  - `context_edit_verbs` = `direct_edit_verbs + (add, connect)`.
  - `existing_context_words` = `existing, current drawing, current autocad,
    this drawing, active drawing, the title, title text, the circle,
    the vessel, the valve, the line, the text, this line, this vessel,
    that circle, outlet line, separator outlet`.
  - `True` if the prompt *equals* or *starts with* `"{verb} "` for a
    direct-edit verb, OR if it contains a context-edit verb (as `"{verb} "`
    substring or exact match) **and** also contains one of the
    existing-context phrases.
- **CAD3D edit intent** (`_CAD3D_EDIT_VERBS`: `move, shift, relocate, change,
  set, update, resize, increase, decrease, delete, remove, add, place,
  lengthen, shorten`; `_CAD3D_EQUIPMENT_TERMS`: `pump, tank, vessel, separator,
  exchanger, heat exchanger, valve, flange, support, support leg, support legs,
  skid, nozzle, pipe, routed pipe`; `_CAD3D_COMPONENT_ID_PATTERN =
  re.compile(r"\b[A-Z]{1,4}-?\d{2,4}[A-Z]?\b", re.IGNORECASE)` — matches tags
  like `P-101`, `V201`, `T-101A`):
  - **`has_cad3d_edit_intent(prompt)`**: `False` if it's a new-drawing request
    or has explicit 2D intent. Otherwise requires an edit verb present (exact
    match, `"{verb} "` prefix, or `" {verb} "` substring). Then: if a
    component-ID pattern matches anywhere in the *original* (non-normalized)
    prompt, return `True` immediately; else return `True` only if
    `is_3d_request(prompt)` **and** an equipment term is present.
  - **Important divergence vs. `decide_chat_route`'s actual usage:** the
    Python `has_cad3d_edit_intent` is used directly inside
    `decide_chat_route`. But the JS twin (`hasCAD3DEditIntent`, in
    `sketch.html`) is only an *input* to a further gate,
    `shouldRouteToCAD3DEdit`, which additionally requires
    "CAD3D context" (`hasCAD3DContext()` — a stored latest-CAD3D-token or an
    in-memory flag that the last generation was a CAD3D scene) before routing
    to CAD3D-edit; **the Python side has no equivalent context/token gate at
    all** — see §7 Cross-cutting observations for why this matters.
- **`decide_chat_route(prompt)`** — final decision tree, evaluated in this
  order:
  1. `is_new_drawing_request` → if 3D → `CHAT_ROUTE_CAD3D`; elif P&ID →
     `CHAT_ROUTE_PID`; else → `CHAT_ROUTE_SKETCH`.
  2. Else if `has_cad3d_edit_intent` → `CHAT_ROUTE_CAD3D_EDIT`.
  3. Else if `is_edit_request` → `CHAT_ROUTE_EDIT`.
  4. Else if `is_3d_request` → `CHAT_ROUTE_CAD3D`.
  5. Else if `is_pid_request` → `CHAT_ROUTE_PID`.
  6. Else → `CHAT_ROUTE_SKETCH` (default/fallback for anything else, e.g. a
     simple "draw a rectangle").

This module is pure logic; it is **not itself called by any FastAPI route** —
`main.py` and the route modules never import from `chat_routing.py`. It exists
purely (a) to be unit-tested (`tests/api/test_chat_routing.py`) as the
canonical routing spec, and (b) as the thing the JS in `sketch.html` must stay
in sync with. The actual live routing decision at runtime happens client-side
in the browser (see §6.2) — the browser JS decides which of
`/api/sketch/generate`, `/api/pid/generate`, `/api/cad3d/generate`,
`/api/cad3d/edit`, or `/api/autocad/edit` to call.

---

## 4. `src/api/schemas.py` — shared Pydantic request models

File: `F:\RC-Projects\autocad-ai\autocad-ai\src\api\schemas.py`. All models use
`model_config = ConfigDict(extra="forbid")` (unknown fields → 422). Note: some
routes (sketch.py, vessel.py, autocad_edit.py, cad3d.py's own request classes
are actually defined *inline in the route file*, not here — see per-route
sections). Models actually defined here:

- **`DEFAULT_SYMBOL_PROMPT`** (module constant, not a model): `"Add pump P-101
  at coordinates 500, 250 on layer P-EQUIPMENT for cooling water."`
- **`JobResultResponse`**: `ok: bool` (required), `message: str | None = None`.
  Declared but not referenced as a `response_model` by any route found in this
  scope — appears to be a documentation/legacy artifact.
- **`TitleBlockUpdateRequest`** (used by `POST /api/title-block-update`):
  - `drawings_folder: str = r"E:\RC-Projects"`
  - `file_pattern: str = "drawing_*.dwg"`
  - `title_block_name: str = "TITLE_BLOCK_TEST"`
  - `updates: dict[str, str]` default `{"REV": "G", "DATE": "2026-05-01", "DRAWN_BY": "S. AAMIR"}`
  - `dry_run: bool = True`
- **`LineListExtractRequest`** (used by `POST /api/line-list-extract`):
  - `drawings_folder: str = r"E:\RC-Projects"`
  - `target_file: str = "pid_001.dwg"`
  - `line_block_name: str = "LINE_BLOCK_TEST"`
- **`PlaceSymbolRequest`** (used by `POST /api/place-symbol`):
  - `prompt: str = DEFAULT_SYMBOL_PROMPT`
  - `execute: bool = False`
- **`ConsistencyCheckRequest`** (used by `POST /api/consistency-check`):
  - `pid_path: str = r"E:\RC-Projects\pid_001.dwg"`
  - `excel_path: str = ""` (blank ⇒ auto-select newest clean line list in `outputs/`)
  - `use_ai_explanation: bool = True`
- **`PIDGenerateRequest`** (used by `POST /api/pid/generate`):
  - `prompt: str` (required)
  - `drawing_style: str = "clean schematic P&ID"`
- **`PIDApproveRequest`** (used by `POST /api/pid/approve`):
  - `token: str` (required)
  - `save: bool = False`
  - `target_dwg_path: str | None = None`
- **`CAD3DGenerateRequest`** (used by `POST /api/cad3d/generate`):
  - `prompt: str | None = None`
  - `drawing_style: str = "simple clean 3D equipment layout"`
  - `example_name: str = "simple_component_layout"`
- **`CAD3DApproveRequest`** (used by `POST /api/cad3d/approve`):
  - `token: str` (required), `save: bool = False`, `target_dwg_path: str | None = None`
- **`CAD3DEditRequest`** (used by `POST /api/cad3d/edit`):
  - `prompt: str` (required)
  - `token: str | None = None` (omitted ⇒ use latest stored scene)
  - `execute: bool = False`
  - `save: bool = False`
  - `target_dwg_path: str | None = None`
  - `create_new_token: bool = True`

Models **not** in this file but defined locally inside their route module
(kept here for cross-reference since they are just as much "the schema" for
their route): `sketch.py` → `SketchGenerateRequest`, `SketchApproveRequest`;
`vessel.py` → `VesselExtractRequest`, `VesselConfirmRequest`;
`autocad_edit.py` → `AutoCADEditRequest`. `autocad_inspect.py` takes only a
query parameter (`max_entities`), no body model at all.

---

## 5. Per-route reference (`src/api/routes/*.py`)

### 5.1 `autocad_edit.py` — live single-shot AutoCAD edit (no token/approve split)

- Router prefix `/api/autocad`, tag `autocad`.
- **`AutoCADEditRequest`** (local Pydantic model, `extra="forbid"`):
  `prompt: str` (`min_length=1`), `max_entities: int = 200` (`ge=1, le=2000`),
  `auto_execute: bool = True`, `save: bool = False`, `target_dwg_path: str | None = None`.
- **`POST /api/autocad/edit`** (`edit_autocad_drawing`):
  1. Strips prompt; 400 if empty after strip.
  2. `_inspect_with_com(max_entities)`: `pythoncom.CoInitialize()` →
     `inspect_active_drawing(max_entities)` (from
     `src.framework.autocad.inspector`) → `summarize_drawing_state(inspection)`
     → `CoUninitialize()` in `finally`. `AutoCADNotRunningError` (from
     `src.parametric.vessel.dwg_export`) → 503 with fixed message
     `"AutoCAD is not running. Open AutoCAD with a drawing active and try again."`
     (module constant `AUTOCAD_NOT_RUNNING_DETAIL`); any other exception → 500
     `"AutoCAD drawing inspection failed: {ExcType}: {exc}"`.
  3. `generate_edit_plan(prompt, inspection)` (from `src.ai.edit_generator`):
     `ValueError` → 400 with the exception's message verbatim (used for
     "ambiguous edit request" cases); any other exception → 502
     `"Edit generation failed: {ExcType}: {exc}"`.
  4. If `auto_execute is False`: returns immediately without executing —
     `{"ok": True, "executed": False, "prompt", "inspection_summary",
     "document_name", "entity_count_returned", "edit_plan", "execution_result": None}`.
  5. Else `_execute_with_com(edit_plan, target_dwg_path, save)`:
     `execute_edit_plan(edit_plan, target_dwg_path=..., save=..., zoom_extents=True)`
     from `src.framework.commands.edit_executor`, wrapped in
     `CoInitialize`/`CoUninitialize`. `AutoCADNotRunningError` → 503 (same
     message); other exceptions → 500 `"AutoCAD edit execution failed: ..."`.
  6. Final response: `{"ok": bool(execution_result["ok"]), "executed": True,
     "prompt", "inspection_summary", "document_name", "entity_count_returned",
     "edit_plan", "execution_result"}`. Note: even when the executor itself
     reports `ok: False` (partial failure, e.g. some deletes failed), the HTTP
     status is still 200 — failure is only visible in the JSON body's `ok`
     field and `execution_result.errors`.
- Side effects: mutates the live AutoCAD drawing in-process via COM
  (deletes/adds entities per the edit plan); optionally saves the DWG; no
  files written to disk by this route itself. Audited under `autocad_edit`.
- Contract confirmed by `tests/api/test_autocad_edit_routes.py`: validates
  200/400/422/503/500 behavior above, that `max_entities` is passed through to
  `inspect_active_drawing`, that `save`/`target_dwg_path` are forwarded to
  `execute_edit_plan`, and that an executor-level `ok: False` result still
  yields HTTP 200 with `ok: false` in the body.

### 5.2 `autocad_inspect.py` — read-only drawing snapshot

- Router prefix `/api/autocad`, tag `autocad`.
- **`GET /api/autocad/inspect?max_entities=200`** (query param, `ge=1, le=2000`,
  default 200): `pythoncom.CoInitialize()` → `inspect_active_drawing(max_entities)`
  → `summarize_drawing_state(inspection)` → `CoUninitialize()` in `finally`.
  `AutoCADNotRunningError` → 503 (same fixed message as §5.1); other exceptions
  → 500 `"AutoCAD drawing inspection failed: {ExcType}: {exc}"`.
  Response: `{"ok": True, "summary": <str>, "inspection": <full inspection dict>}`.
  No mutation, no caching, no token. Audited under `autocad_inspect`.
- The inspection dict shape (per fakes in tests): `ok`, `document_name`,
  `dwg_path`, `entity_count_total`, `entity_count_returned`, `truncated`,
  `entities: [{index, handle, object_name, entity_type, layer, color?,
  linetype?, position, center, radius, start_point, end_point, text, bbox}, ...]`.

### 5.3 `cad3d.py` — 3D CAD scene generate/state/edit/approve (largest route module)

- Router prefix `/api/cad3d`, tag `cad3d`.
- Module-level `_CAD3D_CACHE: dict[str, dict]` — a **second**, independent,
  non-TTL, purely in-memory cache keyed by token, used only by `/approve`
  (looked up by `_CAD3D_CACHE.get(request.token)`, 404 if absent — cache
  entries never expire and are never pruned on process lifetime). This exists
  *alongside* the persistent-ish `CAD3DSceneStore` (`get_default_cad3d_scene_store()`,
  from `src.framework.cad3d.scene_store`) which is the source of truth for
  `/state`, `/state/latest`, `/state/{token}`, and `/edit`'s source lookup.
  **Both stores are populated on `/generate` and `/edit`**, but `/approve` only
  reads from `_CAD3D_CACHE`, not from the scene store — so a token that exists
  in the scene store but was evicted/never entered `_CAD3D_CACHE` (not
  currently possible since both are always written together in `/generate` and
  `/edit`, but structurally a divergent risk) would 404 on `/approve` even
  though `/state/{token}` would still find it.
- **`POST /api/cad3d/generate`** (`CAD3DGenerateRequest`):
  1. If `request.prompt` (after `.strip()`) is truthy: call
     `plan_cad3d_scene_resilient(prompt, drawing_style=..., allow_example_fallback=True)`
     (from `src.ai.cad3d_scene_planner`). Any exception → 502
     `"3D CAD scene planning failed: {ExcType}: {msg (truncated to 2000 chars)}"`.
     `generation_strategy = metadata.get("planner_strategy") or "ai_cad3d_scene_planner"`.
  2. Else (no prompt): `get_cad3d_component_example(example_name)` (default
     `"simple_component_layout"`) from `src.framework.cad3d.component_examples`.
     `ValueError` (unknown example) → 400, listing
     `available_cad3d_component_examples()`; other exception → 500.
     `component_scene.to_scene_data()` → `scene_data`; `generation_strategy =
     "component_example"`.
  3. Mints `token = uuid.uuid4().hex`. Stores full context in `_CAD3D_CACHE[token]`
     (prompt, drawing_style, example_name, scene_data, created_at=`time.time()`,
     generation_strategy, fallback_used/reason/example/template names).
  4. `extract_scene_component_summary(scene_data)` → `component_ids`,
     `component_count`, `component_types`.
  5. Attempts `get_default_cad3d_scene_store().put_generated_scene(token=...,
     prompt, drawing_style, scene=scene_data, generation_metadata=...)`. If
     this raises `CAD3DSceneStoreError` containing `"Invalid CAD3D scene"` →
     500 (schema validation failure is fatal — the generate call fails
     outright even though `_CAD3D_CACHE` was already populated, meaning
     `/approve` could technically still work with that token despite `/generate`
     itself returning an error to the caller — a latent inconsistency). Any
     *other* `CAD3DSceneStoreError` is swallowed:
     `scene_state_saved=False`, `scene_state_error=<msg>` is added to the
     response instead of failing the request.
  6. Returns a large payload: `ok, token, scene_token (same value as token),
     scene_state_saved, component_ids, component_count, generation_strategy,
     fallback_used, fallback_reason, fallback_example_name,
     fallback_template_name, ai_planner_attempted, ai_planner_error_type,
     ai_planner_error, example_name, title, units, component_types,
     assumptions, metadata` (+ `scene_state_error` if applicable).
  7. Does **not** touch AutoCAD — confirmed by
     `test_cad3d_generate_does_not_call_autocad_executor`.
- **`GET /api/cad3d/state?limit=20`**: `store.list_records(limit)` →
  `{"ok": True, "records": [_scene_record_summary(r), ...]}`. Summary fields:
  `token, prompt, drawing_style, status, document_name, component_count,
  component_ids, component_types, created_at, updated_at,
  generation_metadata, approval_result` (approval_result reduced to a fixed
  key subset: `ok, executed_count, total_count, pipe_connections_expanded,
  document_name, entity_count_before, entity_count_after`).
- **`GET /api/cad3d/state/latest`**: `store.get_latest()`; 404
  (`CAD3DSceneStoreError`) if store empty.
- **`GET /api/cad3d/state/{token}`**: `store.get(token)`; 404 if missing.
  Detail adds full `scene` and `expanded_scene` to the summary.
- **`POST /api/cad3d/edit`** (`CAD3DEditRequest`) — this is the "chat edit an
  existing 3D scene" endpoint, distinct from `/approve`:
  1. 400 if prompt empty after strip.
  2. `store.get(request.token)` if a token was given, else `store.get_latest()`
     — 404 (`CAD3DSceneStoreError`) if not found.
  3. `plan_cad3d_edit_resilient(prompt, source_scene)` (from
     `src.ai.cad3d_edit_planner`) → `edit_plan`. Then
     `apply_cad3d_edit_plan(source_scene, edit_plan)` (from
     `src.framework.cad3d.scene_editor`). **If `apply_cad3d_edit_plan` raises
     `CAD3DSceneEditError`**, there's an automatic deterministic fallback:
     `deterministic_edit_plan_from_request(prompt, source_scene)` (from
     `src.ai.cad3d_edit_planner`) is used to rebuild `edit_plan` (tagging
     `metadata.planner_strategy = "deterministic_edit_fallback"`,
     `fallback_used = True`, `ai_plan_apply_error = str(apply_exc)`), then
     `apply_cad3d_edit_plan` is retried with the new plan — if *that* also
     raises `CAD3DSceneEditError`, it propagates up to the outer handler → 400.
     Any other exception during planning → 400
     `"CAD3D edit planning failed: {ExcType}: {msg}"`.
  4. `edited_token = uuid4().hex if request.create_new_token else source_token`
     (default `create_new_token=True`, so by default every edit gets a new
     token and the old one is left untouched/still "generated").
  5. `summarize_scene_edit(source_scene, edited_scene)` and
     `extract_scene_component_summary(edited_scene)` computed.
  6. Saved to scene store via `put_generated_scene` (same
     swallow-non-fatal-errors pattern as `/generate`) **and** mirrored into
     `_CAD3D_CACHE[edited_token]` (so the edited scene is also approvable via
     the old `/approve` + `_CAD3D_CACHE` path, not just via `execute=True` on
     this same call).
  7. If `request.execute` is `True`: `expand_pipe_connections(edited_scene)`
     (best-effort, exceptions swallowed → `expanded_scene=None`), then
     `execute_cad3d_scene(edited_scene, target_dwg_path=..., save=...,
     zoom_extents=True)` wrapped in `pythoncom.CoInitialize/CoUninitialize`.
     `AutoCADNotRunningError` → 503; `AutoCAD3DExecutionError` → 500; other →
     500. On success, `store.mark_approved(edited_token, approval_result=...,
     expanded_scene=...)` updates scene status (swallows
     `CAD3DSceneStoreError` into `scene_state_error`, `scene_status` stays
     whatever it was computed as from `execution_result.get("ok")`).
  8. Response: `ok` (derived as `scene_state_saved and (not executed or
     execution succeeded)`), `source_token, edited_token, edit_plan,
     edit_summary, component_count, component_ids, component_types,
     scene_state_saved, scene_state_updated, scene_status, executed,
     execution_result` (+ `scene_state_error` if any).
  9. Audited under `cad3d_edit`.
- **`POST /api/cad3d/approve`** (`CAD3DApproveRequest`) — executes a
  *previously generated (via `/generate`)* scene, looked up only from
  `_CAD3D_CACHE` (not the scene store) — 404 if token missing/expired
  (cache never expires on its own, so "expired" here really only means "never
  existed" or process restarted).
  1. `expand_pipe_connections(scene_data)` best-effort.
  2. `execute_cad3d_scene(scene_data, target_dwg_path, save, zoom_extents=True)`
     wrapped in COM init/uninit. Same error mapping as `/edit`'s execute path
     (503 AutoCADNotRunningError / 500 AutoCAD3DExecutionError / 500 generic).
  3. `store.mark_approved(token=request.token, approval_result=result,
     expanded_scene=...)` — note this uses `get_default_cad3d_scene_store()`
     freshly (not the same `store` variable pattern as `/edit`, though
     functionally equivalent); swallows `CAD3DSceneStoreError`.
  4. Response: `ok, executed=True, token, scene_token, scene_state_updated,
     scene_status, document_name, execution_result, generation_strategy,
     example_name, title, component_count` (+ `scene_state_error`). Audited
     under `cad3d_approve`.
- Contract confirmed extensively by `tests/api/test_cad3d_routes.py` (834
  lines) — covers AI-planner success/fallback/hard-failure, component-example
  fallback path, scene-state persistence, pipe-connection expansion, and the
  deterministic edit operations (`move_component`, delete removing dependent
  pipe connections, dimension update) with concrete before/after coordinate
  assertions (e.g. moving pump P-101 changes `center` from `[300.0, 0.0, 250.0]`
  to `[1300.0, 0.0, 250.0]` for a "move 1000mm to the right" prompt).

### 5.4 `consistency.py` — deterministic P&ID vs. Excel line-list check + optional AI explanation

- Router prefix `/api`, tag `consistency`. Single route:
  **`POST /api/consistency-check`** (`ConsistencyCheckRequest`):
  1. `pythoncom.CoInitialize()` (whole handler wrapped in try/finally
     `CoUninitialize`).
  2. 404 if `pid_path` doesn't exist on disk.
  3. If `excel_path` non-blank: 404 if it doesn't exist. Else:
     `deterministic.find_latest_line_list_excel()` (from
     `src.use_cases.consistency_check`) — a `SystemExit` (not an `Exception`
     subclass caught by normal handlers — must be caught explicitly, which it
     is here) → 404 `"No clean generated line list Excel file was found in outputs/."`.
  4. Builds `report_path = OUTPUT_FOLDER / f"consistency_report_{pid_path.stem}_{timestamp}.xlsx"`.
  5. `deterministic.extract_pid_lines(pid_path)` — opens the DWG via AutoCAD;
     `SystemExit` → 503 `"Could not extract P&ID data. Ensure AutoCAD is running..."`.
  6. `deterministic.read_excel_line_list(excel_path)`, then
     `deterministic.compare_pid_vs_excel(pid_rows, excel_rows)` → `mismatches`.
  7. `deterministic.write_report(report_path=..., pid_path=, excel_path=,
     pid_rows=, excel_rows=, mismatches=)` — writes the `.xlsx` report to
     `outputs/`.
  8. If `request.use_ai_explanation` (default `True`):
     `explain_consistency_mismatches(mismatches)` (from
     `src.ai.consistency_explainer`) — any exception → 502 (note: this failure
     happens **after** the deterministic report is already written to disk,
     so a 502 here still leaves a valid `.xlsx` report file behind, just
     without the paired AI explanation files — the response never tells the
     caller the report file path in this specific failure branch since the
     function raises before reaching the `return`). On success:
     `ai_wrapper.write_ai_outputs(explanation=..., base_name=base_name)` (from
     `src.use_cases.consistency_check_ai`) → writes a `.json` and a `.txt`
     ("manager summary") file, both under the same `base_name`.
  9. Response: `{"ok": True, "result": "PASS"|"FAIL" (based on
     `bool(mismatches)`), "pid_path", "excel_path", "pid_rows": count,
     "excel_rows": count, "mismatch_count", "mismatches", "ai_explanation",
     "report_file": "outputs/<name>", "report_download_url":
     "/api/download/<name>", "ai_explanation_file"/"_download_url",
     "manager_summary_file"/"_download_url"}` — `ai_explanation_file`/
     `manager_summary_file` are `None` when `use_ai_explanation=False`.
  10. Audited under `consistency_check`. Side effects: writes up to 3 files
      into `outputs/` (`.xlsx` report always; `.json`+`.txt` AI outputs
      conditionally); reads a DWG via COM; reads an Excel file.

### 5.5 `line_list.py` — extract line-list block attributes from a P&ID into Excel

- Router prefix `/api`, tag `line-list`. Uses a
  `_temporary_module_settings(module, **overrides)` context manager (comment
  explicitly says: "Phase 7 must wrap the existing module-level constants
  without editing the use case itself") that monkey-patches attributes on the
  imported `src.use_cases.line_list_extract` module object for the duration of
  one request, then restores originals in `finally` — this is how a per-request
  HTTP body can parameterize a use-case module that was originally written
  with hardcoded module-level constants (`DRAWINGS_FOLDER`, `TARGET_FILE`,
  `LINE_BLOCK_NAME`). **This is not concurrency-safe**: if two requests to this
  route overlap, they will race on the same shared module attributes (no lock).
- **`POST /api/line-list-extract`** (`LineListExtractRequest`):
  1. `pythoncom.CoInitialize()`.
  2. 404 if `drawings_folder` doesn't exist.
  3. Inside the `_temporary_module_settings` context (overriding
     `DRAWINGS_FOLDER`, `TARGET_FILE=target_file`, `LINE_BLOCK_NAME=line_block_name`):
     - 404 if `DRAWINGS_FOLDER / TARGET_FILE` doesn't exist.
     - `use_case.OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)`.
     - `use_case.get_acad()` — any exception → 503 `"Cannot connect to AutoCAD: ..."`.
     - `acad.Documents.Open(str(target))`, `time.sleep(0.3)` (fixed settle delay).
     - `use_case.find_blocks_by_name(doc.ModelSpace, LINE_BLOCK_NAME)` →
       iterated into `rows` via `use_case.extract_attributes(block_ref)` +
       `use_case.normalize_row(..., LINE_LIST_COLUMNS)`.
     - If `rows` non-empty: writes `outputs/line_list_<TARGET_FILE stem>_<timestamp>.xlsx`
       via `use_case.write_line_list_xlsx(rows, doc.Name, output_path)`.
     - `doc.Close(False)` in `finally` (discards changes, doesn't save).
  4. Response: `{"ok": True, "rows_extracted": len(rows), "output_file":
     "outputs/<name>" or None, "download_url": "/api/download/<name>" or None,
     "rows": [...]}`. Audited under `line_list_extract`.
- Side effect: opens/closes a DWG document in the live AutoCAD session
  (temporarily — not necessarily the "active" one the user is looking at),
  writes at most one `.xlsx` file.

### 5.6 `pid.py` — component-based P&ID generate/approve

- Router prefix `/api/pid`, tag `pid`. Module-level `_PID_CACHE: dict[str, dict]`
  (in-memory, no TTL/expiry logic at all — unlike sketch/vessel's TTL caches).
- **`POST /api/pid/generate`** (`PIDGenerateRequest`):
  1. 400 if prompt empty after strip.
  2. `plan_and_render_pid_component_scene_resilient(prompt,
     drawing_style=request.drawing_style, allow_template_fallback=True,
     template_first=False)` (from `src.ai.pid_component_planner`).
     `ValueError` → 400; other exception → 502
     `"P&ID component planning failed: ..."`.
  3. Returns dict with keys `component_scene`, `command_sequence`,
     `component_count`, `planner_strategy`, `fallback_used`,
     `fallback_reason`, `template_name`.
  4. `token = uuid4().hex`; cached in `_PID_CACHE[token]` (prompt, drawing_style,
     component_scene, command_sequence, component_count, planner_strategy,
     fallback_used, fallback_reason, template_name, created_at=`datetime.now()`).
  5. Response: `ok, token, prompt, drawing_style, title, drawing_type,
     component_count, command_count, component_scene, summary
     (=command_sequence.summary), assumptions, planner_strategy,
     fallback_used, fallback_reason, template_name`.
  6. Does not execute anything in AutoCAD. Audited under `pid_generate`.
- **`POST /api/pid/approve`** (`PIDApproveRequest`):
  1. 404 if `token` not in `_PID_CACHE` (never expires but also never
     evicted — token stays valid across the whole process lifetime unless
     the process restarts, unlike sketch's 10-minute TTL).
  2. `execute_command_sequence(command_sequence, target_dwg_path=...,
     save=..., zoom_extents=True)` (from `src.framework.commands.executor`)
     wrapped in `pythoncom` init/uninit. `AutoCADNotRunningError` → 503
     (cache entry is **not** removed on this failure, allowing retry — a test,
     `test_pid_approve_autocad_not_running_returns_503`, explicitly asserts
     the token stays in `_PID_CACHE`); other exception → 500.
  3. Response: `ok, executed=True, token, execution_result, component_count,
     command_count, title`. Note: unlike `sketch.py`'s `/approve`, this route
     **never pops the token from the cache even on success** — a `/pid/approve`
     call can be repeated indefinitely with the same token, re-executing the
     same command sequence into AutoCAD each time. Audited under
     `pid_approve`.

### 5.7 `place_symbol.py` — plan + optionally insert a single symbol/block

- Router prefix `/api`, tag `place-symbol`. Single route:
  **`POST /api/place-symbol`** (`PlaceSymbolRequest`):
  1. `pythoncom.CoInitialize()` (try/finally CoUninitialize around the whole body).
  2. 400 if prompt empty after strip.
  3. `plan_symbol_placement(prompt)` (from `src.ai.symbol_planner`) → any
     exception → 502 `"AI planning failed: {ExcType}: {exc}"`.
  4. `connect_to_autocad()` (from `src.use_cases.place_symbol`) — raises
     `SystemExit` on failure (caught explicitly) → 503
     `"AutoCAD is not reachable. Ensure AutoCAD is running with a drawing open."`.
  5. `insert_symbol(doc=doc, spec=planned_spec, dry_run=not request.execute)`
     (from `src.use_cases.place_symbol`) — this is the only route in the
     project that names its dry-run/execute toggle `dry_run` derived as the
     *inverse* of the request's `execute` flag, rather than exposing a
     separate cached-token generate/approve flow; there is no token here at
     all — a single call both plans and (optionally) executes in one shot,
     more like `autocad_edit.py`'s pattern than sketch/pid/vessel's two-step
     pattern.
  6. Response: `{"ok": bool(insert_result["ok"]), "prompt", "planned_spec",
     "insert_result", "connected_to": acad.Caption, "active_drawing": doc.Name}`.
     Audited under `place_symbol` (audit middleware also captures
     `planned_spec` into the job's separate `ai_output` column via
     `_extract_ai_output`).

### 5.8 `sketch.py` — Mode-2 "chat sketch" generate/approve, with verifier + optional chunking

- Router prefix `/api/sketch`, tag `sketch`. Docstring explicitly documents:
  "generated command cache is an in-memory dictionary with a 10-minute TTL...
  tokens are not shared across multiple worker processes and are intentionally
  not persisted." `TOKEN_TTL = timedelta(minutes=10)`. Local models
  `SketchGenerateRequest` (`prompt: str, min_length=1`, `run_verifier: bool =
  True`, `create_preview: bool = True`) and `SketchApproveRequest` (`token: str,
  min_length=1`, `save: bool = True`, `target_dwg_path: str | None = None`).
- `_cleanup_expired_tokens()` runs a linear scan of `_token_cache` at the start
  of `/generate` and inside `_get_sketch_job` (called from `/approve`), evicting
  entries older than `TOKEN_TTL`.
- **`_looks_complex_prompt(prompt)`** — heuristic gate deciding whether to use
  the plain orchestrator or the chunked one. Returns `True` if any of:
  word count > 35; contains `"p&id"` or the standalone word `"pid"`;
  ≥3 of a fixed component-term list (`vessel, header, branch, valve, valves,
  instrument, bubble, pump, tank, pipe, piping, outlet, inlet, nozzle,
  control valve, heat exchanger`) are present; a number-word or digit (2-9,
  or "two".."ten") immediately precedes one of a quantity-target list (`valve,
  valves, branch, branches, instrument, instruments, bubble, bubbles, pump,
  pumps, tank, tanks, pipe, pipes, nozzle, nozzles`); or the prompt contains
  any of `"clean schematic layout"`, `"layout with"`, `"connect"`, `"branches"`.
- **`POST /api/sketch/generate`**:
  1. `_cleanup_expired_tokens()`; 400 if prompt empty after strip.
  2. If `run_verifier` (default True):
     - If `_looks_complex_prompt(prompt)` → `generation_strategy = "chunked"`,
       calls `generate_chunked_verified_command_sequence(prompt, max_chunks=6,
       max_repair_attempts_per_chunk=1, final_repair_attempts=1,
       repair_on_approve_with_notes=False)` (from
       `src.ai.chunked_command_orchestrator`). Extracts `command_sequence,
       verifier_result, verifier_verdict, repair_attempts_used (=
       final_repair_attempts_used), repair_history, task_plan, chunk_count,
       chunk_results, chunk_repair_attempts_used`.
       `ChunkedCommandOrchestrationError` → 502; `ValueError` → 400; other → 502.
     - Else → `generation_strategy = "normal"`, calls
       `generate_verified_command_sequence(prompt, max_repair_attempts=2,
       repair_on_approve_with_notes=False)` (from `src.ai.command_orchestrator`).
       `CommandOrchestrationError` → 502; `ValueError` → 400; other → 502.
       (`task_plan`, `chunk_count`, `chunk_results`,
       `chunk_repair_attempts_used` stay `None`/`[]` in this branch.)
  3. Else (`run_verifier=False`) → `generation_strategy = "direct"`,
     `generate_commands(prompt)` (from `src.ai.command_generator`) with no
     verifier/repair loop at all. `ValueError` → 502 (note: unlike the
     verifier branches, a `ValueError` here is 502 not 400 — inconsistent
     status-code mapping for the same exception type across the two code
     paths of this same endpoint); other exception → 502.
  4. `token = uuid4().hex`. If `request.create_preview` (default True):
     `_preview_path_for(token)` builds
     `outputs/previews/sketch_preview_<timestamp>_<token[:8]>.dxf`, then
     `render_preview_sequence(command_sequence, str(preview_path))` (from
     `src.framework.commands.preview`) — writes a DXF preview file (does not
     touch live AutoCAD). Any exception → 500
     `"Preview generation failed: {ExcType}: {exc}"`.
  5. `_store_sketch_job(...)` caches everything (prompt, command_sequence,
     verifier_result, preview_path, repair_attempts_used, repair_history,
     generation_strategy, task_plan, chunk_count, chunk_results,
     chunk_repair_attempts_used, created_at) under `token`.
  6. Response: `ok, token, summary, estimated_drawing_type, assumptions,
     command_count, verifier_result, verifier_verdict, repair_attempts_used,
     repair_history, generation_strategy, chunk_count,
     chunk_repair_attempts_used, task_plan, preview_path
     ("outputs/previews/...") , preview_download_url
     ("/api/download/previews/...")`. Audited under `sketch_generate`.
- **`POST /api/sketch/approve`** (`SketchApproveRequest`, default
  `save=True` — note this differs from `pid`/`cad3d` approve routes which
  default `save=False`):
  1. `_get_sketch_job(token)` (which also purges expired tokens as a side
     effect) — 404 if missing/expired.
  2. `execute_command_sequence(command_sequence, target_dwg_path=..., save=...)`
     (from `src.framework.commands.executor`, no `zoom_extents` kwarg passed
     here — unlike `pid.py`/`cad3d.py` which explicitly pass
     `zoom_extents=True`; relies on that function's own default) wrapped in
     `pythoncom` init/uninit. `AutoCADNotRunningError` → 503 (token
     **preserved** for retry — confirmed by
     `test_autocad_not_running_returns_503_and_keeps_token_for_retry`); other
     exception → 500.
  3. If `execution_result.get("ok")` is truthy: `_token_cache.pop(token, None)`
     — i.e., a **successful** approve consumes/invalidates the token (one-shot
     semantics), but a failed one (either 503 or a 200-with-`ok:false` executor
     result) leaves it for retry.
  4. Response: `ok, executed(=ok), token, execution_result, verifier_result,
     verifier_verdict (from verifier_result.verdict), preview_download_url`.
     Audited under `sketch_approve`.

### 5.9 `title_block.py` — batch title-block attribute update across matching DWGs

- Router prefix `/api`, tag `title-block`. Same
  `_temporary_module_settings` monkey-patch pattern as `line_list.py` (same
  race-condition caveat), applied to `src.use_cases.update_title_block`.
- **`POST /api/title-block-update`** (`TitleBlockUpdateRequest`):
  1. `pythoncom.CoInitialize()`.
  2. 404 if `drawings_folder` doesn't exist.
  3. Inside `_temporary_module_settings` (overriding `DRAWINGS_FOLDER`,
     `FILE_PATTERN`, `TITLE_BLOCK_NAME`, `UPDATES=dict(request.updates)`,
     `DRY_RUN=request.dry_run`):
     - `files = sorted(DRAWINGS_FOLDER.glob(FILE_PATTERN))` — if empty, returns
       `{"ok": True, "files": [], "summary": _summarize_results([])}` early
       (all-zero summary) without ever touching AutoCAD.
     - `use_case.get_acad().Caption` — any exception → 503
       `"Cannot reach AutoCAD: ..."`.
     - Iterates `files`, sleeping `use_case.PAUSE_BETWEEN_FILES_SEC` between
       files (not before the first), calling
       `use_case.process_one_file(file_path, UPDATES)` per file, collecting
       results.
  4. `_summarize_results(results)` tallies counts by `item["status"]` in
     `{ok, dry_run, error, no_title_block}` plus `total`.
  5. Response: `{"ok": True, "connected_to": acad.Caption, "files": [per-file
     result dicts], "summary": {...}}`. Audited under `title_block_update`.
  - Side effects: potentially mutates and saves multiple DWG files on disk
    (when `dry_run=False`), depending entirely on `process_one_file`'s
    internal behavior (not in this file's scope, but implied by the
    `dry_run`/`no_title_block`/`error` status vocabulary).

### 5.10 `vessel.py` — Phase-21 vessel extract/confirm two-step web workflow

- Router prefix `/api`, tag `vessel`. Docstring: "extraction review cache is an
  in-memory Python dictionary with a 10-minute TTL... not shared across
  multiple worker processes and intentionally not persisted." Same
  `TOKEN_TTL = timedelta(minutes=10)` pattern as `sketch.py`, separate
  `_token_cache` dict (module-local, not shared with sketch's).
- Local models: `VesselExtractRequest` (`prompt: str, min_length=1`);
  `VesselConfirmRequest` (`token: str, min_length=1`, `output_format: str =
  "dwg"`, regex-constrained to `^(dwg|dxf)$`).
- `_dwg_com_context(enabled)` — a conditional context manager: only calls
  `pythoncom.CoInitialize()`/`CoUninitialize()` when `enabled` is True (i.e.
  only for `dwg` output, since `dxf` output presumably doesn't need live
  AutoCAD COM at all).
- **`POST /api/generate-vessel/extract`** (`VesselExtractRequest`):
  1. `_purge_expired_tokens()`; 400 if prompt empty after strip.
  2. `plan_vessel(prompt)` (from `src.ai.vessel_planner`) → any exception →
     502 `"Vessel parameter extraction failed: ..."`.
  3. `token = uuid4().hex`; cached `{extracted, created_at, prompt}`.
  4. Response: `{"ok": True, "token", "expires_in_seconds": 600, "prompt",
     "extracted", "formatted_review": format_for_review(extracted)}`. Audited
     under `generate_vessel_extract` (and `extracted` is surfaced into the
     job's `ai_output` column via `_extract_ai_output` in `main.py`).
- **`POST /api/generate-vessel/confirm`** (`VesselConfirmRequest`) — **this
  route is unusual among all routes in this project: it never raises
  `HTTPException` for domain failures; every failure path returns HTTP 200
  with `"ok": false` in the body** (a deliberate choice, visible in the
  vessel.html UI logic which branches on `data.ok` and `data.error_type`
  rather than HTTP status, except for token-not-found which is a genuine 404):
  1. `_purge_expired_tokens()`; 404 (`HTTPException`, the *only* actual
     HTTP-error case in this route) if `token` not in cache.
  2. `extracted_to_vessel_parameters(extracted)` → `params`;
     `validate_parameters(params)` → `validation_errors`. If any: pops the
     token (invalidates it — caller must re-extract), returns `{"ok": False,
     "error_type": "validation_failed", "message": "...", "errors":
     validation_errors, "extracted": extracted}` — **HTTP 200**.
  3. `_output_path_for(params.tag, output_format)` builds
     `outputs/vessels/<safe_tag>_web_<timestamp>.<dwg|dxf>`
     (`_safe_filename` replaces ` /\\:` with `_`).
  4. `render_vessel(params=, output_path=str(...), output_format=)` (from
     `src.parametric.vessel.render`), run inside `_dwg_com_context(output_format
     == "dwg")`.
  5. If `not result.get("ok")`: pops token, returns `{"ok": False,
     "error_type": "render_failed", "message", "vessel_tag", "format",
     "result", "extracted"}` — HTTP 200.
  6. On success: pops token, returns `{"ok": True, "message", "vessel_tag",
     "format", "path", "output_file" ("outputs/vessels/<name>"),
     "download_url" ("/api/download/vessels/<name>"),
     "dxf_intermediate_file"/"_download_url" (DWG rendering apparently goes
     through a DXF intermediate step — `result.get("dxf_intermediate")`),
     "scale", "sheet", "extracted"}`.
  7. `except AutoCADNotRunningError` (**not raised as HTTPException — caught
     and converted to a normal 200 return**): returns `{"ok": False,
     "error_type": "autocad_not_running", "message": "...", "detail":
     str(exc), "token": request.token, "extracted": extracted}` — note the
     token is **deliberately NOT popped here**, and the token is echoed back
     in the response so vessel.html can let the user retry "Generate Drawing"
     with the same token once AutoCAD is started.
  8. `except Exception` (catch-all): pops the token, returns `{"ok": False,
     "error_type": "generation_failed", "message": f"Vessel generation
     failed: {ExcType}: {exc}", "extracted": extracted}` — HTTP 200.
  9. Audited under `generate_vessel_confirm`. **Because of `_status_from_result`
     in main.py checking `payload.get("ok") is False`, all of these
     "successful HTTP response but ok:false" branches are still correctly
     logged as job `status="error"` in the audit DB**, despite returning HTTP 200
     — this is one of the main reasons `_status_from_result` inspects the
     body instead of trusting the HTTP status code.
  - Side effects: writes a `.dwg` or `.dxf` (plus possibly an intermediate
    `.dxf` when target is `.dwg`) file to `outputs/vessels/`; optionally
    drives AutoCAD COM.

---

## 6. Static UI pages (`src/api/static/*.html`)

All pages are plain HTML+inline-`<style>`+inline-`<script>`, no bundler, no
framework, calling the JSON API with `fetch()`. `/` and `/static/*` both serve
this directory (see §2.4).

### 6.1 `index.html` — landing page
Static list of `<a class="card">` links to: `/title_block.html`,
`/line_list.html`, `/place_symbol.html`, `/consistency.html`, `/vessel.html`,
`/sketch.html`, `/jobs.html`. No JS, no fetch calls. Text still says "Phase 7
thin web wrapper" even though the routes now go well past title-block/line-list
(cad3d, pid, sketch chat, etc. — an outdated blurb). **Note:** there is no
direct link/card anywhere on this landing page to a dedicated PID or CAD3D UI
page — those two workflows are reachable only via the chat interface in
`sketch.html`, not via their own dedicated form page (unlike title_block,
line_list, place_symbol, consistency, vessel which each have a dedicated
simple form page).

### 6.2 `sketch.html` — the actual "chat" interface (drives sketch + PID + CAD3D + edit, all four backends)

Despite its name/route (`/sketch.html`, backing `/api/sketch/*`), this file is
the single multi-workflow chat UI for the whole app: it implements a **full
JavaScript duplicate of `chat_routing.py`'s decision logic** (functions
`normalizePrompt`, `isNewDrawingRequest`, `hasNegated3DIntent`,
`hasExplicit3DIntent`, `hasExplicit2DIntent`, `is3DRequest`, `isPIDRequest`,
`isEditRequest`, `hasCAD3DEditIntent`, `decideChatRoute` — all textually
mirroring the Python regex/keyword lists) and then dispatches the user's chat
message to one of four different backends based on `decideChatRoute(prompt)`:
- `CHAT_ROUTES.CAD3D` (`"cad3d_generate"`) → `handleCAD3DRequest` → `POST
  /api/cad3d/generate` then (on "Build 3D model in AutoCAD" click)
  `buildCAD3DInAutoCAD` → `POST /api/cad3d/approve`.
- `CHAT_ROUTES.CAD3D_EDIT` (`"cad3d_edit"`) → `handleCAD3DEditRequest` → `POST
  /api/cad3d/edit` with `execute: true` directly (no separate approve step —
  the edit-and-build happens in one call here, unlike generate+approve).
  Resolves the source token via `currentCAD3DToken()` (in-memory
  `latestGeneration`/`latestCAD3DToken`, persisted to `localStorage` key
  `autocad_ai_latest_cad3d_token`) or, if none, `fetchLatestCAD3DToken()` →
  `GET /api/cad3d/state/latest`.
- `CHAT_ROUTES.PID` (`"pid_generate"`) → `handlePIDRequest` → `POST
  /api/pid/generate` then (on "Build P&ID in AutoCAD" click)
  `buildPIDInAutoCAD` → `POST /api/pid/approve`.
- `CHAT_ROUTES.EDIT` (`"autocad_edit"`) → `applyLiveEdit` → `POST
  /api/autocad/edit` directly with `auto_execute: true` (single call, no
  build button — the edit is applied immediately on send).
- default `CHAT_ROUTES.SKETCH` (`"sketch_generate"`) → `generatePlan` → `POST
  /api/sketch/generate` (with `run_verifier: true, create_preview: false` —
  **note the chat UI explicitly disables preview generation**, unlike a
  hypothetical direct API caller which gets `create_preview: true` by
  default) then (on "Build in AutoCAD"/"Build Anyway" click) `buildInAutoCAD`
  → `POST /api/sketch/approve` with `save: false, target_dwg_path: null`.
- Also calls `GET /api/cad3d/state/latest` (see above) when resolving CAD3D
  edit context without a cached token.
- **UI states**: sidebar "Recent Chats" (`localStorage` key
  `autocad_ai_recent_sketches`, capped at 20, populated on every
  generate-success across all four workflows, clicking a recent item just
  refills the prompt box, does not resubmit); a chat transcript of
  `.message.{user|assistant|system|error}` bubbles; a "system" status bubble
  shows transient text like "Generating command plan..." /
  "Connecting to AutoCAD...\nExecuting commands...\nZooming..." while awaiting
  each fetch; build buttons show disabled "Building..." labels while in
  flight and re-enable (with "Build Anyway" label if the sketch verifier's
  verdict was `REJECT`) on failure. Errors from any workflow render as a
  plain error bubble via `String(error.message || error)` — thrown `Error`
  messages are constructed per-route (`editApiErrorMessage`,
  `cad3dEditApiErrorMessage`, or generic `errorMessage(data, fallback)` which
  prefers `data.detail` (FastAPI's HTTPException convention) then
  `data.message`, else a hardcoded fallback string).
- `sendPrompt()` also does a full `console.log` trace of every routing
  predicate result before dispatching — clearly a debugging aid left in
  production code (see §7).
- **Uncommitted local diff** (per `git diff`, not yet committed) is
  **purely cosmetic/UX**: adds an `autoGrowPrompt()` function that
  auto-resizes the prompt `<textarea>` height (up to `min(46vh, 520px)`) on
  input/resize/recent-item-click/new-sketch-reset, changes the textarea from
  fixed `max-height: 180px; resize: vertical` to dynamic auto-grow with
  `resize: none`, and adds `min-height: 0` to `.chat` for correct flex
  scrolling. **No routing logic, endpoint URLs, or request/response handling
  changed** — this is a safe, self-contained WIP UI polish, not a functional
  change; it does not desync the JS-routing/Python-routing test parity
  described in §3 since none of the diffed lines fall inside the
  `decideChatRoute`-and-friends block the Node-based parity test extracts.

### 6.3 `jobs.html` — audit log browser
`GET /api/jobs?limit=&use_case=&status=` populates a table (`Timestamp,
Source, Use Case, Status, Duration, Error, View`); each row's "View" link is
`/jobs.html?job_id=<id>`, which on load triggers `GET /api/jobs/{job_id}` and
pretty-prints the full JSON job record into a `<pre>`. Filters: `use_case`
`<select>` (**hardcoded options**: empty/all, `title_block_update`,
`line_list_extract`, `place_symbol`, `consistency_check` — **missing every
newer use_case**: `generate_vessel_extract`, `generate_vessel_confirm`,
`sketch_generate`, `sketch_approve`, `autocad_inspect`, `autocad_edit`,
`pid_generate`, `pid_approve`, `cad3d_generate`, `cad3d_edit`, `cad3d_approve`
— see §7), `status` `<select>` (empty/all, `started`, `ok`, `error`,
`partial`), `limit` `<select>` (25/50/100). No error-state styling beyond
plain text ("Loading...", "No jobs found.", "Job detail not found.").

### 6.4 `consistency.html` — simple form for `/api/consistency-check`
Text inputs for `pid_path` (default `E:\RC-Projects\pid_001.dwg`),
`excel_path` (optional), a checkbox for `use_ai_explanation` (default
checked). Submit → `POST /api/consistency-check`, raw JSON response dumped
into a `<pre>`. No loading spinner beyond the text "Submitting..."; no special
handling of specific error types — any thrown fetch error or non-2xx response
body is just JSON-stringified as-is (including on network failure, which
wraps into `{"ok": false, "error": String(error)}` client-side, distinct from
the server's own error shape).

### 6.5 `line_list.html` — simple form for `/api/line-list-extract`
Inputs: `drawings_folder` (default `E:\RC-Projects`), `target_file` (default
`pid_001.dwg`), `line_block_name` (default `LINE_BLOCK_TEST`). Same
submit/`<pre>`-dump pattern as consistency.html. No download-link rendering
even though the API response includes `download_url` — the raw JSON is shown
but not turned into a clickable link (functional gap vs. e.g. vessel.html
which does render a proper download button).

### 6.6 `place_symbol.html` — simple form for `/api/place-symbol`
Single `<textarea>` prompt (default = the same `DEFAULT_SYMBOL_PROMPT` string
as `schemas.py`), two buttons "Submit (dry-run)" and "Submit (execute)" that
call the same endpoint with `execute: false`/`true` respectively. Same raw
`<pre>` JSON dump pattern, no dedicated success/error UI.

### 6.7 `title_block.html` — simple form for `/api/title-block-update`
Inputs for `drawings_folder`, `file_pattern`, `title_block_name`, and three
flat fields `rev`/`date`/`drawn_by` that get assembled client-side into the
`updates: {REV, DATE, DRAWN_BY}` dict — **this means the UI can only ever send
exactly these three fixed attribute tags**, even though the backend
`TitleBlockUpdateRequest.updates` is a fully generic `dict[str, str]` that
could carry arbitrary tag names (a UI limitation, not a backend one). Two
buttons: "Submit (dry-run)" → `dry_run: true`, "Submit (execute)" → `dry_run:
false`. Same raw `<pre>` JSON dump.

### 6.8 `vessel.html` — dedicated two-step extract/confirm workflow UI (most polished non-chat page)
Explicit state machine via `setState("input"|"review"|"done")` toggling
`.hidden` on three `<section>`s:
- **input state**: prompt `<textarea>` (long default example prompt for
  vessel V-201), "Extract Parameters" button → `POST
  /api/generate-vessel/extract` → on success stores `currentToken` +
  `currentExtracted`, renders `formatted_review` text and an assumptions
  `<ul>`, switches to review state.
- **review state**: shows the extracted-parameter text dump, assumptions
  list, an output-format `<select>` (dwg/dxf, default dwg), "Generate
  Drawing" button → `POST /api/generate-vessel/confirm`, "Edit Prompt" button
  → back to input state (keeping the typed prompt).
- **`generateDrawing()`** response handling explicitly branches on
  `data.error_type`: `"autocad_not_running"` → keeps `currentToken` alive,
  shows the error banner, stays in review state (so the user can just retry
  "Generate Drawing" after starting AutoCAD, matching the backend's decision
  not to pop the token in that case — see §5.10); any other `!data.ok` →
  clears `currentToken`, disables the Generate button, shows error, stays in
  review state (user must click "Edit Prompt" then re-extract since the
  token is dead server-side too).
- **done state**: text summary (`Vessel:`, `Format:`, `Output:`, `Sheet:`,
  `Scale:` lines joined with `\n`), a styled `.download-button` anchor
  pointing at `download_url` with a `download` attribute set to the
  filename — "Generate Another" button resets to input state.
- **Sidebar history**: `loadHistory()` calls `GET /api/jobs?limit=200`,
  filters client-side for `job.use_case` (or legacy `job.job_type`) starting
  with `"generate_vessel_confirm"`, further prefers `source === "api"` entries
  if any exist, slices to 20, renders each with a title (`vessel_tag` from
  `result_data` or `ai_output.extracted.tag`, falling back to `"Vessel"`),
  meta line (`time | FORMAT | status`), and a conditional "Download" link
  (only rendered when `job.status === "ok"` and a `download_url` exists in
  the stored `result_data`).
- Sidebar link: "Full job history" → `/static/jobs.html` (note: uses the
  `/static/` prefix here specifically, whereas every other page's internal
  links use the un-prefixed root path like `/jobs.html` — both work per the
  double-mount in `main.py`, but it's an inconsistency in how links are
  written across pages).

---

## 7. Cross-cutting observations (inconsistencies, dead code, gaps, surprises)

1. **Chat routing logic is duplicated in two languages and must be kept in
   sync by hand.** `src/api/chat_routing.py` (Python) and the inline
   `<script>` in `src/api/static/sketch.html` (JavaScript) implement the same
   keyword/regex decision tree independently. The only thing enforcing parity
   is `tests/api/test_chat_routing.py::test_static_ui_javascript_routing_matches_expected_endpoints`
   and `::test_static_ui_routes_cad3d_edits_when_cad3d_context_exists`, which
   shell out to `node` to execute the extracted JS block and diff its output
   against the Python route decisions for a fixed prompt list — and this test
   **silently skips** (not fails) if `node` isn't on `PATH`
   (`pytest.skip("Node.js is not available...")`), so in a Node-less CI/dev
   environment, a routing-logic drift between the two implementations would
   go completely undetected. Additionally, **`chat_routing.py` itself is
   never imported/called by any FastAPI route** — it functions purely as a
   spec-by-test for what the JS *should* do; the actual live decision is made
   entirely client-side.

2. **The Python and JS versions of CAD3D-edit routing are not equivalent.**
   Python's `has_cad3d_edit_intent(prompt)` (used directly by
   `decide_chat_route`) returns `True` for a component-ID match *or*
   (explicit-3D-intent AND equipment term) — with no notion of "is there
   currently a CAD3D scene in context". The JS's `hasCAD3DEditIntent(text)` is
   structurally similar but is only ever consulted through
   `shouldRouteToCAD3DEdit(text)`, which additionally requires
   `hasCAD3DContext()` (a truthy `latestCAD3DToken`/`latestGeneration`) before
   routing to CAD3D-edit — i.e. the browser will not treat "Move pump P-101
   1000mm to the right" as a CAD3D edit unless the user has generated (or
   built) a CAD3D scene at some point in the current browser session (or has
   a token left over in `localStorage`). The Node-parity tests account for
   this by explicitly seeding `latestGeneration`/`latestCAD3DToken` before
   asserting CAD3D-edit routing (`test_static_ui_routes_cad3d_edits_when_cad3d_context_exists`),
   but `test_chat_routing.py`'s pure-Python assertions for the same prompts
   (e.g. `test_cad3d_component_edit_prompts_route_to_cad3d_edit`) have no such
   context gate — meaning the Python spec is intentionally more permissive
   than the JS implementation for this one dimension. A future agent should
   not assume `decide_chat_route`'s behavior is 1:1 reproducible by calling
   the live chat UI without also faking that context.

3. **`jobs.html`'s use-case filter dropdown is stale.** It only offers
   `title_block_update`, `line_list_extract`, `place_symbol`,
   `consistency_check` — none of `generate_vessel_extract`,
   `generate_vessel_confirm`, `sketch_generate`, `sketch_approve`,
   `autocad_inspect`, `autocad_edit`, `pid_generate`, `pid_approve`,
   `cad3d_generate`, `cad3d_edit`, `cad3d_approve` are selectable, even though
   `AUDIT_ROUTE_MAP` in `main.py` has logged all of them for a while. The
   underlying `/api/jobs?use_case=...` query param works fine for any of these
   values — it's a front-end omission only (the `<select>` is simply missing
   `<option>` elements); a user must know to type a URL like
   `/jobs.html?job_id=...` or otherwise bypass the dropdown to filter on the
   newer use cases.

4. **`index.html`'s landing page has no card for PID or CAD3D workflows.**
   Every other backend feature (title block, line list, place symbol,
   consistency, vessel, sketch chat, job history) has a discoverable link
   from `/`. `/api/pid/*` and `/api/cad3d/*` are reachable only indirectly, by
   typing a 3D- or P&ID-sounding prompt into the sketch chat UI — there is no
   dedicated `pid.html`/`cad3d.html` page, and no link explaining that
   `sketch.html` secretly also handles P&ID and 3D generation. The
   `index.html` body text also still says "Phase 7 thin web wrapper," which
   predates PID/CAD3D/inspect/edit routes entirely (stale copy).

5. **Inconsistent token-cache lifetime/eviction semantics across workflows** —
   worth knowing before assuming any one pattern generalizes:
   - `sketch.py` / `vessel.py`: 10-minute TTL, purged lazily on next
     generate/approve call; **successful** approve pops the token
     (`sketch.py`); vessel's confirm pops the token on *every* terminal
     outcome except `autocad_not_running` (which deliberately keeps it alive
     for retry).
   - `pid.py`: `_PID_CACHE` has **no TTL and no eviction at all** — tokens
     live for the lifetime of the process, and a **successful** `/pid/approve`
     does **not** pop the token either, so the exact same P&ID can be
     re-executed into AutoCAD arbitrarily many times with one token.
   - `cad3d.py`: `_CAD3D_CACHE` (used only by `/approve`) also has no TTL/
     eviction and is never popped on success or failure — same
     replay-forever characteristic as PID. Meanwhile the *separate*
     `CAD3DSceneStore` (used by `/generate`, `/edit`, `/state*`) has its own
     independent lifecycle/status machine (`generated` → `approved`/`failed`)
     that `/approve` doesn't update through the same code path consistency as
     `/edit` does (both call `mark_approved`, just via slightly different
     `store` variable acquisition — functionally fine, just worth noting the
     two routes don't share a helper for this).
   - This means: after a server restart, sketch/vessel tokens are lost
     exactly the same as PID/CAD3D tokens (all four are in-memory only), but
     *while the process is alive*, PID and CAD3D tokens are effectively
     immortal/replayable while sketch tokens expire in 10 minutes and
     self-invalidate on success.

6. **HTTP-status-code inconsistency for the same exception type within one
   endpoint.** In `sketch.py`'s `/generate`, a `ValueError` raised by the
   verified-orchestrator paths (`run_verifier=True`) is mapped to **400**, but
   a `ValueError` raised by the direct `generate_commands(prompt)` path
   (`run_verifier=False`) is mapped to **502** — same exception type, same
   endpoint, different HTTP status depending on a request flag. A caller
   trying to distinguish "bad request" from "upstream/provider failure" by
   status code alone cannot rely on this being stable across that flag.

7. **`vessel.py`'s `/generate-vessel/confirm` deliberately never uses
   `HTTPException` for domain-level failures** (validation failure, render
   failure, AutoCAD-not-running, generic exception) — everything except an
   unknown token returns HTTP 200 with `"ok": false` and an `error_type`
   discriminator. This is the *opposite* convention from every other
   route in this codebase (which raise `HTTPException` with a numeric status
   for AutoCAD-not-running, validation, etc.). A caller that generically
   checks `response.ok`/status code across all these routes (as some naive
   client code might) will silently treat a failed vessel-confirm as
   successful unless it also inspects the JSON body's `ok` field — which the
   audit middleware's `_status_from_result` correctly does, but a
   hand-rolled API client easily might not. `vessel.html`'s own JS is aware
   of this and branches on `data.ok`/`data.error_type` correctly.

8. **`/api/jobs`/`/api/jobs/{job_id}` audit log can silently misreport
   `error_message` for failures that don't use the `detail` key.**
   `_log_wrapped_route_success`'s `error_message` extraction only reads
   `payload.get("detail")` (the FastAPI/HTTPException convention). Routes
   that return their own ad-hoc error shape with `message`/`error_type`
   instead of `detail` on an `ok: false`-but-200 response (chiefly
   `vessel.py`'s confirm route, and to an extent the "issues" branches of
   `autocad_edit`/`sketch`/`pid`/`cad3d` where `ok: false` comes from a
   partially-failed *executor* result rather than a raised exception) will be
   logged with `status="error"` but `error_message: null` — the actual
   human-readable failure text lives only in `result_data.message` /
   `result_data.execution_result.errors`, not in the dedicated
   `error_message` column that `jobs.html`'s table renders as the "Error"
   column. So the jobs table's "Error" column will show blank for many
   `status=error` rows even though a real message is present a level deeper
   in the JSON detail.

9. **`console.log` debugging trace left in production `sketch.html`.**
   `sendPrompt()` unconditionally logs 7 lines (`"Routing message:"`,
   `isNewDrawingRequest`, `is3DRequest`, `isPIDRequest`, `hasCAD3DContext`,
   `hasCAD3DEditIntent`, `shouldRouteToCAD3DEdit`, `isEditRequest`,
   `decideChatRoute`, plus a `"Route selected: X"` line) to the browser
   console on every single chat message sent. Harmless functionally, but
   clearly a debugging leftover; a future agent doing UI cleanup could
   remove or gate it.

10. **`JobResultResponse` in `schemas.py` is unused.** Defined
    (`ok: bool`, `message: str | None`) but no route in `src/api/routes/`
    references it as a `response_model` or return-type annotation anywhere
    found in this scope — looks like a leftover from an earlier, more
    uniform response-shape design that individual routes have since diverged
    from (every route now hand-builds its own ad-hoc response dict with a
    much larger, route-specific field set).

11. **`line_list.py` and `title_block.py`'s `_temporary_module_settings`
    monkey-patching pattern is explicitly flagged by its own comment as a
    workaround** ("Phase 7 must wrap the existing module-level constants
    without editing the use case itself") and is **not concurrency-safe**:
    it mutates shared module-level attributes on `src.use_cases.line_list_extract`
    / `src.use_cases.update_title_block` for the duration of one request, with
    no lock. Two concurrent requests to either of these two endpoints (e.g.
    from two browser tabs, or two API clients) can interleave and clobber
    each other's `DRAWINGS_FOLDER`/`TARGET_FILE`/etc. — likely fine for the
    single-operator local-desktop use case this app is built for, but a
    hazard if this is ever exposed to more than one concurrent caller (the
    same underlying single-process/no-multi-worker assumption is called out
    explicitly in `sketch.py`/`vessel.py`'s own docstrings for their token
    caches, but *not* documented here in `line_list.py`/`title_block.py`).

12. **`_install_audit_wrappers()`'s technique of reassigning
    `route.app = request_response(route.get_route_handler())`** (main.py:200)
    is tightly coupled to FastAPI/Starlette internals (`APIRoute.endpoint`,
    `APIRoute.dependant.call`, `APIRoute.app`, `fastapi.routing.request_response`).
    It works today (confirmed by the whole test suite exercising every
    audited route through `TestClient(app)` and passing), but a FastAPI
    upgrade that changes how `APIRoute` compiles its ASGI callable could
    silently break auditing without breaking anything else observable (the
    routes would still work; only the audit-log side effect would stop firing,
    and there's no test that directly asserts "a job row gets written" — the
    existing route tests mock away `pythoncom`/executors but don't inspect
    `src/logging/jobs.py`'s SQLite state after a call, as far as this scope's
    test files show).

13. **`/api/download/{filename:path}` always serves
    `media_type="application/octet-stream"`** regardless of the actual file
    extension (`.xlsx`, `.dwg`, `.dxf`, `.json`, `.txt`), meaning browsers
    will always prompt a raw download rather than attempting to open/preview
    supported types inline — consistent behavior, but notably `vessel.html`
    and `jobs.html`'s vessel-history download links rely on the `download`
    attribute (not content-type sniffing) to give the saved file a sensible
    name, which does work correctly.

14. **`sketch.html`'s uncommitted diff (`git diff src/api/static/sketch.html`)
    is purely a textarea auto-grow UX change** (see §6.2) — confirmed by
    inspecting the full diff: no endpoint URLs, request bodies, or routing
    functions were touched. It is safe to treat the working tree's
    `sketch.html` as functionally identical to the last commit
    (`6a365fd`) for anything routing- or API-contract-related; only visual
    textarea-resize behavior differs.

15. **Two untracked files at the repo root** (`setup-and-start.ps1`,
    `start-autocad-ai.bat`, per the git status snapshot) are outside this
    scope (`src/api/`) but are presumably how this app is normally launched
    on Windows — not read as part of this analysis, flagged only for
    completeness since they appeared in the git status handed to this task.

---

## 8. Quick file index (absolute paths)

- `F:\RC-Projects\autocad-ai\autocad-ai\src\api\main.py`
- `F:\RC-Projects\autocad-ai\autocad-ai\src\api\chat_routing.py`
- `F:\RC-Projects\autocad-ai\autocad-ai\src\api\schemas.py`
- `F:\RC-Projects\autocad-ai\autocad-ai\src\api\routes\autocad_edit.py`
- `F:\RC-Projects\autocad-ai\autocad-ai\src\api\routes\autocad_inspect.py`
- `F:\RC-Projects\autocad-ai\autocad-ai\src\api\routes\cad3d.py`
- `F:\RC-Projects\autocad-ai\autocad-ai\src\api\routes\consistency.py`
- `F:\RC-Projects\autocad-ai\autocad-ai\src\api\routes\line_list.py`
- `F:\RC-Projects\autocad-ai\autocad-ai\src\api\routes\pid.py`
- `F:\RC-Projects\autocad-ai\autocad-ai\src\api\routes\place_symbol.py`
- `F:\RC-Projects\autocad-ai\autocad-ai\src\api\routes\sketch.py`
- `F:\RC-Projects\autocad-ai\autocad-ai\src\api\routes\title_block.py`
- `F:\RC-Projects\autocad-ai\autocad-ai\src\api\routes\vessel.py`
- `F:\RC-Projects\autocad-ai\autocad-ai\src\api\static\index.html`
- `F:\RC-Projects\autocad-ai\autocad-ai\src\api\static\sketch.html` (uncommitted local diff, cosmetic only)
- `F:\RC-Projects\autocad-ai\autocad-ai\src\api\static\jobs.html`
- `F:\RC-Projects\autocad-ai\autocad-ai\src\api\static\consistency.html`
- `F:\RC-Projects\autocad-ai\autocad-ai\src\api\static\line_list.html`
- `F:\RC-Projects\autocad-ai\autocad-ai\src\api\static\place_symbol.html`
- `F:\RC-Projects\autocad-ai\autocad-ai\src\api\static\title_block.html`
- `F:\RC-Projects\autocad-ai\autocad-ai\src\api\static\vessel.html`
- `F:\RC-Projects\autocad-ai\autocad-ai\src\logging\jobs.py` (referenced by main.py; `log_job_start`, `log_job_end`, `list_recent_jobs`, `get_job`)
- Tests read for contract confirmation: `tests\api\test_autocad_edit_routes.py`,
  `test_autocad_inspect_routes.py`, `test_cad3d_routes.py`,
  `test_chat_routing.py`, `test_pid_routes.py`, `test_sketch_routes.py`

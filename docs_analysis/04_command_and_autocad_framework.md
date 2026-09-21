# AutoCAD AI Automation — Command & AutoCAD Framework (Deep Dive)

Scope of this document: the generic command execution framework
(`src/framework/commands/*`), the read-only AutoCAD inspector
(`src/framework/autocad/inspector.py`), and the top-level AutoCAD
client/backup helpers (`src/autocad_client.py`, `src/backup.py`). This is
written so a future agent never needs to re-read the source files listed
below to work in this area.

Files covered (all read in full):
- `src/framework/commands/schema.py`
- `src/framework/commands/executor.py`
- `src/framework/commands/preview.py`
- `src/framework/commands/edit_schema.py`
- `src/framework/commands/edit_executor.py`
- `src/framework/commands/planning_schema.py`
- `src/framework/commands/verification_schema.py`
- `src/framework/autocad/inspector.py`
- `src/autocad_client.py`
- `src/backup.py`
- Plus the mock helper `src/parametric/vessel/dwg_export.py` (not in original
  scope, but it is the actual COM-connection dependency for almost every file
  above — see section 6).
- All 8 test files under `tests/framework/`.

---

## 1. Role in the system

This is the **deterministic execution core** of AutoCAD AI Automation. AI
modules under `src/ai/*` produce JSON ("Mode 2" command sequences, live edit
plans, chunked drawing plans, verifier verdicts) from LLM calls; none of that
AI-facing code is allowed to touch AutoCAD directly. Everything in
`src/framework/commands/` and `src/framework/autocad/` is the layer that (a)
validates that JSON against a strict `jsonschema` `Draft7Validator` schema, and
(b) actually turns validated commands into `win32com.client` COM calls against
a live, already-running `AutoCAD.Application` instance (`ModelSpace.AddLine`,
`ModelSpace.AddCircle`, `Layers.Add`, `HandleToObject().Delete()`, etc.), or
alternatively renders the same JSON into a throwaway DXF preview file using
`ezdxf` (no AutoCAD needed) so a human/AI can sanity-check geometry before it
touches the real drawing. `src/framework/autocad/inspector.py` is the
read-only counterpart: it walks `ModelSpace` on the live document and returns
a JSON snapshot of entities, used both for verification/edit-planning context
and for the `/api/autocad/inspect` route. `src/autocad_client.py` is a
mostly-dead legacy thin wrapper (see section 6); the actual COM plumbing all
of this framework relies on lives in `src/parametric/vessel/dwg_export.py`.
`src/backup.py` is a tiny, standalone utility that copies a `.dwg` file into a
timestamped folder before a use case mutates it — it is not wired into the
generic executor/edit_executor, only into `src/use_cases/update_title_block.py`.

Every module in this doc's scope explicitly disclaims doing more than its one
job — the docstrings at the top of each file say things like "does not call
AI, AutoCAD, API routes, or rendering code" (schema.py) — this is a
deliberate phase-by-phase architecture (docstrings reference "Phase 23.1",
"Phase 27.3", "Phase 28.4A" as the incremental build order).

---

## 2. Command schema

All four schema modules use **`jsonschema.Draft7Validator`** as the
validation mechanism (`from jsonschema import Draft7Validator`), built once
at module import time as a private `_VALIDATOR`, then driven through
`_VALIDATOR.iter_errors(data)`. Every module sorts errors by
`(absolute_path, message)` and formats them into a human-readable
`"root.path[index]: message"` string via a local `_format_path`/`_format_error`
pair (duplicated near-identically in all four files — see section 9 for the
duplication note). Every schema module exposes the same two-function public
contract: `validate_<thing>(data) -> list[str]` (empty list = valid) and
`is_valid_<thing>(data) -> bool`.

### 2.1 `schema.py` — `COMMAND_SCHEMA` (`COMMAND_SCHEMA_VERSION = "1.0"`)

Top-level object, `additionalProperties: False`, required keys:
`schema_version` (must equal the `const` `"1.0"`), `summary` (non-empty
string), `assumptions` (array of strings), `commands` (array, `minItems: 1`).
Optional: `estimated_drawing_type` (non-empty string).

`commands` items are validated with a base shape
(`required: ["command"]`, `command` must be one of the enum
`_COMMAND_TYPES = ["LAYER", "LINE", "CIRCLE", "ARC", "ELLIPSE", "POLYLINE", "TEXT", "INSERT", "DIM_LINEAR"]`)
plus a chain of 9 `allOf`/`if`/`then` conditionals, one per command type, each
`then`-referencing a `#/definitions/<type>_command` sub-schema. Every
per-type definition sets `additionalProperties: False`, so unknown fields on
a command (e.g. `"width": 2` on a LINE) fail validation
(`test_extra_unexpected_property_fails`).

Shared building blocks (`definitions`):
- `coordinate`: `array` of exactly 2 numbers (`minItems`/`maxItems: 2`) — always
  **2D** `[x, y]`, never 3D, at the schema level (Z is always synthesized as
  0.0 downstream).
- `common_optional` (declared but not actually referenced by any command
  definition — each definition inlines `layer`/`comment` itself instead —
  dead code, see section 9): `layer` (string, `minLength: 1`), `comment`
  (plain string, no length constraint).

Per-command exact field shapes:

| command | required | optional | notable constraints |
|---|---|---|---|
| `LAYER` | `command`, `layer_name` | `color`, `linetype` | `color`: integer 1–255; `layer_name`: non-empty string |
| `LINE` | `command`, `from`, `to` | `layer`, `comment` | `from`/`to`: `coordinate` |
| `CIRCLE` | `command`, `center`, `radius` | `layer`, `comment` | `radius`: number, `exclusiveMinimum: 0` |
| `ARC` | `command`, `center`, `radius`, `start_angle_degrees`, `end_angle_degrees` | `layer`, `comment` | `radius` exclusiveMinimum 0; angles unconstrained numbers (degrees) |
| `ELLIPSE` | `command`, `center`, `major_axis_endpoint`, `ratio` | `start_angle_degrees`, `end_angle_degrees`, `layer`, `comment` | `ratio`: number 0.01–1.0 |
| `POLYLINE` | `command`, `points` | `closed` (boolean), `layer`, `comment` | `points`: array of `coordinate`, `minItems: 2` |
| `TEXT` | `command`, `text`, `position` | `height`, `rotation_degrees`, `layer`, `comment` | `text`: non-empty string; `height`: exclusiveMinimum 0 |
| `INSERT` | `command`, `block_name`, `position` | `scale`, `rotation_degrees`, `layer`, `comment` | `block_name`: non-empty string; `scale`: exclusiveMinimum 0 |
| `DIM_LINEAR` | `command`, `from`, `to`, `dim_line_position` | `text_override`, `layer`, `comment` | all three points are `coordinate` |

`_format_error` special-cases the `enum` validator on the `command` field to
produce a friendlier message: `"root.commands[N]: unknown command type 'X'.
Allowed command types: LAYER, LINE, CIRCLE, ARC, ELLIPSE, POLYLINE, TEXT,
INSERT, DIM_LINEAR."` — all other errors fall back to
`jsonschema`'s raw `error.message`.

Representative examples (from tests / this doc):

```json
// Valid LINE command inside a sequence
{
  "command": "LINE",
  "from": [0, 0],
  "to": [100, 0],
  "layer": "OBJECT",
  "comment": "baseline"
}
```

```json
// Valid CIRCLE + LAYER sequence (whole top-level object)
{
  "schema_version": "1.0",
  "summary": "Draw a circle on layer TEST.",
  "estimated_drawing_type": "test",
  "assumptions": [],
  "commands": [
    {"command": "LAYER", "layer_name": "TEST", "color": 3},
    {"command": "CIRCLE", "center": [0, 0], "radius": 50, "layer": "TEST"}
  ]
}
```

```json
// Valid DIM_LINEAR command
{
  "command": "DIM_LINEAR",
  "from": [0, 0],
  "to": [100, 0],
  "dim_line_position": [50, 20],
  "text_override": "100",
  "layer": "DIMENSION"
}
```

### 2.2 `edit_schema.py` — `EDIT_PLAN_SCHEMA` (`EDIT_SCHEMA_VERSION = COMMAND_SCHEMA_VERSION` = `"1.0"`)

Reuses `COMMAND_SCHEMA` rather than redefining command shapes: it does
`commands_schema = deepcopy(COMMAND_SCHEMA["properties"]["commands"])` then
sets `commands_schema["minItems"] = 0` (edit plans may add zero new
entities), and copies `COMMAND_SCHEMA["definitions"]` verbatim via
`deepcopy` for the `$ref`s to resolve. `_COMMAND_TYPES` here is pulled live
from `COMMAND_SCHEMA["properties"]["commands"]["items"]["properties"]["command"]["enum"]`
rather than being redeclared, so the two schemas cannot drift on allowed
command types.

Top-level object, `additionalProperties: False`, required:
`schema_version` (const `"1.0"`), `edit_intent` (non-empty string), `summary`
(non-empty string), `assumptions` (array of strings), `delete_handles`
(array of non-empty strings — AutoCAD entity handles), `commands` (array,
`minItems: 0`, same per-type shapes as `COMMAND_SCHEMA`). Optional:
`target_description` (non-empty string).

Beyond plain JSON-Schema validation, `validate_edit_plan` adds one **custom,
non-schema business rule** via `_has_edit_action(data)`: if both
`delete_handles` and `commands` are empty, it appends the extra message
`"root: at least one of delete_handles or commands must be non-empty."` even
if the schema itself passed — a no-op edit plan is otherwise
schema-valid but is rejected by this hand-written check
(`test_both_delete_handles_and_commands_empty_fails`).

Representative examples:

```json
// Delete-only edit plan
{
  "schema_version": "1.0",
  "edit_intent": "Delete the center circle.",
  "summary": "Delete one circle entity from the active drawing.",
  "target_description": "Center circle on layer CENTERLINE.",
  "assumptions": [],
  "delete_handles": ["26C"],
  "commands": []
}
```

```json
// Replace-style edit (delete old text, add moved text) — the pattern used
// to represent "move an entity" since there is no MOVE command
{
  "schema_version": "1.0",
  "edit_intent": "Move the title text upward.",
  "summary": "Delete old title text and add replacement text 150mm higher.",
  "assumptions": ["Moving text is represented as delete old entity plus add new text."],
  "delete_handles": ["26D"],
  "commands": [
    {"command": "TEXT", "text": "My Drawing", "position": [0, 800], "height": 80, "layer": "TEXT"}
  ]
}
```

### 2.3 `planning_schema.py` — `DRAWING_TASK_PLAN_SCHEMA` (`PLANNING_SCHEMA_VERSION = "1.0"`, independent constant, not shared with COMMAND_SCHEMA_VERSION)

This is a "chunked drawing task plan" — a plan for splitting a big drawing
into up to 12 named work chunks (presumably each chunk later becomes its own
LLM call producing a `COMMAND_SCHEMA` sequence — consumed by
`src/ai/drawing_task_planner.py` and `src/ai/chunked_command_orchestrator.py`,
outside this doc's scope but confirmed by grep).

Top-level required: `schema_version` (const `"1.0"`), `drawing_type`
(non-empty string), `summary` (non-empty string), `assumptions` (array of
strings), `chunks` (array, `minItems: 1`, `maxItems: 12`). Optional:
`layout_strategy` (non-empty string). `additionalProperties: False` at top
level.

Each chunk (`additionalProperties: False`), required: `chunk_id` (non-empty
string matching `^[A-Za-z0-9_-]+$`), `title` (non-empty string), `goal`
(non-empty string), `priority` (integer, `minimum: 1`), `expected_elements`
(array of non-empty strings). Optional: `layout_hint` (non-empty string).

`validate_drawing_task_plan` has no custom business-rule layer beyond the
schema (unlike `edit_schema.py`).

Representative example:

```json
{
  "schema_version": "1.0",
  "drawing_type": "P&ID-style sketch",
  "summary": "Central vessel with piping, valves, instruments, and labels.",
  "assumptions": ["Used a clean orthogonal schematic layout."],
  "layout_strategy": "Place vessel centrally, route piping orthogonally around it.",
  "chunks": [
    {
      "chunk_id": "equipment",
      "title": "Central vessel",
      "goal": "Draw the central vertical vessel and vessel label.",
      "priority": 1,
      "expected_elements": ["vertical vessel", "vessel tag"],
      "layout_hint": "Place vessel at the center of the drawing."
    }
  ]
}
```

### 2.4 `verification_schema.py` — `VERIFICATION_SCHEMA` (`VERIFICATION_SCHEMA_VERSION = "1.0"`, also independent)

This is the schema for an AI "verifier" pass's structured verdict on a
generated `COMMAND_SCHEMA` sequence (consumed by `src/ai/command_verifier.py`,
outside this doc's scope). Verdict meanings are documented in the module
docstring: `APPROVE` (no meaningful issues), `APPROVE_WITH_NOTES` (minor
concerns, engineer should review), `REJECT` (blocker issues — sequence should
not execute without correction).

Top-level required: `schema_version` (const `"1.0"`), `verdict` (enum
`APPROVE`/`APPROVE_WITH_NOTES`/`REJECT`), `summary` (non-empty string),
`issues` (array of `#/definitions/issue`), `command_annotations` (array of
`#/definitions/command_annotation`). `additionalProperties: False`.

`issue` definition — required: `severity` (enum `BLOCKER`/`WARNING`/`INFO`),
`description` (non-empty string); optional: `command_index` (integer,
`minimum: 0`), `suggested_fix` (non-empty string). `additionalProperties:
False`.

`command_annotation` definition — required: `command_index` (integer,
`minimum: 0`), `annotation` (non-empty string), `concern_level` (enum
`NONE`/`MINOR`/`MAJOR`). `additionalProperties: False`.

No custom business-rule layer (pure schema validation) — note there is no
rule enforcing "REJECT implies at least one BLOCKER issue" or similar
cross-field consistency; that is left entirely to the LLM's own judgment
(see section 9, risk notes).

Representative example:

```json
{
  "schema_version": "1.0",
  "verdict": "APPROVE_WITH_NOTES",
  "summary": "The sequence can execute, but one text label may overlap nearby geometry.",
  "issues": [
    {
      "severity": "WARNING",
      "description": "Text label may overlap the rectangle border.",
      "command_index": 5,
      "suggested_fix": "Move the text label upward by 100 mm."
    }
  ],
  "command_annotations": [
    {
      "command_index": 5,
      "annotation": "Possible text overlap near upper border.",
      "concern_level": "MINOR"
    }
  ]
}
```

---

## 3. Executors

### 3.1 `executor.py` — `execute_commands` / `execute_command_sequence`

**Dependencies**: imports `AutoCADNotRunningError`, `_com_retry`, `_get_acad`
from `src.parametric.vessel.dwg_export` (see section 6 for why — this is a
cross-module reuse of a helper module that was originally written for DXF→DWG
conversion, not a dedicated "AutoCAD connection" module).

**`CommandExecutionError`** — the module's own exception, raised for: empty
`commands` list, unsupported command type, and (via
`execute_command_sequence`) schema validation failure. It is **not** raised
for individual per-command COM failures during execution — those are
collected, not thrown (see below).

**COM point/array helpers**:
- `acad_point(x, y, z=0.0)` — builds a `win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, (x, y, z))`, i.e. a COM-safe 3D double array AutoCAD expects for point args. Falls back to a plain `(x, y, z)` tuple if `pythoncom`/`win32com` import fails (so the module is still importable, and partially testable, on a machine without pywin32 — tests monkeypatch this function anyway).
- `_acad_double_array(values)` — same VARIANT wrapping for flat arrays of doubles (used for polyline vertex lists).
- `_point_from_pair(pair)` — `acad_point(pair[0], pair[1])`; note **Z is always 0.0** for every 2D input coordinate from the schema — this framework only ever draws in the XY plane at Z=0.
- `_set_com_attr(obj, name, value, description)` — wraps `setattr(obj, name, value)` in `_com_retry` for retry-on-busy semantics.

**Layer handling** — `ensure_layer(layers, layer_name, known_layers=None)`:
returns `None` immediately if `layer_name` is falsy or literally `"0"` (the
AutoCAD default layer is never explicitly created/touched). If a
`known_layers` cache set is supplied and already contains the name, it tries
`layers.Item(layer_name)` directly (skip-the-negative-lookup optimization);
otherwise it tries `layers.Item(layer_name)` and on any exception falls back
to `layers.Add(layer_name)` (get-or-create pattern), then records the name in
`known_layers`. `_prepare_layer(command, layers, known_layers)` is the
per-geometry-command convenience that calls `ensure_layer` only when a
non-`"0"` `layer` field is present, and `_apply_entity_layer(entity,
layer_name)` sets `entity.Layer = layer_name` afterward via `_set_com_attr`.
`known_layers` is a single `set[str]` created once per `execute_commands`
call and threaded through every command — it is a per-batch cache, not
persisted across calls.

**Per-command-type handler functions** (each wraps its literal AutoCAD COM
call(s) in `_com_retry(lambda: ..., "<description>")`, i.e. retries on
COM "busy" errors, see section 6):

| Command | Handler | COM call |
|---|---|---|
| `LAYER` | `_execute_layer` | `layers.Item`/`layers.Add`, then optional `layer.Color = int(...)`, optional `layer.Linetype = ...` (wrapped in its own inner `try/except: pass` — a linetype failure is silently swallowed and does **not** get recorded as a per-command error) |
| `LINE` | `_execute_line` | `msp.AddLine(point_from, point_to)` |
| `CIRCLE` | `_execute_circle` | `msp.AddCircle(point_center, float(radius))` |
| `ARC` | `_execute_arc` | `msp.AddArc(point_center, float(radius), math.radians(start), math.radians(end))` — **AutoCAD's `AddArc` takes radians; the schema is degrees, so this handler converts.** |
| `ELLIPSE` | `_execute_ellipse` | `msp.AddEllipse(point_center, point_major_axis_endpoint, float(ratio))`, then optionally sets `entity.StartAngle`/`entity.EndAngle` (radians) if present |
| `POLYLINE` | `_execute_polyline` | Prefers `msp.AddLightWeightPolyline(flat_2d_array)` (checked via `hasattr(msp, "AddLightWeightPolyline")`); falls back to `msp.AddPolyline(flat_3d_array_with_z=0)` if that method doesn't exist on the COM object. Sets `entity.Closed = True` if `command.get("closed") is True`. |
| `TEXT` | `_execute_text` | `msp.AddText(text, point_position, height)` where `height = float(command.get("height", 100.0))` — **default text height is 100 (drawing units), not the schema's implicit default** — then optional `entity.Rotation = radians(...)` |
| `INSERT` | `_execute_insert` | `msp.InsertBlock(point_position, block_name, x_scale, y_scale, z_scale, rotation_radians)` — uses the **same** `scale` value for X/Y/Z (uniform scale only; schema has no per-axis scale). Defaults: `scale=1.0`, `rotation_degrees=0.0`. |
| `DIM_LINEAR` | `_execute_dim_linear` | `msp.AddDimAligned(point_from, point_to, point_dim_line_position)` — note this is an **aligned** dimension COM call despite the schema/command name being `DIM_LINEAR`; then optionally sets `entity.TextOverride` |

Dispatch table `_COMMAND_HANDLERS: dict[str, Callable]` maps command-type
strings to these handler functions; `_execute_one_command` looks up the
handler and raises `CommandExecutionError(f"Unsupported command type: {type}")`
if missing (defensive — the schema validator should already have rejected
unknown types before execution, but `execute_commands` itself does **not**
re-validate, so a caller that skips `execute_command_sequence` and calls
`execute_commands` directly with unvalidated data can hit this path).

**`execute_commands(commands, target_dwg_path=None, save=True, continue_on_error=True, zoom_extents=True) -> dict`** algorithm:
1. Reject if `commands` is not a non-empty list → `CommandExecutionError`.
2. `acad = _get_acad()` — connect to the running `AutoCAD.Application` (raises `AutoCADNotRunningError` if AutoCAD isn't open).
3. If `target_dwg_path` given: `acad.Documents.Open(str(target_dwg_path))` to open/switch to that drawing; else `_active_document(acad)` which reads `acad.ActiveDocument` and raises `CommandExecutionError("No active AutoCAD document is available.")` if it's missing or `None`.
4. Grab `msp = doc.ModelSpace`, `layers = doc.Layers`, a fresh `known_layers: set[str] = set()`.
5. Snapshot `document_name`, `dwg_path`, `entity_count_before` (via `_safe_modelspace_count`, which tries `int(msp.Count)` then falls back to `len(msp)`, returning `None` if both fail — never raises).
6. **Main loop**: for each `(index, command)` in `commands`, call `_execute_one_command`. On success, `executed_count += 1`. On **any** `Exception`, append `{"command_index": index, "command": command, "error": f"{type(exc).__name__}: {exc}"}` to `errors` — **this is best-effort/partial execution, not all-or-nothing**: one bad command does not roll back previously-executed commands. If `continue_on_error` is `False`, the loop `break`s immediately after the first error (remaining commands in the batch are simply never attempted — no rollback of already-applied ones either).
7. If `save` is `True`: `doc.Save()` wrapped in `try/except`; a save failure is appended to `errors` as `{"command_index": None, "command": "SAVE", "error": ...}` (note: mixed-type `command` field — a dict for real command errors, the literal string `"SAVE"` for this one — see section 9).
8. Snapshot `entity_count_after`.
9. If `zoom_extents` is `True`: call `_activate_regen_zoom(acad, doc)`, which does `doc.Activate()` → `doc.Regen(1)` → `acad.ZoomExtents()` in sequence inside one `try/except`; any failure there is captured as `zoom_error` and `zoom_extents_called=False`, but **this never adds to `errors` and never flips `ok` to `False`** — a zoom/regen failure is cosmetic-only and does not affect the reported success of the drawing operation itself (explicitly tested: `test_zoom_failure_does_not_make_ok_false_when_commands_succeeded`).
10. Returns a dict: `{"ok": not errors, "executed_count", "total_count": len(commands), "errors": [...], "dwg_path", "document_name", "entity_count_before", "entity_count_after", "zoom_extents_called", "zoom_error"}`.

**`execute_command_sequence(command_sequence, target_dwg_path=None, save=True, continue_on_error=True, zoom_extents=True) -> dict`**: calls
`src.framework.commands.schema.validate_command_sequence` (imported lazily
inside the function body, presumably to avoid a module-level circular import
since `schema.py` doesn't import `executor.py` but this keeps them decoupled),
and raises `CommandExecutionError("Invalid command sequence:\n- err1\n- err2...")`
if any validation errors exist; otherwise delegates straight to
`execute_commands(command_sequence["commands"], ...)`. This is the
schema-checked entry point that API routes actually call — `execute_commands`
itself is unchecked and lower-level.

### 3.2 `edit_executor.py` — `execute_edit_plan`

**Dependencies**: same `AutoCADNotRunningError`/`_com_retry`/`_get_acad` from
`dwg_export`, plus `execute_commands` (not `execute_command_sequence`) from
`executor.py` — reused for the "add new geometry" half of an edit plan.

**`EditExecutionError`** — the module's own exception (separate from
`CommandExecutionError`), raised for: schema validation failure only. Like
`executor.py`, individual delete/add failures during execution are captured
in the result, not raised.

**`execute_edit_plan(edit_plan, target_dwg_path=None, save=True, continue_on_error=True, zoom_extents=True) -> dict`** algorithm:
1. `validate_edit_plan(edit_plan)` — if errors, raise `EditExecutionError("Invalid edit plan:\n...")`.
2. `acad = _get_acad()`; `doc = _get_document(acad, target_dwg_path)` (same open-or-use-active pattern as `executor.py`, raising `EditExecutionError("No active AutoCAD document is available.")` when there's no active doc and no `target_dwg_path`).
3. Snapshot `msp`, `document_name`, `dwg_path`, `entity_count_before`.
4. **Delete phase**: for each `handle` in `edit_plan.get("delete_handles", [])`: `_delete_entity_by_handle(doc, handle)` = `entity = doc.HandleToObject(handle)` then `entity.Delete()` (both `_com_retry`-wrapped). Success increments `deleted_count`. On exception, appends `{"type": "delete", "handle": handle, "error": "<ExcType>: <msg>"}` to `errors`. If `continue_on_error` is `False`, sets `additions_blocked = True` and breaks the delete loop immediately — **this is the one place where a failure in one phase explicitly gates the next phase**: a delete failure with `continue_on_error=False` skips the entire add phase (tested: `test_delete_failure_stops_additions_when_continue_on_error_false`).
5. **Add phase**: if `commands` is non-empty and `additions_blocked` is `False`: calls `execute_commands(commands, target_dwg_path=None, save=False, continue_on_error=continue_on_error, zoom_extents=False)` — note it always passes `target_dwg_path=None` (the document is already open/selected) and always `save=False`/`zoom_extents=False` at this inner call (save/zoom happen once, at the edit-plan level, not per-phase). The nested result's `errors` list is normalized via `_normalize_add_errors` — each entry gets `{"type": "add", ...original fields...}` merged in (or, if the error is not a dict, wrapped as `{"type": "add", "error": str(error)}`); if the nested `execute_commands` result had `ok=False` but produced no `errors` list at all, a synthetic `{"type": "add", "error": "Addition command execution failed."}` is appended as a safety net. If calling `execute_commands` itself raises (e.g. `CommandExecutionError` for an empty list — though that can't happen here since it's gated on `commands` being truthy), that exception is caught and turned into `{"type": "add", "error": "<ExcType>: <msg>"}` too.
6. **Save phase**: if `save`, `doc.Save()`, with failures appended as `{"type": "save", "error": ...}`.
7. Snapshot `entity_count_after`; if `zoom_extents`, run the same `_activate_regen_zoom` as `executor.py` (zoom failures again never affect `ok`).
8. Returns: `{"ok": not errors, "edit_intent", "summary", "deleted_count", "delete_count": len(delete_handles), "added_executed_count", "added_total_count", "errors": [...], "document_name", "dwg_path", "entity_count_before", "entity_count_after", "zoom_extents_called", "zoom_error"}`.

Every error dict in the final `errors` list is tagged with a `"type"` field
(`"delete"`, `"add"`, or `"save"`) so a caller can tell which phase produced
it — this is the one place in the executor code that gives errors a
structured, filterable shape (contrast with `executor.py`'s flatter, untyped
error dicts).

---

## 4. `preview.py` — what "preview" means here

A **preview is a DXF file rendered by the `ezdxf` library**, entirely
independent of AutoCAD/COM — it is a pure, local, dependency-light dry run
used to visually sanity-check a command sequence's geometry (e.g., opened in
a DXF viewer, or converted to an image elsewhere) before committing it to the
live AutoCAD document. There is no AutoCAD COM involvement, no image
rendering (no PNG/SVG), and no "diff against the live drawing" — it is a
from-scratch synthetic drawing built only from the JSON commands.

**`render_preview(commands, output_path) -> str`** algorithm:
1. Reject empty/non-list `commands` → `PreviewRenderError`.
2. `doc = ezdxf.new(dxfversion="R2010", setup=True)`; `_set_units_to_mm(doc)` tries `doc.units = ezdxf.units.MM` and `doc.header["$INSUNITS"] = 4`, each independently swallowed on failure — any failure to create/configure the DXF doc raises `PreviewRenderError`.
3. `msp = doc.modelspace()`.
4. For each `(index, command)`: dispatches via a `_RENDERERS` dict keyed by command type (mirrors `_COMMAND_HANDLERS` in `executor.py` but calls `ezdxf` APIs instead of COM):
   - `LAYER` → `_render_layer`/`ensure_preview_layer(doc, name, color, linetype)`: creates the DXF layer if absent (`doc.layers.add`/`doc.layers.get`), sets `layer.color`/`layer.dxf.linetype` (linetype set failure swallowed).
   - `LINE` → `msp.add_line(point2_from, point2_to, dxfattribs={"layer": ...})`.
   - `CIRCLE` → `msp.add_circle(point2_center, radius, dxfattribs=...)`.
   - `ARC` → `msp.add_arc(point2_center, radius, start_degrees, end_degrees, dxfattribs=...)` — **`ezdxf.add_arc` takes degrees directly, unlike the COM `AddArc` in `executor.py` which needed a radian conversion** — this is a meaningful asymmetry between the "real" executor and the preview renderer (see section 9).
   - `ELLIPSE` → computes `major_axis` vector as `endpoint - center` (both promoted to 3-tuples via `_point3`, Z always 0.0) and calls `msp.add_ellipse(center=, major_axis=, ratio=, dxfattribs=...)`; if both angle fields present, adds `start_param`/`end_param` in **radians** (`math.radians(...)`) — ezdxf's ellipse start/end params are radians, matching the COM entity's `StartAngle`/`EndAngle` semantics.
   - `POLYLINE` → `msp.add_lwpolyline(points_2d, close=bool(closed), dxfattribs=...)`.
   - `TEXT` → helper `_add_text` creates the DXF TEXT entity then calls `entity.set_placement(position)` and optionally sets `entity.dxf.rotation`.
   - `INSERT` → **no real block insertion** — `_render_insert_placeholder` draws a substitute circle (`radius = max(25.0 * scale, 10.0)`) at the position plus a text label `f"BLOCK: {block_name}"` offset to the right (`position.x + radius*1.5`) — this is because the preview DXF has no access to the AutoCAD block library, so INSERT is always rendered as a generic marker, not the real block geometry.
   - `DIM_LINEAR` → `_render_dim_linear_preview` draws two plain LINE entities (the dimensioned segment itself, plus a horizontal line at the dimension line's Y position) and a TEXT entity at the dimension position showing `text_override` or the literal string `"<dim>"` if absent — this is a simplified geometric approximation of a real AutoCAD aligned dimension, not an actual DIMENSION entity.
5. **Per-command error handling is best-effort and silent-to-the-caller**: any exception raised while rendering command `index` (including an unsupported/missing renderer, which raises `PreviewRenderError` internally) is caught and passed to `_add_preview_error_marker(doc, msp, index, command, exc)`, which draws a red (`color=1`) TEXT entity on a `PREVIEW_ERROR` layer at `y = -100 * (index + 1)` reading `f"PREVIEW ERROR command {index}: {ExceptionType}"` — **the preview never raises for a single bad command; it always finishes and saves the file**, visually flagging failures instead of aborting (this differs from the live executor/edit_executor, which report per-command errors in a JSON error list rather than drawing them into the output).
6. `output.parent.mkdir(parents=True, exist_ok=True)`, then `doc.saveas(str(output))` (failure → `PreviewRenderError`).
7. Returns `str(output)` (the same path passed in).

**`render_preview_sequence(command_sequence, output_path) -> str`**: validates
via `validate_command_sequence` first (raises `PreviewRenderError` on schema
violations, mirroring `execute_command_sequence`'s pattern) then delegates to
`render_preview(command_sequence["commands"], output_path)`.

---

## 5. AutoCAD inspector (`src/framework/autocad/inspector.py`)

Purely read-only — the module docstring explicitly states it "does not
modify, delete, move, or create AutoCAD entities." Depends on the same
`AutoCADNotRunningError`/`_com_retry`/`_get_acad` trio from
`src.parametric.vessel.dwg_export`.

**`DrawingInspectionError`** — module's exception for: failure to obtain
`doc.ModelSpace` via either path (see below), no active document, and
`max_entities < 1`.

**`get_model_space_block(doc)`** — tries `doc.ModelSpace` first (`_com_retry`);
if that raises, falls back to `doc.Blocks.Item("*Model_Space")` — AutoCAD's
raw block-table name for model space, used when the friendlier `ModelSpace`
COM property is unavailable for some reason. If **both** fail, raises
`DrawingInspectionError` with a message embedding both underlying exception
type/messages, e.g. `"Failed to read ModelSpace. doc.ModelSpace failed with
AttributeError: .... doc.Blocks.Item(\"*Model_Space\") failed with
AttributeError: ...."` (exact substrings asserted in tests).

**Safe COM readers** (all best-effort, return `None`/default on any failure,
never raise): `_safe_get(obj, attr, default=None)` wraps `getattr` in
`_com_retry`; `_to_xyz(value)` normalizes a COM point-like value (unwraps
`.value`/`.Value` nested attrs once, then does `list(value)`) into a 3-float
list — pads a 2-element point with `0.0` for Z, returns `None` for anything
under 2 elements or non-iterable/string/bytes input; `_safe_float`,
`_safe_int` do plain `float()`/`int()` coercion swallowing exceptions;
`_safe_bbox(entity)` calls `entity.GetBoundingBox()` if that attribute
exists — first tries calling it with no args and unpacking a 2-tuple result
`(min, max)`; if that raises, retries using the classic pywin32
by-ref-`VARIANT` calling convention
(`win32com.client.VARIANT(VT_BYREF | VT_ARRAY | VT_R8, [0,0,0])` passed as
two out-params) — returns `{"min": [x,y,z], "max": [x,y,z]}` or `None`.

**`inspect_entity(entity, index) -> dict`** — the per-entity extraction,
entirely via `_safe_get`, always returns exactly this shape (extra fields
beyond `index` are always present but may be `None`):
```json
{
  "index": 7,
  "handle": "<Handle>",
  "object_name": "<ObjectName>",
  "entity_type": "<same as object_name>",
  "layer": "<Layer>",
  "color": 4,
  "linetype": "<Linetype>",
  "position": [x, y, z] | null,
  "center": [x, y, z] | null,
  "radius": 12.5 | null,
  "start_point": [x, y, z] | null,
  "end_point": [x, y, z] | null,
  "text": "<string>" | null,
  "bbox": {"min": [x,y,z], "max": [x,y,z]} | null
}
```
Notes on field-fill logic: `position` first tries the entity's `Position`
property, and if that's `None`, falls back to `InsertionPoint` (covers TEXT
and block-reference entities that use `InsertionPoint` instead of
`Position`). `text` reads `TextString` first; if that's `None` **and**
`object_name` is `"AcDbBlockReference"` or `"AcDbMInsertBlock"`, it falls
back to the entity's `Name` (the block definition name) — so an INSERT'd
block reference reports its block name in the `text` field even though it
has no text string. `entity_type` is always a duplicate of `object_name`
(intentional redundancy for downstream consumers that might expect either
key name).

**`_iter_modelspace_entities(msp, max_entities)`** — tries `iter(msp)` first
(COM collections are often directly iterable) and yields `(index, entity)`
pairs up to `max_entities`, stopping early with a plain `break` (so if
iteration itself is cheap/lazy, extra entities beyond the cap are never
even touched). If `iter(msp)` fails, falls back to an indexed-access loop
using `msp.Item(index)` for `index in range(limit)` where
`limit = min(max_entities, total_count)` when `total_count` (from
`_safe_modelspace_count`, same `Count`-then-`len()` pattern as
`executor.py`) is known, else just `max_entities`; any single `Item(index)`
failure inside this fallback path is silently skipped via `continue` (not
aborted).

**`inspect_active_drawing(max_entities=500) -> dict`** algorithm:
1. `max_entities < 1` → raise `DrawingInspectionError`.
2. `acad = _get_acad()` — `AutoCADNotRunningError` is **re-raised as-is** (not wrapped) if that specific exception occurs; any *other* exception during connection is wrapped as `DrawingInspectionError(f"Failed to connect to AutoCAD: {ExcType}: {msg}")`.
3. `doc = acad.ActiveDocument` — any exception, or a `None` result, raises `DrawingInspectionError("No active AutoCAD document is available.")`.
4. `msp = get_model_space_block(doc)`.
5. `total_count = _safe_modelspace_count(msp)`.
6. `entities = [inspect_entity(e, i) for i, e in _iter_modelspace_entities(msp, max_entities)]`.
7. `truncated = total_count is not None and total_count > max_entities`.
8. Returns:
```json
{
  "ok": true,
  "document_name": "Drawing10.dwg",
  "dwg_path": "C:\\Drawings\\Drawing10.dwg",
  "entity_count_total": 3,
  "entity_count_returned": 3,
  "truncated": false,
  "entities": [ /* inspect_entity(...) dicts, in ModelSpace iteration order */ ]
}
```

**`summarize_drawing_state(inspection: dict) -> str`** — a compact
human-readable one-liner built purely from the dict above (no new COM
calls): `document_name` (default `"<unnamed drawing>"` if falsy),
`entity_count_returned`, a sorted, deduplicated, comma-joined list of
non-empty `layer` values seen across `entities` (default `"none"`), and a
sorted `"<EntityType>=<count>"` list built from a `collections.Counter` over
`entity_type` (falling back to `object_name`, then the literal string
`"Unknown"`) — example: `"Drawing10.dwg: 3 entities returned. Layers:
GEOMETRY, TEXT. Types: AcDbCircle=1, AcDbLine=1, AcDbText=1."`

---

## 6. `src/autocad_client.py` — low-level connection helper (and why it's mostly dead code)

`src/autocad_client.py` defines:
- `point(x, y, z=0.0)` — same `VT_ARRAY | VT_R8` VARIANT construction as `acad_point` in `executor.py`, duplicated rather than shared.
- `AutoCADNotRunningError`, `NoActiveDrawingError` — two exceptions, **distinct from** the `AutoCADNotRunningError` defined independently in `src/parametric/vessel/dwg_export.py` (same name, two different classes in two different modules — a real gotcha if code ever does `except autocad_client.AutoCADNotRunningError` on an error actually raised by `dwg_export`'s class, or vice versa; they will not match).
- **`AutoCADClient`** class — `__init__` calls `self._connect()` then `self._get_active_doc()` then grabs `self.model = self.doc.ModelSpace`. `_connect()`: `win32com.client.GetActiveObject("AutoCAD.Application")`, wraps any failure as `AutoCADNotRunningError("AutoCAD is not running. Open AutoCAD and try again.")` — **note: no retry logic at all** (contrast with `dwg_export._get_acad`, which is the same one-line `GetActiveObject` call but is always invoked through `_com_retry` elsewhere in the codebase — `AutoCADClient` itself never uses `_com_retry`). `_get_active_doc()`: reads `self.app.ActiveDocument` and touches `doc.Name` to force a real round-trip check (some stale/None `ActiveDocument` references pass a naive read but fail on further use, so touching `.Name` catches that), wrapping failure as `NoActiveDrawingError("No drawing is open in AutoCAD. Open or create a drawing, then try again.")`.
- Convenience methods: `add_circle`, `add_line`, `add_rectangle` (builds a closed `AddLightWeightPolyline` from 4 explicit corner coordinates), `add_text`, `zoom_extents`, `open_drawing` (opens by path and refreshes `self.doc`/`self.model`), `save_drawing`, `close_drawing(save_changes=True)`. None of these have per-call retry, error normalization, layer handling, or structured result dicts — they are thin, immediate, unwrapped COM calls.
- `safe_connect()` — a CLI-oriented helper: constructs `AutoCADClient()`, and on either connection exception prints `f"ERROR: {e}"` and calls `sys.exit(1)` — this is meant for a command-line script context, not a library/API context (an API route calling this would kill the whole process on failure, which no route does — nothing in `src/api/` imports this module).

**Callers found via repo-wide grep**: only two files reference
`autocad_client` at all: `src/autocad_client.py` itself (its own module
docstring example) and `src/scratch/demo_shapes.py` (`from
src.autocad_client import safe_connect`), a standalone demo script that
connects and draws a couple of shapes with a comment `"Hello from
autocad_client"`. **No production code path** (no `src/api/routes/*`, no
`src/framework/*`, no `src/ai/*`, no `src/use_cases/*`) imports
`autocad_client.py`. Instead, every real COM-touching module in this
framework (`executor.py`, `edit_executor.py`, `inspector.py`, plus
`src/framework/pid/*`, `src/framework/cad3d/autocad_3d_executor.py`, most of
`src/ai/*`, and every route under `src/api/routes/`) imports `_get_acad`,
`_com_retry`, and `AutoCADNotRunningError` from
**`src.parametric.vessel.dwg_export`** instead — a module whose own docstring
says it is for `"DXF -> DWG conversion via AutoCAD COM"`. That module (read
in part for this doc) defines:
- `_get_acad()` — identical one-liner `win32com.client.GetActiveObject("AutoCAD.Application")`, wrapped into its own `AutoCADNotRunningError`.
- `_com_retry(operation, description, attempts=5, delay_seconds=0.5)` — calls `operation()`; on exception, checks `_is_busy_error(exc)` (true for a `pywintypes.com_error` whose `hresult` is `RPC_E_CALL_REJECTED` (-2147418111) or `RPC_E_SERVERCALL_RETRYLATER` (-2147417846), or for a plain `AttributeError`); if not a busy error, re-raises immediately; if busy and attempts remain, prints a retry notice to `stderr` and `time.sleep(delay_seconds * attempt)` (linear backoff: 0.5s, 1.0s, 1.5s, 2.0s for attempts 1–4 by default) before retrying, up to 5 attempts total; exhausting attempts re-raises the last error.

So **`src/autocad_client.py` is effectively legacy/orphaned** — the "real"
low-level AutoCAD connection helper the whole framework actually depends on
is the private (underscore-prefixed) helper trio inside
`src/parametric/vessel/dwg_export.py`, imported by module name into each
consumer's own namespace (which is also why tests monkeypatch
`executor._get_acad`, `inspector._get_acad`, etc., rather than patching
`dwg_export._get_acad` centrally — each importer gets its own bound
reference at import time). This is a significant architectural inconsistency
worth flagging to anyone extending this code (see section 9).

---

## 7. `src/backup.py`

`BACKUP_ROOT = Path(__file__).parent.parent / "backups"` — since this file
lives at `src/backup.py`, `.parent` is `src/`, `.parent.parent` is the
project root, so `BACKUP_ROOT` resolves to `<project_root>/backups`
regardless of the caller's current working directory (it's derived from
`__file__`, not `cwd`).

`backup_file(source_path: Path) -> Path`:
1. Coerces `source_path` to a `Path`; raises `FileNotFoundError(f"Source file does not exist: {source_path}")` if it doesn't exist.
2. Builds a timestamp string `datetime.now().strftime("%Y-%m-%d_%H-%M-%S")` (second-resolution, e.g. `2026-04-27_16-12-57`).
3. `target_dir = BACKUP_ROOT / timestamp`; `target_dir.mkdir(parents=True, exist_ok=True)`.
4. `shutil.copy2(source_path, target_dir / source_path.name)` — a full metadata-preserving copy (not a move; the original file is untouched) into that fresh per-call timestamped folder.
5. Returns the copied file's path.

**This matches what's on disk**: the repo's top-level `backups/` directory
contains one timestamped subfolder per `backup_file()` call (confirmed:
folders like `2026-04-27_16-12-57/`, each holding a single `drawing_001.dwg`
matching the source filename) — consistent with "one folder per call, named
by the moment `backup_file` ran." One thing worth a note: there is *also* a
`src/backups/` folder (inside `src/`, not at the project root) with the same
timestamp-folder pattern and the same `drawing_001.dwg` filename — this is
surprising given `BACKUP_ROOT` always resolves relative to `__file__`
(`src/backup.py`'s parent's parent, i.e. the project root, never `src/`
itself) and there is only one `backup.py` in the whole repo (confirmed via
`find`), so nothing in the current code should ever write to `src/backups/`.
The most likely explanation is that `src/backups/` is leftover from manual
testing/an earlier working-directory assumption rather than something the
current `backup_file()` implementation produces — a future agent should not
assume `src/backups/` is an active output location.

**Invocation**: `backup_file` is called from exactly one place in
production code: `src/use_cases/update_title_block.py:139` —
`result["backup"] = str(backup_file(dwg_path))`, i.e. it backs up the target
`.dwg` before that use case mutates the title block, and records the backup
path in its result dict. **It is not called anywhere in the generic
`executor.py`/`edit_executor.py` path** — `execute_commands` and
`execute_edit_plan` mutate/save the live document directly with no automatic
backup step; any caller of the generic command/edit executors that wants a
safety copy must call `backup_file` itself first (none of the API routes
found in this pass — `src/api/routes/sketch.py`, `pid.py`, `autocad_edit.py`
— do so before calling `execute_command_sequence`/`execute_edit_plan`; see
section 9, risk notes).

---

## 8. Test coverage summary

All 8 test files mock AutoCAD/COM entirely with hand-written fake classes —
**`win32com.client` is never imported or touched by these tests**, consistent
with there being no real AutoCAD installed on the analysis machine. The
mocking pattern is consistent across `test_command_executor.py`,
`test_edit_executor.py`, and `test_autocad_inspector.py`: each defines
`FakeEntity`/`FakeLayer(s)`/`FakeModelSpace`/`FakeDocument`/`FakeDocuments`/`FakeAcad`
classes with just enough attributes/methods to satisfy the code under test,
then uses `monkeypatch.setattr(<module>, "_get_acad", lambda: acad)` and
`monkeypatch.setattr(<module>, "_com_retry", lambda operation, description,
attempts=5, delay_seconds=0.5: operation())` (i.e. retry logic itself is
bypassed in tests — `_com_retry`'s actual backoff/retry behavior is **not**
unit-tested anywhere in this test set) to redirect the module's bound
references. `test_command_executor.py` additionally monkeypatches
`executor.acad_point`/`executor._acad_double_array` to identity-ish
tuple-returning functions so it never touches real `pythoncom`/`win32com`
VARIANT construction (meaning the actual VARIANT-building code path in
`acad_point`/`_acad_double_array` is also **not exercised** by any test —
only the fallback plain-tuple branch is implicitly covered, and only because
tests bypass the function entirely rather than because `pythoncom` import
fails).

Coverage by file:
- **`test_command_schema.py`**: valid LINE, valid 4-line rectangle; failure cases for missing `commands`, empty `commands`, unknown command type, LINE missing `to`, negative-radius CIRCLE, empty-text TEXT, 1-point POLYLINE, out-of-range LAYER color, extra/unexpected property; `is_valid_command_sequence` true/false. Does **not** explicitly test every command type's every field (e.g. no explicit ARC/ELLIPSE/INSERT/DIM_LINEAR schema-failure tests) — coverage is representative, not exhaustive per type.
- **`test_command_executor.py`**: empty-list rejection, invalid-schema rejection via `execute_command_sequence`, LINE/CIRCLE/TEXT COM calls, LAYER creation + color, layer-name propagation onto a created entity, one failing command (`INSERT` with `block_name="MISSING"`, which the `FakeModelSpace.InsertBlock` deliberately raises `RuntimeError` for) captured while a later LINE still executes (`continue_on_error=True`) vs. execution stopping after the first failure (`continue_on_error=False`), `save` true/false behavior, full `execute_command_sequence` happy path, zoom-extents called/not-called and its independent success/failure (`zoom_error` populated but `ok` stays `True`), and result fields `document_name`/`entity_count_before`/`entity_count_after`. **Not covered**: ARC, ELLIPSE, POLYLINE, INSERT-success, DIM_LINEAR execution paths (only INSERT-failure is exercised, not a successful INSERT), the `Linetype`-set failure `try/except: pass` branch in `_execute_layer`, the `AddLightWeightPolyline`-missing fallback branch in `_execute_polyline`, and the `SAVE`-failure error-dict branch.
- **`test_command_preview.py`**: empty-list/invalid-schema rejection, LINE/CIRCLE/TEXT/POLYLINE/ARC/ELLIPSE DXF-entity creation (each asserted via `ezdxf.readfile` + `msp.query(...)`), LAYER creation with color, entity-layer application, INSERT placeholder rendering (circle + `"BLOCK: PUMP"` text), DIM_LINEAR preview geometry (2+ lines, override text present), automatic output-directory creation, and `render_preview_sequence`'s return value. **Not covered**: the per-command error-marker path (`_add_preview_error_marker` — no test intentionally feeds a bad command into `render_preview` to check the red `PREVIEW_ERROR` text gets drawn instead of aborting), the `_set_units_to_mm` failure branches, and the "doc-level ezdxf creation fails" `PreviewRenderError` branch.
- **`test_edit_schema.py`**: valid delete-only, add-only, and replace-style (delete+add) plans; missing `edit_intent`, empty `edit_intent`, missing `delete_handles`, missing `commands`, both-empty (asserts the custom message substring), empty-string handle, invalid nested command (negative radius), unknown nested command type (asserts "unknown command type" substring), extra top-level property, wrong `schema_version`; `is_valid_edit_plan` true/false.
- **`test_edit_executor.py`**: invalid-plan rejection, delete-only (`HandleToObject`+`Delete` call sequence and counts), add-only (asserts exact call args passed through to the mocked `execute_commands`, including that `target_dwg_path` is always forced to `None` and `save`/`zoom_extents` are always forced `False` for the nested call), replace (delete-then-add ordering via a shared `call_log`), delete failure captured+continues (`continue_on_error=True`) vs. delete failure blocking the add phase entirely (`continue_on_error=False`, asserting the mocked `execute_commands` was **never called**), save true/false, zoom true/false (+ zoom failure not affecting `ok`), result metadata fields, add-phase errors surfacing with `type: "add"` and making `ok=False`. This is a thorough, algorithm-level test of the exact branching described in section 3.2.
- **`test_planning_schema.py`**: valid plan, missing/empty `chunks`, too-many-chunks (13, over the 12 max), chunk missing `goal`, empty `expected_elements` string, extra top-level property, wrong `schema_version`, `is_valid_drawing_task_plan` true/false. Does not test the `chunk_id` pattern regex (`^[A-Za-z0-9_-]+$`) failing on an invalid character, nor `priority < 1`.
- **`test_verification_schema.py`**: valid APPROVE (no issues), valid APPROVE_WITH_NOTES (with one WARNING issue + one MINOR annotation), valid REJECT (with one BLOCKER issue + one MAJOR annotation) — covers all three verdicts and all three severities/concern-levels combined across cases (though not every enum value gets its own dedicated positive test, e.g. no dedicated test for an `INFO`-severity issue or a `NONE`-concern-level annotation, though those are implicitly the "default" unexercised enum members); missing/invalid `verdict`, missing/wrong `schema_version`, empty `summary`, invalid `severity` value, negative `command_index`, invalid `concern_level`, extra top-level property, extra issue property, `is_valid_verification_result` true/false.
- **`test_autocad_inspector.py`**: `_to_xyz` conversion (tuple/list input) and its `None`-returning failure modes (`None` input, string input, too-short list, non-numeric list); `inspect_entity` field extraction for common fields, LINE (`start_point`/`end_point`), CIRCLE (`center`/`radius`, including a **string** radius `"12.5"` correctly coerced to float), TEXT (`position` via `InsertionPoint` + `text` via `TextString`), and a fully-broken `BadEntity` (every attribute access raises `RuntimeError`) still returning a well-formed all-`None` dict rather than raising; `inspect_active_drawing` metadata shape, `get_model_space_block` happy path and its fallback-to-`Blocks.Item("*Model_Space")` behavior (explicitly triggered by making `FakeDocumentModelSpaceFails.ModelSpace` a property that raises `AttributeError`), the double-failure `DrawingInspectionError` message format (asserts both embedded sub-messages appear), `max_entities` truncation behavior (`truncated=True` when total exceeds cap, returned entities capped and index-ordered), `summarize_drawing_state` content (document name, count, layers, type-counts), `AutoCADNotRunningError` propagating through un-wrapped, and "no active document" raising `DrawingInspectionError`. This is the most thorough test file relative to its module's surface area — nearly every branch in `inspector.py` has a corresponding test.

**Overall gaps across the whole test set** (beyond the per-file notes above):
- No test exercises real `pythoncom`/`win32com` VARIANT construction (`acad_point`, `_acad_double_array`, and the `pythoncom.VT_BYREF` bbox-reading branch in `inspector._safe_bbox`) — everything COM-VARIANT-shaped is monkeypatched away.
- No test exercises `_com_retry`'s actual retry/backoff behavior (busy-error detection, `time.sleep` backoff, exhausting attempts) since every test replaces `_com_retry` with a pass-through lambda — this real behavior lives in `src/parametric/vessel/dwg_export.py`, which has no dedicated test file evaluated in this pass.
- No integration test exists that runs the schema validator *and* the executor together end-to-end against a fake AutoCAD for every command type (each test file tests either schema-only or executor-only per command; a genuinely invalid-but-schema-passing edge case, e.g. an ARC whose `start_angle_degrees > end_angle_degrees`, is never explicitly tried anywhere).
- `src/backup.py` and `src/autocad_client.py` have **no test files at all** anywhere in the repo (not requested in the task's list, and none exist under `tests/` for either module, confirmed implicitly by their absence from the provided test list and by there being no `test_backup.py`/`test_autocad_client.py` surfaced during this investigation).

---

## 9. Cross-cutting observations (inconsistencies, TODOs, risk areas)

1. **Duplicate `AutoCADNotRunningError` classes with the same name.** `src/autocad_client.py` defines its own `AutoCADNotRunningError`; `src/parametric/vessel/dwg_export.py` defines a *different* class with the identical name, and it's the `dwg_export` one that every real framework module (`executor.py`, `edit_executor.py`, `inspector.py`, etc.) actually imports and raises/catches. Code that does `except autocad_client.AutoCADNotRunningError` would silently fail to catch an exception actually raised by the framework, since Python exception matching is by class identity, not name. There is also a distinct `NoActiveDrawingError` in `autocad_client.py` with no equivalent in `dwg_export.py` — the framework's own "no active document" cases raise their own module-local exceptions (`CommandExecutionError`, `EditExecutionError`, `DrawingInspectionError`) with a plain string message instead of a dedicated, catchable exception type.

2. **`src/autocad_client.py` is legacy/orphaned code.** It has real intent (a clean OO `AutoCADClient` wrapper) but zero production callers — only a scratch demo script uses it. Every actual COM entry point in the framework reaches into `src.parametric.vessel.dwg_export`'s private (`_`-prefixed) helpers instead, a module whose docstring and naming suggest it's scoped to "DXF→DWG conversion," not general AutoCAD connection management. A future agent adding a genuinely new "connect to AutoCAD" need should be aware the real shared implementation is in `dwg_export.py`, not `autocad_client.py`, despite the latter's name being the obvious guess. This also means `autocad_client.py`'s `point()` helper, `AutoCADClient.add_rectangle()` (closed 4-corner polyline), etc. have no automated test coverage and are not exercised by anything except manual scratch runs.

3. **No automatic backup before live mutation in the generic path.** `execute_commands`/`execute_command_sequence` (executor.py) and `execute_edit_plan` (edit_executor.py) both open/mutate/save the live AutoCAD document directly, with **no call to `src.backup.backup_file`** anywhere in either module or in the three API routes that call them (`sketch.py`, `pid.py`, `autocad_edit.py`). Backup is opt-in and currently wired into exactly one use case (`update_title_block.py`). Any drawing edited through the sketch-generation or live-edit-plan API flows has **no automatic safety copy** — if a bad command sequence or edit plan is approved and executed with `save=True` (the default for both functions), the live `.dwg` is overwritten with no rollback path other than whatever backup discipline the caller (human or upstream code) exercises manually. This is the single biggest "could corrupt a live drawing" risk area in this scope.

4. **Best-effort/partial execution is the default, and it's easy to end up with a half-applied drawing.** Both `execute_commands` and `execute_edit_plan` default `continue_on_error=True`, meaning a command sequence with one bad command (e.g. referencing a missing block, or a layer name AutoCAD rejects) will still execute and **save** every other command in the batch, then report `ok: False` with the specific failures listed — but the drawing has already been permanently changed (further compounded by point 3: no backup). A caller that only checks a top-level boolean without inspecting `errors` could believe a batch fully succeeded or fully failed when it actually partially succeeded. There is no dry-run/two-phase-commit/transaction concept anywhere in the executor — `preview.py`'s DXF preview is the closest thing to a dry run, but nothing forces a preview to happen before a real execute, and the preview renderer's ARC-angle-units, ellipse rendering approach, and INSERT-as-placeholder mean the preview is not a byte-for-byte stand-in for what the real executor will draw (see point 6).

5. **Verifier schema has no cross-field consistency enforcement.** `verification_schema.py`'s `VERIFICATION_SCHEMA` allows a `REJECT` verdict with an empty `issues` array, or an `APPROVE` verdict alongside a `BLOCKER`-severity issue — the schema only validates shape, not that the verdict logically follows from the issues list. This is presumably intentional (left to LLM judgment/prompting) but is a silent gap a future agent might assume is enforced.

6. **Preview rendering is not a faithful physical stand-in for real execution**, beyond the documented INSERT-placeholder behavior:
   - `executor.py`'s `_execute_arc` converts `start_angle_degrees`/`end_angle_degrees` to radians before calling COM `AddArc`; `preview.py`'s `_render_arc` passes the same degree values straight into `ezdxf`'s `add_arc`, which itself expects degrees — so both are internally correct for their respective target APIs, but this means the unit-conversion logic is duplicated and asymmetric across the two files rather than shared, and any future change to one (e.g. switching AutoCAD's expected units) must be remembered and mirrored in the other by hand.
   - `executor.py`'s DIM_LINEAR handler creates a genuine `AddDimAligned` COM dimension entity; `preview.py`'s DIM_LINEAR renderer draws two plain LINE primitives plus a TEXT label as a geometric approximation — visually similar but not the same entity type, so anything inspecting the preview DXF for "is there a DIMENSION entity" would get a false negative.
   - `executor.py`'s POLYLINE handler prefers `AddLightWeightPolyline` and falls back to `AddPolyline` (3D) depending on what the live COM `ModelSpace` object exposes; `preview.py` always uses `ezdxf.add_lwpolyline` (2D lightweight) unconditionally — so on an AutoCAD COM surface that lacks `AddLightWeightPolyline` (older/different config), the real executor's output entity type could differ from what the preview showed.

7. **Inconsistent shape of the `errors` list's `command` field in `executor.py`.** Per-command failures store the *actual command dict* under `errors[i]["command"]` (e.g. `{"command": "LINE", "from": [...], ...}`), but the save-failure entry stores the **literal string** `"SAVE"` in that same key (`{"command_index": None, "command": "SAVE", "error": ...}`). A consumer that assumes `errors[i]["command"]` is always a dict (e.g. to re-display or re-attempt the failed command) would need a special case for the save-failure sentinel. `edit_executor.py` avoids this specific issue by using a `"type"` discriminator field (`"delete"`/`"add"`/`"save"`) instead of overloading a `"command"` key, which is the more consistent design of the two executors — a future refactor could align `executor.py`'s error shape to that same `"type"`-tagged pattern.

8. **Duplicated `_format_path`/`_format_error` schema-error-formatting helpers.** `schema.py` and `edit_schema.py` each define byte-for-byte nearly identical `_format_path`/`_format_error` functions (the only difference being which `_COMMAND_TYPES` list `_format_error` references for its "unknown command type" special case); `planning_schema.py` and `verification_schema.py` each define their own simpler `_format_path`/`_format_error` pair (without the enum special-case). None of these four are shared via a common utility module — a fifth schema module added later would likely copy-paste a fifth near-identical pair rather than reuse one.

9. **`common_optional` definition in `schema.py` is unused dead code.** `COMMAND_SCHEMA["definitions"]["common_optional"]` bundles `layer`/`comment` but no per-command-type definition actually `$ref`s it — every command definition (LINE, CIRCLE, etc.) inlines its own `layer`/`comment` properties directly instead. Harmless, but a maintenance trap: editing `common_optional` would have zero effect on validation behavior, which is not obvious from reading the schema alone.

10. **`ensure_layer`'s "get-or-create" pattern in `executor.py` does a full COM round-trip (`layers.Item`) even for cache-hit layers**, rather than trusting the `known_layers` cache to skip the COM call entirely — the code comment/structure suggests the cache is meant as an optimization, but as written it still calls `_com_retry(lambda: layers.Item(layer_name), ...)` on every cache hit (just skips the "does it exist" probe-then-create fallback logic, not the COM call itself). This is a minor perf nit, not a correctness bug, but worth knowing if profiling COM call counts later.

11. **`src/backups/` (inside `src/`) vs. `backups/` (project root) mismatch.** As detailed in section 7, the current `backup.py` code should only ever write under the project-root `backups/` folder (derived from `__file__.parent.parent`), yet a `src/backups/` folder with the same naming convention exists on disk. No second `backup.py`/`backup_file` implementation was found anywhere in the repo that could have produced it. Flagged here as a discrepancy for a future agent to be aware of — don't assume `src/backups/` is a live, current output path; treat any content there as possibly stale/manually-placed rather than authoritative.

12. **Zoom/regen failures are always non-fatal to `ok`, by design, in both executors** — confirmed by explicit tests (`test_zoom_failure_does_not_make_ok_false_when_commands_succeeded` / `..._when_edits_succeeded`). This is a deliberate, tested design choice (cosmetic viewport operations shouldn't fail an otherwise-successful drawing edit), not a gap — noted here only so it isn't mistaken for a bug when auditing error handling.

13. **`CommandExecutionError`/`EditExecutionError`/`DrawingInspectionError`/`PreviewRenderError` are four separate, unrelated exception classes** (no shared base class between them, e.g. no common `FrameworkError`), each defined locally in its own module. A caller that wants to catch "anything from this framework layer" in one `except` clause cannot do so without listing all four (plus `AutoCADNotRunningError` from `dwg_export.py`, plus potentially `autocad_client.py`'s two if that legacy module is ever wired back in) individually.

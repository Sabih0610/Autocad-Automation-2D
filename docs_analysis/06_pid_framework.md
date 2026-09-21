# P&ID Framework Deep Dive (`src/framework/pid/`)

This document exhaustively covers the deterministic 2D P&ID (Piping & Instrumentation Diagram)
subsystem. It is a sibling of, but architecturally unrelated to, the 3D `cad3d` subsystem — they
share no base classes, no schema code, and no command-generation code. Everything here concerns
2D schematic symbols drawn with flat AutoCAD 2D primitives (LINE, ARC, CIRCLE, POLYLINE, TEXT) on
named layers, output as a "command sequence" JSON object that the executor (`src/framework/commands/executor.py`,
outside this scope) replays into AutoCAD via COM.

All coordinates throughout this subsystem are in **millimeters**, and geometry is essentially
schematic/topological, not to true physical scale (vessel diameters of 700mm are drawn far larger
than realistic diagrams for presentation-video legibility — see `_equipment_tag_height` sizing
comments in `symbols.py`).

---

## 1. Role in the system

The project README describes the pipeline as:
`user prompt -> AI component scene planner -> deterministic schema validation -> deterministic component builder/renderer -> command sequence -> AutoCAD approval execution`.

Concretely, across files (both in- and out-of-scope) this maps as:

1. **User prompt** arrives at `POST /api/pid/generate` (`src/api/routes/pid.py:33`, `pid_generate`), carrying `prompt` and `drawing_style` (via `PIDGenerateRequest`, defined in `src/api/schemas.py`, out of scope).
2. **AI component scene planner**: `src/ai/pid_component_planner.py` (out of scope for deep documentation, but read here for the handoff contract) — `plan_and_render_pid_component_scene_resilient()` is called with `allow_template_fallback=True, template_first=False`. It calls `ask_ai(...)` with the exact JSON Schema `PID_COMPONENT_SCENE_SCHEMA` (imported from `component_schema.py`, **in scope**) as the response-format constraint, and the system prompt `PID_COMPONENT_PLANNER_SYSTEM_PROMPT` which enumerates the 11 supported `component_type` values.
3. **Deterministic schema validation**: whatever JSON the AI returns (or whatever deterministic template is chosen on failure) is validated via `validate_pid_component_scene_data()` in `component_schema.py:229`. This is a strict Draft-07 JSON Schema check (`additionalProperties: False`, `oneOf` per component type).
4. **Deterministic component builder/renderer**: `component_builder.py`'s `build_pid_component_scene()` (line 121) turns validated JSON into a `PIDComponentScene` object (dataclasses in `components/`), and `render_pid_component_scene_data()` (line 144) is the single call that does validate → build → `scene.to_command_sequence()`.
5. **Command sequence**: `PIDComponentScene.to_command_sequence()` (`components/scene.py:66`) emits the exact same "Mode 2 command schema" dict shape used elsewhere in the app (`schema_version`, `summary`, `estimated_drawing_type`, `assumptions`, `commands`), validated against `COMMAND_SCHEMA` from `src/framework/commands/schema.py` (out of scope but read for context — command types are `LAYER, LINE, CIRCLE, ARC, ELLIPSE, POLYLINE, TEXT, INSERT, DIM_LINEAR`).
6. **AutoCAD approval execution**: the FastAPI route caches the generated `command_sequence` under a random `uuid4().hex` token in the in-memory dict `_PID_CACHE` (`pid.py:19`), and only actually draws it when the user later calls `POST /api/pid/approve` with that token, which calls `execute_command_sequence()` (`src/framework/commands/executor.py`, out of scope) inside a `pythoncom.CoInitialize()/CoUninitialize()` block.

There are **two independent, parallel pipelines** in this subsystem that both terminate in the
same command-sequence JSON shape:

- **The "flat scene" pipeline**: `scene_schema.py` (fixed lists: `equipment`, `pipes`, `valves`, `instruments`, `labels`, `flow_arrows`, `signal_lines`) + `scene_renderer.py` (a single big function `render_pid_scene_to_commands`). This is the *older/simpler* design — it is **not** what `/api/pid/generate` uses. Nothing in `src/ai/` or `src/api/` currently calls `scene_renderer.py`; it is exercised only by its own example function and tests. It appears to be a predecessor design kept for its worked example (`example_horizontal_separator_pid_scene`) and/or reference tests.
- **The "component" pipeline**: `component_schema.py` (a flat `components` array where each item is tagged by `component_type`) + `component_builder.py` + the `components/` package (OOP dataclasses with ports, rendering, and a scene container) + `component_templates.py` (deterministic fallback scenes) + `component_examples.py` (hand-built demonstration scenes using the OOP component classes directly, bypassing JSON). **This is the pipeline actually wired to `/api/pid/generate`** via `src/ai/pid_component_planner.py`.

Both pipelines ultimately call into the same low-level deterministic geometry functions in
`symbols.py` (e.g. both `scene_renderer.py` and `components/equipment.py` call
`horizontal_vessel_commands`), so `symbols.py` is the true shared foundation of the whole
subsystem.

---

## 2. `symbols.py` — deterministic symbol/primitive catalog

File: `src/framework/pid/symbols.py`. Pure functions, no classes. Every function returns a
`list[dict]` of Mode-2-command-schema dicts (never a full sequence) except
`wrap_commands_as_sequence`, which wraps a `list[dict]` into the full sequence envelope.

### Constants
- Layer name constants: `PID_LAYER_EQUIPMENT="PID_EQUIPMENT"`, `PID_LAYER_PIPING="PID_PIPING"`, `PID_LAYER_VALVES="PID_VALVES"`, `PID_LAYER_INSTRUMENTS="PID_INSTRUMENTS"`, `PID_LAYER_TEXT="PID_TEXT"`, `PID_LAYER_SIGNAL="PID_SIGNAL"`, `PID_LAYER_FLOW="PID_FLOW"`.
- ACI color constants tied 1:1 to the above layers: `PID_COLOR_EQUIPMENT=4` (cyan), `PID_COLOR_PIPING=3` (green), `PID_COLOR_VALVES=6` (magenta), `PID_COLOR_INSTRUMENTS=2` (yellow), `PID_COLOR_TEXT=7` (white/foreground), `PID_COLOR_SIGNAL=8` (gray), `PID_COLOR_FLOW=30` (orange-ish).
- Sizing constants: `PID_TEXT_HEIGHT_NORMAL=85`, `PID_TEXT_HEIGHT_SMALL=55`, `PID_TEXT_HEIGHT_TITLE=150`, `PID_INSTRUMENT_RADIUS=85`, `PID_VALVE_SIZE=120`, `PID_PIPE_LABEL_OFFSET=140`, `PID_EQUIPMENT_TAG_HEIGHT=70`.

### Internal helpers
- `_xy(point) -> (float, float)`: requires a `list` of length ≥2, else raises `ValueError("point must contain at least two coordinates")`.
- `_validate_positive(value, name)`: raises `ValueError(f"{name} must be positive")` if `<= 0`.
- `_validate_orientation(orientation)`: uppercases and requires `{"H","V"}`, else `ValueError("orientation must be 'H' or 'V'")`.
- `_validate_direction(direction)`: uppercases and requires `{"RIGHT","LEFT","UP","DOWN"}`, else `ValueError("direction must be RIGHT, LEFT, UP, or DOWN")`.
- `_estimated_text_width(text, height) = len(text) * height * 0.55` — crude monospace-ish width estimate used only to decide tag placement, not written into any command.
- `_equipment_tag_height(size)`: clamps `size * 0.12` between `PID_EQUIPMENT_TAG_HEIGHT*0.65=45.5` and `PID_EQUIPMENT_TAG_HEIGHT+10=80`. Comment explicitly says this exists because "the previous sizing could make tags very large on big equipment" — tuned for demo videos/screenshots, not engineering accuracy.

### `pid_standard_layers() -> list[dict]`
Returns 7 `LAYER` commands (one per layer constant above), each `{"command": "LAYER", "layer_name": ..., "color": ...}`. This is prepended to every rendered command sequence in both pipelines (via `PIDComponentScene.render_commands(include_standard_layers=True)` default, and directly in `scene_renderer.render_pid_scene_to_commands`).

### Drawing-primitive symbol functions
All validate inputs and raise `ValueError` on bad geometry (size/diameter/length/height/radius must be positive; tag/text must be non-empty).

- **`pipe_line_commands(points, layer=PID_LAYER_PIPING) -> [POLYLINE]`**: requires `len(points) >= 2`; emits one open (`closed: False`) `POLYLINE` command through all given points, coerced to floats.

- **`horizontal_vessel_commands(center, length, diameter, tag="V-101", layer=PID_LAYER_EQUIPMENT) -> [LINE, LINE, ARC, ARC, TEXT]`**: draws a horizontal cylindrical vessel as top/bottom `LINE`s spanning `length`, capped by two `ARC`s of `radius = diameter/2` (left cap `90°→270°`, right cap `270°→90°`), plus a `TEXT` tag. Tag height from `_equipment_tag_height(diameter)`; tag is centered inside the vessel at `cy + diameter*0.12` unless it's too wide (`tag_width > length*0.65`) or too tall (`tag_height > diameter*0.35`), in which case it's pushed above the vessel (`top_y + tag_height*0.75`). Tag TEXT is always emitted on `PID_LAYER_TEXT` regardless of the `layer` param (which only affects the vessel body lines/arcs).

- **`vertical_vessel_commands(center, height, diameter, tag="V-101", layer=PID_LAYER_EQUIPMENT) -> [LINE, LINE, ARC, ARC, TEXT]`**: mirror of the horizontal version rotated 90°: left/right vertical `LINE`s spanning `height`, top cap `ARC` (`0°→180°`), bottom cap `ARC` (`180°→360°`), radius = `diameter/2`. Tag placed inside near `cy + diameter*0.12` unless `tag_width > diameter*0.9`, then pushed above the vessel.

- **`gate_valve_commands(center, size=PID_VALVE_SIZE, orientation="H", layer=PID_LAYER_VALVES) -> list[dict]`**: classic bow-tie/hourglass gate-valve symbol — two triangular `POLYLINE`s (`closed: True`) meeting at the center point, plus inlet/outlet connector `LINE`s extending `half + connector` beyond the body, plus a stem `LINE` and a perpendicular handle `LINE` at the top (H) or right (V) end. Sizing fractions of `size`: `body_half=half*0.82`, `body_width=half*0.52`, `connector=half*0.32`, `stem=half*0.55`, `handle=half*0.42`. For `orientation="H"` the handle sticks up; for `"V"` it sticks out to the right. Returns 6 commands (2 POLYLINE + 4 LINE).

- **`control_valve_commands(center, size=140, orientation="H", layer=PID_LAYER_VALVES) -> list[dict]`**: calls `gate_valve_commands(...)` internally then appends a `CIRCLE` (the actuator, `radius = size*0.22`) and a `LINE` connecting the valve body to the actuator. Actuator is offset `size*0.88` above center (H) or to the right of center (V); the connecting stem only reaches `size*0.48` from center. This is the "instrument-actuated valve" symbol (control valve with diaphragm actuator).

- **`instrument_bubble_commands(center, tag, radius=PID_INSTRUMENT_RADIUS, layer=PID_LAYER_INSTRUMENTS) -> [CIRCLE, LINE, TEXT]`**: the standard ISA instrument-bubble symbol — a `CIRCLE`, a horizontal `LINE` bisecting it (the tag-split line separating instrument-letter row from loop-number row conventionally, though here it's just one tag string), and centered `TEXT`. Text height clamped between 32 and 52 (`radius*0.24` clamped). Text always on `PID_LAYER_TEXT`.

- **`signal_line_commands(points, layer=PID_LAYER_SIGNAL) -> [POLYLINE]`**: literally delegates to `pipe_line_commands(points, layer=layer)`. Docstring notes dashed-linetype support "can be added later when linetype availability is managed centrally" — currently signal lines are visually identical solid polylines, distinguished only by layer/color (gray, ACI 8).

- **`flow_arrow_commands(position, direction="RIGHT", size=100, layer=PID_LAYER_FLOW) -> [POLYLINE(closed=True)]`**: a filled/closed triangular arrowhead. `half = size*0.45` (tip distance), `width = size*0.26` (base half-width). Four direction branches (`RIGHT/LEFT/UP/DOWN`) each produce a 3-point closed triangle pointing the requested way.

- **`text_label_commands(text, position, height=PID_TEXT_HEIGHT_NORMAL, layer=PID_LAYER_TEXT) -> [TEXT]`**: single TEXT command; raises `ValueError("text cannot be empty")` if `text` falsy.

- **`wrap_commands_as_sequence(commands, summary="P&ID symbol test") -> dict`**: builds the full command-sequence envelope: `{"schema_version": COMMAND_SCHEMA_VERSION, "summary": summary, "estimated_drawing_type": "P&ID schematic", "assumptions": ["Generated from deterministic P&ID symbol templates."], "commands": commands}`. `COMMAND_SCHEMA_VERSION` is imported from `src/framework/commands/schema.py` (currently `"1.0"`).

No block/INSERT-based symbols exist anywhere in this subsystem — everything is drawn from raw
LINE/ARC/CIRCLE/POLYLINE/TEXT primitives; `INSERT` and `DIM_LINEAR` command types exist in the
shared command schema but are never emitted by any P&ID code.

---

## 3. Schema files — full JSON shapes

Both schema files are Draft-07 JSON Schemas built with the `jsonschema` package
(`Draft7Validator`), both expose the same three-function pattern: `_format_path`, `_format_error`,
`validate_*(data) -> list[str]`, `is_valid_*(data) -> bool`. Errors are formatted as
`"root.path[index]: message"`.

### 3a. `scene_schema.py` — the "flat scene" shape (`PID_SCENE_SCHEMA`, version `PID_SCENE_SCHEMA_VERSION = "1.0"`)

Top-level object, `additionalProperties: False`, **all 10 of these keys are required** (even if
the corresponding array is empty):

| Field | Type | Notes |
|---|---|---|
| `schema_version` | `const "1.0"` | must equal exactly |
| `title` | string, minLength 1 | |
| `drawing_type` | string, minLength 1 | e.g. `"P&ID"` |
| `assumptions` | array of strings | may be empty |
| `equipment` | array of `equipment` objects | may be empty |
| `pipes` | array of `pipe` objects | may be empty |
| `valves` | array of `valve` objects | may be empty |
| `instruments` | array of `instrument` objects | may be empty |
| `labels` | array of `label` objects | may be empty |
| `flow_arrows` | array of `flow_arrow` objects | may be empty |
| `signal_lines` | array of `signal_line` objects | may be empty |

Sub-object definitions (all `additionalProperties: False`):

- **`equipment`**: required `["id","type","tag","center","diameter"]`. `type` enum `["horizontal_vessel","vertical_vessel"]`. Conditional (`allOf`/`if-then`): if `type=="horizontal_vessel"` then `length` is additionally required; if `type=="vertical_vessel"` then `height` is additionally required. Optional properties present in the schema regardless: `length`, `height`, `diameter` (all `exclusiveMinimum: 0`). `center` is a 2-number point.
- **`pipe`**: required `["id","points"]`. `points`: array of 2-number points, `minItems: 2`. Optional `label` (string, minLength 1).
- **`valve`**: required `["id","type","center","orientation"]`. `type` enum `["gate_valve","control_valve"]`. `orientation` enum `["H","V"]`. Optional `size` (`exclusiveMinimum: 0`).
- **`instrument`**: required `["id","tag","center"]`. Optional `radius` (positive number) and `signal_to` (a points array, `minItems: 2` — a polyline to another point, used to draw a signal line from the instrument).
- **`label`**: required `["text","position"]`. Optional `height` (positive number). **Note: no `id` field on labels** in this schema (unlike every other definition).
- **`flow_arrow`**: required `["position","direction"]`. `direction` enum `["RIGHT","LEFT","UP","DOWN"]`. Optional `size`. **No `id` field.**
- **`signal_line`**: required `["points"]` only. Points array `minItems: 2`. **No `id` field.**

Functions: `validate_pid_scene(data) -> list[str]`, `is_valid_pid_scene(data) -> bool`.

### 3b. `component_schema.py` — the "component" shape (`PID_COMPONENT_SCENE_SCHEMA`, version `PID_COMPONENT_SCHEMA_VERSION = "1.0"`)

Top-level object, `additionalProperties: False`, required `["schema_version","title","drawing_type","assumptions","components"]` (note: **no separate arrays per category** — everything lives in one `components` array, unlike the flat scene schema).

| Field | Type | Notes |
|---|---|---|
| `schema_version` | `const "1.0"` | |
| `title` | string, minLength 1 | |
| `drawing_type` | string, minLength 1 | |
| `assumptions` | array of strings | |
| `metadata` | object (optional) | used by planner/templates to stash `source`, `template_name`, `planner_strategy`, `fallback_used`, `fallback_reason`, `ai_planner_attempted`, `ai_planner_error_type`, `ai_planner_error` — see §7 |
| `components` | array, `minItems: 1` | each item validated against a `oneOf` list of 11 per-type schemas |

Every component schema shares a common base (`_base_properties`, `component_builder.py`
line 50): `component_type` (`const` = the specific type string), `id` (string, minLength 1),
`tag` (string, minLength 1, optional), `center` (2-number point, optional unless required by
that type), `metadata` (object, optional). Every component schema sets
`additionalProperties: False` and `required: ["component_type","id", ...type-specific requireds]`.

The 11 valid `component_type` strings and their extra required/optional fields:

1. **`horizontal_vessel`** — required extra: `tag`, `center`, `length`, `diameter`. Properties: `length` (positive number), `diameter` (positive number).
2. **`vertical_vessel`** — required extra: `tag`, `center`, `height`, `diameter`. Properties: `height`, `diameter` (positive numbers).
3. **`pipe_run`** — required extra: `points`. Properties: `points` (≥2 points), `label` (string), `label_position` (point), `flow_direction` (enum RIGHT/LEFT/UP/DOWN), `flow_arrow_position` (point). Note `center` is NOT required/typically used for pipe runs (they use `points` instead).
4. **`signal_line`** — required extra: `points`. Properties: `points` only.
5. **`gate_valve`** — required extra: `center`, `orientation`. Properties: `orientation` (enum H/V), `size` (positive number).
6. **`control_valve`** — same shape as `gate_valve`.
7. **`instrument_bubble`** — required extra: `tag`, `center`. Properties: `radius` (positive number).
8. **`controller_loop`** — required extra: `instrument_tag`, `controller_tag`, `instrument_center`, `controller_center`. Properties: those four (strings/points) plus `signal_points` (≥2 points, optional) and `radius` (optional).
9. **`label`** — required extra: `text`, `center`. Properties: `text` (string), `height` (positive number, optional).
10. **`flow_arrow`** — required extra: `center`, `direction`. Properties: `direction` (enum), `size` (optional).
11. **`leader_line`** — required extra: `points`. Properties: `points`, `text` (optional string), `text_position` (optional point).

Functions: `validate_pid_component_scene_data(data) -> list[str]`, `is_valid_pid_component_scene_data(data) -> bool`.

**Key schema-level asymmetry to flag for future work**: because each component's schema branch
declares its own `required` list and Draft-07 `oneOf` tries every branch, a component object
missing a required field for its own type will fail *every* branch (since `component_type` is a
`const` mismatch on the 10 other branches too), producing potentially confusing multi-branch error
output from `_VALIDATOR.iter_errors` — though `validate_pid_component_scene_data`'s sorted/dedup
formatting keeps this readable in practice (confirmed by test expectations only checking
truthiness of the error list, not exact messages, except in `scene_schema.py`'s equipment
`if/then` tests which are exact-required-field failures, not `oneOf` branch explosions).

---

## 4. Component architecture (`components/` package)

### `components/base.py` — the foundation

- `Point = list[float]`, `PortMap = dict[str, Point]` (type aliases only, not classes).
- `normalize_point(point) -> Point`: accepts a `list`/`tuple` of length 2 or 3 (3D points are
  accepted but the Z coordinate is **silently dropped** — this is a genuinely 2D-only framework);
  raises `ValueError("point must be a 2D or 3D coordinate")` for wrong length/type, or
  `ValueError("point coordinates must be numeric")` if casting to float fails.
- `offset_point(point, dx=0, dy=0) -> Point`: returns `[x+dx, y+dy]`.
- `component_text_id(prefix, index) -> str`: formats `"{prefix}-{index:03d}"` (e.g.
  `component_text_id("V", 101) == "V-101"`); raises on empty/whitespace prefix or `index < 1`.
- **`PIDComponent`** (a `typing.Protocol`, structural typing only — not a base class components
  inherit from): declares `id: str`, `tag: str | None`, and methods `ports() -> PortMap`,
  `render() -> list[dict]`, `summary() -> str`.
- **`BasePIDComponent`** (`@dataclass`) — the actual concrete base every component subclasses
  (all component dataclasses in `equipment.py`/`instruments.py`/`piping.py`/`valves.py`/`annotations.py`
  inherit from this). Fields: `id: str`, `tag: str | None = None`,
  `center: Point = [0.0, 0.0]` (default factory), `metadata: dict[str, Any] = {}` (default
  factory). `__post_init__` validates: `id` must be a non-empty/non-whitespace string (stripped in
  place); `tag`, if not `None`, must be non-empty/non-whitespace (stripped); `center` is run
  through `normalize_point`; `metadata` must be a `dict`. Default `ports()` returns `{}`.
  Default `render()` raises `NotImplementedError` (subclasses must override). Default `summary()`
  returns `f"{self.__class__.__name__}(id={self.id}, tag={self.tag})"`.
- **`RenderedComponent`** (`@dataclass`, not a `PIDComponent` itself): the result of "rendering"
  one component — `component_id: str`, `component_type: str` (the Python class name, e.g.
  `"HorizontalVesselComponent"` — **not** the JSON `component_type` string like
  `"horizontal_vessel"`), `commands: list[dict]`, `ports: PortMap`, `summary: str`.
- **`render_component(component) -> RenderedComponent`**: calls `component.render()` for
  `commands`, and `component.ports()` for `ports` (running every port value through
  `normalize_point` again defensively), and `component.summary()`.

### `components/equipment.py`

- **`HorizontalVesselComponent`** (`@dataclass`, extends `BasePIDComponent`): fields `length: float = 2600.0`, `diameter: float = 700.0`. `__post_init__` validates both positive, casts to float. `ports()` returns 7 named ports computed from `center`/`length`/`diameter`: `inlet_left` (left end, on centerline), `outlet_right` (right end, on centerline), `vapor_top` (30% right of center, at top), `top_center`, `bottom_center`, `water_bottom_left` (30% left of center, at bottom), `oil_bottom_right` (30% right of center, at bottom). These port names directly encode the real-world layout convention for a 3-phase horizontal separator (inlet, vapor out top, oil/water out bottom split left/right). `render()` delegates to `symbols.horizontal_vessel_commands(center, length, diameter, tag=self.tag or self.id)` — **note the tag fallback**: if no explicit `tag` was given, the component `id` itself is drawn as the vessel tag text.
- **`VerticalVesselComponent`**: fields `height: float = 1800.0`, `diameter: float = 700.0`. `ports()` returns 4 named ports: `top`, `bottom`, `left`, `right`. `render()` delegates to `symbols.vertical_vessel_commands(...)`, same `tag or id` fallback.

Real-world symbol represented: ASME/ISO-style vessel outlines (a rounded-cap cylinder body) — the
classic "TL/TT" horizontal vessel or vertical column/tower shape seen in P&IDs, with a tag label.

### `components/instruments.py`

- **`InstrumentBubbleComponent`**: field `radius: float = PID_INSTRUMENT_RADIUS` (85). `__post_init__` **requires `tag` to be non-`None`** (raises `ValueError("tag must be non-empty")` if missing — this is the one component type where `tag` is effectively mandatory even though the base class treats it as optional). `ports()`: `center`, `bottom`, `top`, `left`, `right` (cardinal points on the circle). `render()` delegates to `symbols.instrument_bubble_commands(center, tag=self.tag or "", radius=self.radius)`.
- **`ControllerLoopComponent`**: represents a *pair* of instrument bubbles connected by a signal line — the classic "field transmitter → controller" loop symbol. Fields: `instrument_tag: str = ""`, `controller_tag: str = ""`, `instrument_center: Point = [0.0, 0.0]`, `controller_center: Point = [250.0, 0.0]`, `signal_points: list[Point] | None = None`, `radius: float = PID_INSTRUMENT_RADIUS`. `__post_init__` validates both tags non-empty (via local `_validate_tag`), normalizes both centers, validates radius positive, and if `signal_points` given requires `len >= 2` and normalizes each point. `ports()` returns `{"instrument": ..., "controller": ...}` (note: **not** using the component's own `center`/`id` port convention — this component effectively has two logical "bodies"). `render()`: draws two `instrument_bubble_commands` calls (one per tag/center) plus a `signal_line_commands` call along `signal_points` or, if not given, a straight 2-point line directly from `instrument_center` to `controller_center`.

Real-world symbol represented: transmitter-to-controller instrumentation loop (e.g. LT→LC,
PT→PIC), a very common P&ID motif — this single component encodes 2 bubbles + 1 dashed/plain
signal line as one reusable unit.

### `components/piping.py`

- **`polyline_midpoint(points) -> Point`** (module function, not a method): finds the midpoint of the routed polyline's *middle segment* — `segment_index = (len(points)-2)//2`, then midpoint of `points[segment_index]` to `points[segment_index+1]`. Used as the default label/flow-arrow anchor when none is explicitly given. For a 2-point line this is simply the line's midpoint; for longer polylines it targets roughly the visually-central segment (not the true polyline centroid).
- **`PipeRunComponent`**: fields `points: list[Point] = []`, `label: str | None = None`, `label_position: Point | None = None`, `flow_direction: str | None = None`, `flow_arrow_position: Point | None = None`. `__post_init__` requires `len(points) >= 2`, normalizes all points; if `label` given requires non-empty (stripped); normalizes `label_position`/`flow_arrow_position` if given; normalizes `flow_direction` via `_normalize_direction` (upper-cased, must be in `{"RIGHT","LEFT","UP","DOWN"}`, else `ValueError("flow_direction must be RIGHT, LEFT, UP, or DOWN")`). `ports()`: `{"start": points[0], "end": points[-1]}`. `render()`: always emits `pipe_line_commands(points)` (a POLYLINE); if `label` is truthy, additionally emits a `text_label_commands` call at `label_position` or, if absent, at `polyline_midpoint(points)` offset by `(-PID_PIPE_LABEL_OFFSET*0.8, +PID_PIPE_LABEL_OFFSET)` = `(-112, +140)`; if `flow_direction` is truthy, additionally emits `flow_arrow_commands` at `flow_arrow_position` or the polyline midpoint.
- **`SignalLineComponent`**: fields `points: list[Point] = []`. Same `>=2` point validation/normalization as `PipeRunComponent` but simpler (no label/arrow). `ports()`: `{"start", "end"}`. `render()` delegates straight to `symbols.signal_line_commands(points)` (gray dash-intended polyline, `PID_LAYER_SIGNAL`).

Real-world symbol represented: process piping runs (green, `PID_LAYER_PIPING`) with inline flow
labels and directional arrowheads, versus instrument signal/control lines (gray,
`PID_LAYER_SIGNAL`).

### `components/valves.py`

- Module-level `_valve_ports(center, size, orientation) -> PortMap` shared by both valve component classes: for `"H"` orientation returns `{"left": [cx-half,cy], "right": [cx+half,cy]}`; for `"V"` returns `{"bottom": [cx,cy-half], "top": [cx,cy+half]}` where `half = size/2`.
- **`GateValveComponent`**: fields `orientation: str = "H"`, `size: float = PID_VALVE_SIZE` (120). `__post_init__` normalizes orientation (must be H/V else `ValueError("orientation must be 'H' or 'V'")`) and validates size positive (`ValueError("size must be positive")`). `ports()` = `_valve_ports(...)`. `render()` delegates to `symbols.gate_valve_commands(center, size, orientation)`.
- **`ControlValveComponent`**: identical shape/validation to `GateValveComponent`; `render()` delegates to `symbols.control_valve_commands(...)` (adds the actuator circle+stem on top of the gate-valve bowtie symbol).

Real-world symbol represented: manual isolation valve (bowtie, "gate valve" generic symbol used
here for any manual on/off valve) vs. an instrument-actuated control valve (bowtie + circle
actuator on a stem) — these are the two valve symbol types the whole framework supports; there is
no ball/check/relief-valve-specific geometry anywhere.

### `components/annotations.py`

- **`LabelComponent`**: fields `text: str = ""`, `height: float = PID_TEXT_HEIGHT_NORMAL` (85). `__post_init__` requires non-empty text (stripped) else `ValueError("text must be non-empty")`; validates height positive. `render()` = `symbols.text_label_commands(text, center, height)`. (No `ports()` override — inherits the empty-dict default from `BasePIDComponent`.)
- **`FlowArrowComponent`**: fields `direction: str = "RIGHT"`, `size: float = 100.0`. Validates direction via local `_normalize_direction` (else `ValueError("direction must be RIGHT, LEFT, UP, or DOWN")`) and size positive. `render()` = `symbols.flow_arrow_commands(position=center, direction, size)`.
- **`LeaderLineComponent`**: fields `points: list[Point] = []`, `text: str | None = None`, `text_position: Point | None = None`. Requires `>=2` points (else `ValueError("...at least two points")`); if `text` given requires non-empty. `render()`: emits `signal_line_commands(points)` (a plain polyline — **note: leader lines currently render as a signal-line-styled polyline, not a special leader/arrowhead symbol** — there is no distinct leader-arrowhead geometry), then if `text` is truthy, appends a `text_label_commands` call at `text_position` or, if absent, at `points[-1]` (the leader's terminal point).

Real-world symbol represented: free-floating text callouts (`label`), directional flow indicators
independent of a specific pipe (`flow_arrow` — used e.g. standalone near an inlet), and
leader-line annotations pointing from a note to a feature (`leader_line`).

### `components/scene.py` — the composition root

- **`PIDComponentScene`** (`@dataclass`): fields `title: str`, `components: list[PIDComponent] = []`, `assumptions: list[str] = []`, `metadata: dict[str, Any] = {}`. `__post_init__`: validates `title` non-empty (stripped); validates `assumptions` is a list of strings; validates `metadata` is a dict; then **re-adds every initially-provided component through `self.add()`** (clearing `self.components` first) so that duplicate-id checking applies even to components passed in the constructor's `components=` list.
- **`add(component)`**: raises `ValueError(f"duplicate component id: {component.id}")` if any existing component shares the new one's `id`. Otherwise appends.
- **`get(component_id) -> PIDComponent`**: linear search; raises `KeyError(component_id)` if not found.
- **`all_ports() -> dict[str, Point]`**: renders every component (via `render_component`) and flattens all their ports into one dict keyed `"{component.id}.{port_name}"` (e.g. `"V201.inlet_left"`). This is how one component's pipe can be wired to another's port — e.g. `component_examples.py` reads `vessel.ports()["inlet_left"]` directly (not through `all_ports`, but the same mechanism) to connect a `PipeRunComponent`'s endpoint to the vessel's exact port coordinate.
- **`render_commands(include_standard_layers=True) -> list[dict]`**: optionally prepends `pid_standard_layers()`, then renders every component in **list order** (i.e., the order components were `add()`-ed / appeared in the JSON `components` array) and concatenates their command lists.
- **`to_command_sequence() -> dict`**: calls `render_commands()`, wraps via `symbols.wrap_commands_as_sequence(commands, summary=f"P&ID component scene: {self.title}")`, then appends to the sequence's `assumptions` list: first all of `self.assumptions` (via `.extend`), then the fixed string `"Generated from reusable P&ID components."`. Finally validates the result against the **generic command schema** (`validate_command_sequence` from `src/framework/commands/schema.py`) and raises `ValueError` with a joined bullet list of errors if invalid. This is the **only** place command-schema validation happens for the component pipeline (component_builder.py itself only validates the component-scene JSON schema, not the rendered commands — that happens implicitly through this method).
- **`summary() -> str`**: `f"{title}: {n} component(s). Components: {comma-joined ids or 'none'}."`
- **`make_component_scene(title, components) -> PIDComponentScene`**: convenience constructor that builds an empty-components scene then `.add()`s each one (equivalent to passing `components=` to the dataclass directly, since `__post_init__` does the same thing).

### `components/__init__.py` — package surface

Re-exports (and this is the exact import path used by `component_builder.py`,
`component_examples.py`, and tests): `BasePIDComponent`, `ControlValveComponent`,
`ControllerLoopComponent`, `FlowArrowComponent`, `GateValveComponent`,
`HorizontalVesselComponent`, `InstrumentBubbleComponent`, `LabelComponent`, `LeaderLineComponent`,
`PIDComponent`, `PIDComponentScene`, `PipeRunComponent`, `Point`, `PortMap`, `RenderedComponent`,
`SignalLineComponent`, `VerticalVesselComponent`, `component_text_id`, `make_component_scene`,
`normalize_point`, `offset_point`, `render_component`.

---

## 5. `component_builder.py` — JSON → command sequence algorithm

File: `src/framework/pid/component_builder.py`. Defines `PIDComponentBuildError(Exception)`.

**`_common_kwargs(data) -> dict`** (line 28): starts with `{"id": data["id"]}`, then copies over
`tag`, `center`, `metadata` from `data` *only if present* (so component dataclass defaults apply
when omitted).

**`build_component_from_data(data) -> PIDComponent`** (line 36): a single large `if/elif` chain
(not a dict dispatch table) keyed on `data.get("component_type")`. Exact mapping, all wrapped in
`_common_kwargs(data)` plus type-specific extra kwargs:

| `component_type` string | Class instantiated | Extra kwargs pulled from `data` |
|---|---|---|
| `horizontal_vessel` | `HorizontalVesselComponent` | `length=data["length"]`, `diameter=data["diameter"]` |
| `vertical_vessel` | `VerticalVesselComponent` | `height=data["height"]`, `diameter=data["diameter"]` |
| `pipe_run` | `PipeRunComponent` | `points=data["points"]`, `label=data.get("label")`, `label_position=data.get("label_position")`, `flow_direction=data.get("flow_direction")`, `flow_arrow_position=data.get("flow_arrow_position")` |
| `signal_line` | `SignalLineComponent` | `points=data["points"]` |
| `gate_valve` | `GateValveComponent` | `orientation=data["orientation"]`, `size=data.get("size", GateValveComponent.size)` (dataclass default, i.e. 120) |
| `control_valve` | `ControlValveComponent` | same pattern as gate_valve |
| `instrument_bubble` | `InstrumentBubbleComponent` | `radius=data.get("radius", InstrumentBubbleComponent.radius)` (85) |
| `controller_loop` | `ControllerLoopComponent` | `instrument_tag`, `controller_tag`, `instrument_center`, `controller_center` (all required, no `.get`), `signal_points=data.get("signal_points")`, `radius=data.get("radius", ControllerLoopComponent.radius)` |
| `label` | `LabelComponent` | `text=data["text"]`, `height=data.get("height", LabelComponent.height)` (85) |
| `flow_arrow` | `FlowArrowComponent` | `direction=data["direction"]`, `size=data.get("size", FlowArrowComponent.size)` (100.0) |
| `leader_line` | `LeaderLineComponent` | `points=data["points"]`, `text=data.get("text")`, `text_position=data.get("text_position")` |
| anything else | — | falls through to `raise PIDComponentBuildError(f"Unsupported component type: {component_type}")` |

Any `KeyError`, `TypeError`, or `ValueError` raised while constructing the component (e.g. a
dataclass `__post_init__` validation failure, or a missing required key not already caught by
schema validation) is caught and re-raised as
`PIDComponentBuildError(f"Failed to build component {data.get('id','<unknown>')}: {exc}")`.

**`build_pid_component_scene(data) -> PIDComponentScene`** (line 121) — the orchestration
algorithm:
1. Runs `validate_pid_component_scene_data(data)`; if any errors, raises
   `PIDComponentBuildError("Invalid P&ID component scene:\n- err1\n- err2...")` (joined with
   `"\n- "` bullets) **before touching any component objects**.
2. Constructs an empty `PIDComponentScene(title=data["title"], assumptions=data["assumptions"], metadata=data.get("metadata", {}))`.
3. Iterates `data["components"]` **in array order** (this determines final draw/layer-paint
   order — see §4 `render_commands`), calling `build_component_from_data(component_data)` for
   each, then `scene.add(component)`. If `scene.add` raises `ValueError` (duplicate id), it's
   caught and re-raised as `PIDComponentBuildError(str(exc))`.
4. Returns the fully populated scene.

**`render_pid_component_scene_data(data) -> dict`** (line 144) — the single public entry point
used by `src/ai/pid_component_planner.py`: `build_pid_component_scene(data)` then
`scene.to_command_sequence()`. This is where the command-schema validation from §4 implicitly
fires.

**Layer/style assignment**: there is no explicit per-component layer selection logic in
`component_builder.py` itself — every component's `render()` method already hard-codes its own
layer via the `symbols.py` functions it calls (e.g. `HorizontalVesselComponent.render()` always
draws on `PID_LAYER_EQUIPMENT` because `horizontal_vessel_commands`'s default `layer` param is
`PID_LAYER_EQUIPMENT` and no component ever overrides it). So **layer assignment is fully
deterministic and type-based, not user-configurable** through the component JSON — a
`horizontal_vessel` component can never be drawn on a different layer than
`PID_EQUIPMENT`/color 4, for instance.

---

## 6. `scene_renderer.py` — the parallel "flat scene" renderer

File: `src/framework/pid/scene_renderer.py`. Defines `PIDSceneRenderError(Exception)`.

**Important clarification of the question "is this a preview image or a synonym for building
commands"**: in this codebase, **"render" is a synonym for "build the AutoCAD command sequence,"
not for producing a bitmap/preview image.** There is no rasterization, no PIL/canvas drawing, no
image file output anywhere in this file or the component pipeline — `render_pid_scene_to_commands`
and `PIDComponentScene.to_command_sequence()`/`render_pid_component_scene_data()` all produce the
exact same *kind* of artifact: a JSON command-sequence dict meant to be replayed into AutoCAD by
`execute_command_sequence`. "Rendering" here means "turning declarative scene/component
description into imperative drawing commands," analogous to a template-rendering step, not visual
rasterization.

**`_label_position_for_pipe(points) -> [x, y]`** (line 32): a heuristic distinct from
`components/piping.py`'s `polyline_midpoint` — finds the **longest segment** of the pipe polyline
(by squared length, comparing every consecutive pair), then places the label at that segment's
midpoint, offset depending on whether the segment is more horizontal or vertical: if
`dx >= dy` (horizontal-ish segment) offset is `(-PID_PIPE_LABEL_OFFSET*1.3, +PID_PIPE_LABEL_OFFSET)` = `(-182, +140)`; else (vertical-ish) offset is `(+PID_PIPE_LABEL_OFFSET*0.45, -PID_PIPE_LABEL_OFFSET*0.25)` = `(+63, -35)`. This is a **different, more sophisticated algorithm** than the component pipeline's pipe-label placement (`PipeRunComponent.render()` just uses the middle segment, not the longest one) — a clear duplication/divergence between the two pipelines (see §8).

**`render_pid_scene_to_commands(scene) -> dict`** (line 59) — the single monolithic rendering
function for the flat-scene pipeline:
1. `validate_pid_scene(scene)` — if errors, raise `PIDSceneRenderError("Invalid P&ID scene:\n...")`.
2. `commands = pid_standard_layers()`.
3. Iterate `scene["equipment"]`: dispatch on `equipment["type"]` — `"horizontal_vessel"` →
   `horizontal_vessel_commands(center, length, diameter, tag)`; `"vertical_vessel"` →
   `vertical_vessel_commands(center, height, diameter, tag)`; anything else raises
   `PIDSceneRenderError(f"Unsupported equipment type: {equipment['type']}")` (this branch is
   currently unreachable in practice since the schema's `type` enum already restricts values to
   these two, but it is defensive dead code for forward compatibility).
4. Iterate `scene["pipes"]`: always emit `pipe_line_commands(points)`; if `pipe.get("label")`
   truthy, also emit `text_label_commands(label, _label_position_for_pipe(points), height=PID_TEXT_HEIGHT_NORMAL)`.
5. Iterate `scene["valves"]`: dispatch on `type` — `"gate_valve"` → `gate_valve_commands(center, size=valve.get("size", PID_VALVE_SIZE), orientation)`; `"control_valve"` → `control_valve_commands(...)`; else raise `PIDSceneRenderError(f"Unsupported valve type: {valve['type']}")` (again schema-enum-guarded, defensive).
6. Iterate `scene["instruments"]`: always `instrument_bubble_commands(center, tag, radius=instrument.get("radius", PID_INSTRUMENT_RADIUS))`; if `instrument.get("signal_to")` truthy, also emit `signal_line_commands(instrument["signal_to"])` — this is the flat-scene equivalent of the component pipeline's `ControllerLoopComponent`, but implemented as an *optional attribute of a single instrument* rather than a two-bubble compound component.
7. Iterate `scene["signal_lines"]`: emit `signal_line_commands(points)` for each.
8. Iterate `scene["labels"]`: emit `text_label_commands(text, position, height=label.get("height", PID_TEXT_HEIGHT_NORMAL))`.
9. Iterate `scene["flow_arrows"]`: emit `flow_arrow_commands(position, direction, size=arrow.get("size", 100))`.
10. **After all of the above**, unconditionally appends one more `TEXT` command: `text_label_commands(scene["title"], [-1600, 1600], height=PID_TEXT_HEIGHT_TITLE)` — i.e., every flat-scene render draws the scene's title as a large (height 150) title block at fixed position `[-1600, 1600]` regardless of drawing content. **The component pipeline has no equivalent automatic title text** — this is a divergence.
11. Wraps via `wrap_commands_as_sequence(commands, summary=f"P&ID scene: {scene['title']}")`, then `.extend()`s `scene.get("assumptions", [])` onto the sequence's assumptions (no extra fixed string appended, unlike the component pipeline's `"Generated from reusable P&ID components."` addition).
12. Validates the final sequence with `validate_command_sequence`; raises `PIDSceneRenderError` with joined bullets if invalid.

**`example_horizontal_separator_pid_scene() -> dict`** (line 154): a large hand-built, fully valid
flat-scene JSON example (one `V-101` horizontal vessel, 4 pipes with labels — inlet, vapor, water,
oil — 5 valves including one control valve `LV_OIL`, 4 instruments including two with `signal_to`
paths, one free label "Level Control", 4 flow arrows, 1 signal line). This is the flat-scene
equivalent of `component_examples.py`'s `horizontal_separator_component_scene`, but expressed in
the flat-scene JSON shape rather than as OOP component objects, and with slightly different tag
names (`V-101` here vs `V-201` in the component example) and different exact geometry — they are
**not** the same drawing, just thematically parallel.

**`render_example_horizontal_separator_pid() -> dict`** (line 248): trivial
`render_pid_scene_to_commands(example_horizontal_separator_pid_scene())`.

**This entire module is currently orphaned from the live API path** — grep confirms
`src/ai/pid_component_planner.py` and `src/api/routes/pid.py` only import from
`component_builder.py`/`component_schema.py`/`component_templates.py`, never from
`scene_renderer.py`/`scene_schema.py`. The flat-scene pipeline is exercised only by its own tests
(`test_pid_scene_schema.py`, `test_pid_scene_renderer.py`) and appears to be either a retained
earlier design or a reference/demo module.

---

## 7. `component_templates.py` / `component_examples.py` — deterministic fallback templates

### `component_templates.py` — the README's "resilient fallback"

Defines `PIDComponentTemplateError(Exception)` and
`validate_template_scene(scene) -> dict`: deep-copies the input scene, validates it with
`validate_pid_component_scene_data`, and raises `PIDComponentTemplateError` (joined bullet list)
if invalid, else returns the defensive copy. **Every** template builder function below calls
`validate_template_scene(scene)` as its last line before returning — so templates are guaranteed
schema-valid at construction time (this is also directly tested:
`test_horizontal_separator_template_scene_validates`, etc.).

There are exactly **three** deterministic templates, matching the README's list exactly:

#### `horizontal_separator_template_scene(title="Horizontal Separator P&ID") -> dict`
`metadata: {"source": "deterministic_template", "template_name": "horizontal_separator"}`.
Components (19 total): one `horizontal_vessel` (`id=V201`, `tag=V-201`, `center=[0,0]`,
`length=2800`, `diameter=760`); five `pipe_run`s (`P_INLET`/"3 Phase Inlet" flowing RIGHT,
`P_VAPOR`/"Vapor Outlet" flowing RIGHT, `P_OIL`/"Oil Outlet" flowing RIGHT, `P_WATER`/"Water
Outlet" flowing LEFT, `P_DRAIN`/"Drain" flowing DOWN, `P_VENT`/"Vent" flowing UP — that's actually
6, not 5); 4 valves (`XV_IN` H gate, `XV_VAPOR` H gate, `XV_WATER` H gate, `XV_DRAIN` V gate) plus
1 control valve (`LV_OIL`); 2 `instrument_bubble`s (`PT201`, `PI201`); 1 `controller_loop`
(`LC201_LOOP`, tags `LT-201`/`LC-201`, with an explicit 4-point `signal_points` routing);
2 `signal_line`s (`SIG_PT`, `SIG_PI`); 3 `label`s (`LBL_DEMISTER`="Demister Pad",
`LBL_WEIR`="Weir", `LBL_VORTEX`="Vortex Breaker"). Assumptions: `["Generated from deterministic
horizontal separator component template.", "Schematic is for concept review and requires
engineering verification."]`.

#### `vertical_vessel_template_scene(title="Vertical Vessel P&ID") -> dict`
`metadata: {"source": "deterministic_template", "template_name": "vertical_vessel"}`. Components
(14 total): one `vertical_vessel` (`V301`/`V-301`, `height=1900`, `diameter=720`); 3 `pipe_run`s
(`P_FEED`="Feed Inlet" RIGHT, `P_VAPOR`="Vapor Outlet" RIGHT, `P_LIQUID`="Liquid Outlet" RIGHT); 2
gate valves (`XV_FEED`, `XV_VAPOR`) + 1 control valve (`LV_LIQUID`); 2 instrument bubbles
(`PT301`, `TI301`); 1 controller loop (`LC301_LOOP`, `LT-301`/`LC-301`); 2 signal lines
(`SIG_PT`, `SIG_TI`); 2 labels (`LBL_LEVEL`="Level Control", `LBL_TEMP`="Temperature").

#### `pump_tank_template_scene(title="Pump and Tank P&ID") -> dict`
`metadata: {"source": "deterministic_template", "template_name": "pump_tank"}`. Components (15
total): one `vertical_vessel` used **as the tank** (`T101`/`T-101`, `height=1500`,
`diameter=760`); a label `LBL_TANK`="Tank T-101"; **the pump itself is represented by an
`instrument_bubble` component** (`id=P101_MARKER`, `tag="P-101"`, `radius=110`) plus a separate
label `LBL_PUMP`="Pump P-101" — i.e. **there is no dedicated pump symbol/shape anywhere in this
framework**; a pump is always just an oversized instrument-bubble circle with a tag, per the
explicit assumption text `"Pump is represented by a labeled circular placeholder."`; 2 pipe runs
(`P_SUCTION`="Suction" RIGHT, `P_DISCHARGE`="Discharge" RIGHT); 2 gate valves (`XV_SUCTION`,
`XV_DISCHARGE`) + 1 control valve (`FV_DISCHARGE`); 2 instrument bubbles (`PI101`, `FI101`); 2
signal lines (`SIG_PI`, `SIG_FI`).

**`available_pid_component_templates() -> dict[str, Callable[[], dict]]`**: `{"horizontal_separator": horizontal_separator_template_scene, "vertical_vessel": vertical_vessel_template_scene, "pump_tank": pump_tank_template_scene}` — exactly the 3 keys named in the README.

**`choose_pid_component_template(user_request: str) -> tuple[str, dict]`** — the exact keyword
heuristic used to pick a fallback template from free text (all case-insensitive, checked in this
priority order, first match wins):
1. If any of `["pump", "suction", "discharge", "tank"]` appears → `"pump_tank"`.
2. Elif any of `["vertical", "column", "tower", "vessel vertical"]` appears → `"vertical_vessel"`.
3. Elif any of `["separator", "3 phase", "three phase", "oil", "water", "vapor", "horizontal"]` appears → `"horizontal_separator"`.
4. **Else** (no keyword matched at all) → `"horizontal_separator"` is the **hard-coded default
   template** for any unrecognized request (confirmed by
   `test_choose_unknown_prompt_defaults_to_horizontal_separator`).

Returns `(template_name, available_pid_component_templates()[template_name]())` — i.e. the
chosen name plus a fresh, already-schema-validated scene dict.

### How/when the fallback actually triggers (cross-referenced with `src/ai/pid_component_planner.py`, out of scope but read for this handoff)

`plan_pid_component_scene_resilient(user_request, drawing_style, allow_template_fallback=True, template_first=False)`:
- If `template_first=True`: **skips the AI planner entirely** and calls
  `choose_pid_component_template(user_request)` directly, tagging
  `metadata["planner_strategy"]="template_selected"`, `metadata["ai_planner_attempted"]=False`.
  (`/api/pid/generate` in `src/api/routes/pid.py:44` always passes `template_first=False`, so this
  branch is not reachable from the live HTTP API — only from direct Python callers/tests.)
- Otherwise (the live-API path): calls `plan_pid_component_scene(user_request, drawing_style)`
  (which calls `ask_ai(...)` with `PID_COMPONENT_SCENE_SCHEMA` + `PID_COMPONENT_PLANNER_SYSTEM_PROMPT`,
  `max_retries=2`, `max_tokens=5000`, then re-validates the AI's JSON with
  `validate_pid_component_scene_data`, raising `ValueError` if the AI's output doesn't conform even
  after `ask_ai`'s internal retries). **Any exception at all** from that call (validation failure,
  network/AI error, malformed JSON, etc.) is caught by a bare `except Exception as exc:` — this is
  literally the "if the AI planner fails or returns invalid JSON, a resilient fallback picks a
  deterministic component template" behavior from the README.
  - If caught and `allow_template_fallback=False`: the exception is simply re-raised (no
    fallback) — confirmed by `test_resilient_planner_reraises_when_fallback_disabled`.
  - If caught and `allow_template_fallback=True` (the default, and what `/api/pid/generate` uses):
    calls `choose_pid_component_template(clean_request)` — **the fallback template selection uses
    the ORIGINAL user request text**, not any partial/malformed AI output — appends the fixed
    assumption string `"AI component planner failed, so a deterministic template fallback was
    used. Review and edit the result as needed."`, and stamps `metadata` with
    `planner_strategy="template_fallback"`, `fallback_used=True`,
    `fallback_reason=f"{type(exc).__name__}: {exc}"`, `template_name=<chosen>`,
    `ai_planner_attempted=True`, `ai_planner_error_type=type(exc).__name__`,
    `ai_planner_error=str(exc)`.
  - If the AI planner succeeds outright: stamps `planner_strategy="ai_component_planner"`,
    `fallback_used=False`, `ai_planner_attempted=True`, both error fields `None`.
- `plan_and_render_pid_component_scene_resilient(...)` wraps the above then calls
  `render_pid_component_scene_data(scene_data)` (→ `component_builder.py`) to get the final
  command sequence, and surfaces `planner_strategy`/`fallback_used`/`fallback_reason`/
  `template_name` at the top level of its return dict (pulled from `scene_data["metadata"]`) — and
  these exact keys are what `pid.py`'s `/generate` response echoes back to the HTTP caller
  (`planner_strategy`, `fallback_used`, `fallback_reason`, `template_name` — see route body at
  `pid.py:83-86`).

`test_pid_component_planner.py` confirms this contract precisely: e.g.
`test_resilient_planner_returns_template_scene_when_strict_planner_fails` monkeypatches
`plan_pid_component_scene` to `raise RuntimeError("invalid JSON")`, calls
`plan_pid_component_scene_resilient("horizontal 3 phase separator with oil water vapor")`, and
asserts `metadata["template_name"] == "horizontal_separator"` and
`"RuntimeError: invalid JSON" in metadata["fallback_reason"]`.

### `component_examples.py` — hand-authored demo scenes (OOP, not template JSON)

Distinct purpose from `component_templates.py`: these functions build `PIDComponentScene` objects
directly using the Python component classes (imported from `src.framework.pid.components`) and
**exploit component ports** (e.g. `vessel.ports()["inlet_left"]`) to wire pipe endpoints exactly
to vessel connection points — something the raw-JSON templates cannot do (JSON templates hard-code
approximate coordinates instead, e.g. `[-1400, 0]` near but not exactly touching the vessel edge
port). Three scenes, each thematically matching a template but with its own distinct geometry/IDs:

- **`horizontal_separator_component_scene() -> PIDComponentScene`**: title "Horizontal Separator
  Component P&ID". Builds a `V201`/`V-201` horizontal vessel (`length=2800, diameter=760`),
  captures its `ports()`, then wires 6 `PipeRunComponent`s directly to `ports["inlet_left"]`,
  `ports["vapor_top"]`, `ports["oil_bottom_right"]`, `ports["water_bottom_left"]`,
  `ports["bottom_center"]` (drain), `ports["top_center"]` (vent). Same valve/instrument/label
  layout pattern as the JSON template (5 valves, 2 bubbles, 1 controller loop `LC201_LOOP`, 2
  signal lines, 3 labels: Demister Pad/Weir/Vortex Breaker). `render_horizontal_separator_component_pid() -> dict` = `.to_command_sequence()`.
- **`vertical_vessel_component_scene() -> PIDComponentScene`**: title "Vertical Vessel Component
  P&ID". `V301`/`V-301` vertical vessel (`height=1900, diameter=720`); pipe runs wired to
  `ports["left"]` (feed), `ports["top"]` (vapor), `ports["bottom"]` (liquid), and a `P301_RECYCLE`
  pipe wired to `ports["right"]` — **this recycle-return pipe with a `right`-port connection does
  NOT exist in the equivalent `vertical_vessel_template_scene()` JSON template**, which only has 3
  pipe runs, not 4 — a concrete content divergence between the "example" and "template" versions
  of the same nominal scenario. `render_vertical_vessel_component_pid()`.
- **`pump_tank_component_scene() -> PIDComponentScene`**: title "Pump and Tank Component P&ID".
  `T101`/`T-101` vertical-vessel-as-tank (`height=1500, diameter=760`), pump represented the same
  way as the template — `InstrumentBubbleComponent(id="P101_PLACEHOLDER", tag="P-101", radius=110)`
  (note: **different id** than the template's `P101_MARKER` for the same concept) plus a
  `LBL101_PUMP` label; suction pipe wired to `tank_ports["bottom"]`. `render_pump_tank_component_pid()`.

**`available_component_examples() -> dict[str, Callable[[], PIDComponentScene]]`**: same 3 keys
(`horizontal_separator`, `vertical_vessel`, `pump_tank`) but mapped to scene-object builders, not
JSON-dict builders — a different callable type than `available_pid_component_templates()`.

**`render_component_example(name) -> dict`**: `available_component_examples()[name]().to_command_sequence()`; raises `ValueError(f"Unknown component example: {name}")` for unrecognized names.

**Neither `component_examples.py` function is called by the live `/api/pid/generate` or
`/api/pid/approve` routes** — they exist purely as demo/reference scenes exercised by
`test_pid_component_examples.py`, and presumably by any demo/CLI script elsewhere in the repo (not
found in this scope).

---

## 8. Test coverage summary

All 14 test files listed in scope were read in full. Coverage is thorough and largely 1:1 with
public functions:

- **`test_pid_symbols.py`** (26 tests): validates every `symbols.py` function individually plus a
  combined "mini P&ID" integration test; explicitly asserts exact output shape for
  `pipe_line_commands`, exact tag-height bounds (`60 <= height <= 120`) for vessel tags, exact
  error messages for invalid orientation/negative dimensions.
- **`test_pid_scene_schema.py`** (11 tests): schema-only tests for the flat-scene shape — missing
  required fields, wrong `schema_version`, conditional length/height requirement per equipment
  type, invalid enum values, additional-properties rejection, `is_valid_pid_scene` true/false.
- **`test_pid_scene_renderer.py`** (18 tests): renderer-level tests including the full
  `example_horizontal_separator_pid_scene` — notably asserts `len(commands) > 40` and checks for
  specific expected TEXT values (`V-101`, `3 Phase Inlet`, `Vapor Outlet`, `Water Outlet`,
  `Oil Outlet`, `PT-101`, `PI-101`, `LT-101`, `LC-101`) and vessel-tag height `<=140`.
- **`test_pid_component_schema.py`** (14 tests): mirrors the scene-schema tests but for the
  component shape, plus a comprehensive `test_every_supported_component_type_can_appear_in_valid_scene`
  that instantiates all 11 component types in one scene and asserts zero validation errors —
  effectively the canonical "what does a full valid component JSON look like" reference.
- **`test_pid_component_builder.py`** (16 tests): covers `build_component_from_data` for every one
  of the 11 types individually (isinstance checks), unsupported-type error, full scene build,
  component count, `all_ports()` containing `"V201.inlet_left"`, render→validate round trip,
  invalid-scene error, and duplicate-id error.
- **`test_pid_component_examples.py`** (15 tests): validates all 3 example scenes render to valid
  command sequences, checks exact expected label/tag text sets per scene, checks
  `available_component_examples()` keys, checks unknown-name `ValueError`, checks every example has
  `>=8` components and every rendered example has `>25` commands, checks scene titles appear in
  `scene.summary()`.
- **`test_pid_component_templates.py`** (13 tests): validates all 3 templates individually,
  `available_pid_component_templates()` keys, exact `choose_pid_component_template` routing for
  representative phrases per category plus the unknown-defaults-to-horizontal_separator case,
  exact expected text sets per template, full render+validate for every template.
- **`test_pid_components_base.py`** (11 tests): `normalize_point` (2D pass-through, 3D-drops-Z,
  rejects length-1), `offset_point`, `component_text_id` (format + error cases),
  `BasePIDComponent` id/center validation, `render()` NotImplementedError, `render_component()`
  round trip using a local `FakeComponent` test double.
- **`test_pid_equipment_components.py`** (6 tests): exact port dictionaries for both vessel types
  (e.g. `inlet_left == [-1300.0, 0.0]` for default `length=2600`, `top == [0.0, 900.0]` for default
  `height=1800`), render-in-scene validation, positive-dimension error messages.
- **`test_pid_instrument_components.py`** (5 tests): tag-required error for `InstrumentBubbleComponent`,
  exact port set/values, render validation, `ControllerLoopComponent` render validation and exact
  `ports()` dict.
- **`test_pid_piping_components.py`** (6 tests): point normalization (3-tuple → 2-list drop-Z),
  exact start/end ports, label/flow-arrow render validation, `<2`-points error, `SignalLineComponent`
  render validation.
- **`test_pid_valve_components.py`** (6 tests): exact port dicts for H/V gate valves at `size=120`
  (`left=[-60,0], right=[60,0]` / `bottom=[0,-60], top=[0,60]`), render validation for both valve
  types, invalid-orientation and invalid-size error messages.
- **`test_pid_annotation_components.py`** (6 tests): label text-required error, render validation
  for label/flow-arrow (parametrized over all 4 directions)/leader-line, invalid-direction error,
  leader-line `<2`-points error.
- **`test_pid_component_planner.py`** (out of this module's scope but read for the handoff
  contract, 15 tests + 1 live-AI-gated test): confirms `ask_ai` is called with
  `schema=PID_COMPONENT_SCENE_SCHEMA`, `system_prompt=PID_COMPONENT_PLANNER_SYSTEM_PROMPT`,
  `max_retries=2`, `max_tokens=PID_COMPONENT_PLANNER_MAX_TOKENS` (5000); confirms
  `schema_version` auto-injection when the AI omits it; confirms invalid AI JSON raises
  `ValueError("P&ID component scene failed validation")`; confirms the full resilient
  fallback contract described in §7 including exact metadata field values.

**Nothing tests `/api/pid/generate` or `/api/pid/approve` directly at the HTTP layer** within this
scope (no `test_pid_routes.py` was listed) — route-level behavior is only inferable from reading
`src/api/routes/pid.py` directly, not from an automated test in the provided list.

---

## 9. Cross-cutting observations, risks, and inconsistencies

1. **Two independent, non-interoperating pipelines coexist**: the flat "scene" pipeline
   (`scene_schema.py`/`scene_renderer.py`) and the OOP "component" pipeline
   (`component_schema.py`/`component_builder.py`/`components/`). Only the component pipeline is
   wired to the live `/api/pid/generate` API (via `src/ai/pid_component_planner.py`). The flat
   pipeline appears to be a superseded/earlier design retained for its own tests and one worked
   example (`example_horizontal_separator_pid_scene`). A future agent should confirm with the repo
   owner whether `scene_schema.py`/`scene_renderer.py` are dead code safe to delete, or intentionally
   kept as a simpler/alternate API surface for some other future consumer.

2. **Pipe-label placement is implemented twice, differently**: `components/piping.py`'s
   `polyline_midpoint()` picks the polyline's *middle segment*; `scene_renderer.py`'s
   `_label_position_for_pipe()` picks the polyline's *longest segment* with orientation-aware
   offsets. These produce different label placements for the same routed polyline depending on
   which pipeline renders it — a genuine duplicated-logic risk if one is bugfixed without the
   other.

3. **No dedicated pump symbol exists anywhere.** Every "pump" in this framework (both the
   `pump_tank` template and the `pump_tank` component example) is literally an
   `InstrumentBubbleComponent`/`instrument_bubble_commands` circle with a tag, plus a nearby free
   `label`. There is no pump-specific geometry (no impeller/triangle/kidney shape). Anyone asked
   to "add a real pump symbol" should add a new function to `symbols.py` (e.g.
   `centrifugal_pump_commands`) and a new component class in `components/equipment.py`, then wire
   it into `component_builder.py`'s dispatch chain and `component_schema.py`'s `oneOf` list — none
   of that currently exists.

4. **`ControllerLoopComponent` duplicates `instrument.signal_to` from the flat-scene schema** as a
   different abstraction: the component pipeline models a controller loop as one compound
   component with two named centers, whereas the flat-scene pipeline models the same real-world
   concept as an optional attribute (`signal_to`) hanging off a single `instrument` entry that
   only draws one bubble. These are not interchangeable and there's no shared code between them
   beyond both ultimately calling `instrument_bubble_commands`/`signal_line_commands`.

5. **Component-schema `oneOf` validation error messages can be confusing** (see §3b) because a
   component object that's missing one required field for its own declared `component_type` will
   fail validation against all 11 `oneOf` branches (since `component_type` is a `const` per
   branch, and Draft-07 doesn't short-circuit on the matching branch) — the actual root cause
   (one missing field) can get buried among 10 other "wrong component_type" mismatches in the
   raw jsonschema error list. `validate_pid_component_scene_data`'s formatting doesn't specifically
   mitigate this (no "best matching oneOf branch" heuristic) — a future agent debugging why a
   generated scene fails validation should expect potentially noisy/redundant error lists from this
   function when the problem is a single missing field on one component, not sort by first error
   and assume that's the true cause.

6. **3D input is silently truncated to 2D.** `normalize_point()` in `components/base.py` accepts
   3-element points and discards the third coordinate without warning. If any caller upstream
   (e.g. a shared coordinate utility also used by the 3D `cad3d` subsystem) ever passes a
   Z-coordinate meant to matter, it will vanish silently here. This is presumably intentional
   (P&ID is inherently a flat schematic), but it's worth flagging since there's no runtime warning
   or logged assumption about it — it's purely implicit in `normalize_point`'s docstring
   ("Normalize a 2D/3D coordinate to a two-number coordinate").

7. **`tag` fallback to `id` is easy to miss.** `HorizontalVesselComponent.render()` and
   `VerticalVesselComponent.render()` both use `tag=self.tag or self.id` — so a vessel component
   JSON that omits `tag` (which the schema does NOT require to be omitted — `tag` is actually
   listed as **required** for `horizontal_vessel`/`vertical_vessel` in `component_schema.py`, so
   this fallback path is schema-unreachable for those two types specifically) would draw its raw
   `id` string as the vessel's engineering tag. Because the schema makes `tag` required for
   vessels, this fallback is effectively dead code for those two component types, but it remains
   live and reachable for any future component type added without a required `tag` — worth
   remembering if `tag` is ever relaxed to optional for vessels.

8. **Sizing/geometry constants are explicitly tuned for demo/presentation legibility, not
   engineering accuracy** — the `_equipment_tag_height` docstring in `symbols.py` says so directly
   ("more suitable for demo videos and client presentation screenshots"), and every "assumptions"
   list injected by the templates/examples/planner includes disclaimers like "Schematic is for
   concept review and requires engineering verification" / "not fabrication-grade." Any consumer
   treating this output as engineering-accurate P&ID should be redirected to these disclaimers.

9. **`component_templates.py` and `component_examples.py` are NOT kept in sync** for the same
   nominal scenario (see §7's vertical-vessel recycle-pipe divergence, and the differing
   `id`/`center` details in `pump_tank`). If a future task is "update the pump_tank scenario," both
   files likely need parallel edits, and it's easy to update one and forget the other since they
   serve different call paths (fallback template vs. hand-authored example/demo) but represent
   conceptually the same idea.

10. **No unit/scale system beyond "millimeters" convention.** All coordinate values are bare
    floats; nothing in any schema encodes units, and the executor presumably assumes AutoCAD's
    drawing units already match millimeters (out of scope to confirm here, but worth flagging as a
    risk if a drawing template with different `INSUNITS` is ever the target).

11. **`instrument_bubble` used both for real instruments and as the pump placeholder** means a
    generated scene's `instrument_bubble` components are semantically overloaded — a future agent
    filtering/counting "real instruments" in a scene (e.g. for a bill-of-instruments report) must
    not naively treat every `instrument_bubble` as a process instrument; some are pump markers
    (distinguishable only by convention — e.g. tag prefix `P-` vs `PI-`/`PT-`/`LT-` — not by any
    schema-level type distinction).

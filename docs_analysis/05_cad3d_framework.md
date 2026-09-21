# `src/framework/cad3d/` — CAD3D Subsystem Deep Dive

This document is an exhaustive reference to the CAD3D subsystem: deterministic 3D piping/equipment
scene generation, editing, persistence, and AutoCAD COM execution. It is meant to let an agent work
in this code without re-reading the source.

All paths below are relative to the project root `F:\RC-Projects\autocad-ai\autocad-ai` unless given
as absolute Windows paths.

---

## 1. Role in the system

CAD3D is the **3D counterpart** to the 2D P&ID framework (`src/framework/pid/`, documented
separately). Where the PID framework produces flat 2D schematic drawings (symbols, lines, text) on a
single drawing plane, CAD3D produces **3D solid/placeholder geometry** (cylinders, boxes, lines,
text) laid out in millimeter XYZ space to represent a piping isometric-style layout: tanks, vessels,
pumps, heat exchangers, valves, flanges, nozzles, pipe runs, structural/pipe supports, skid bases, and
text labels.

The subsystem itself (everything under `src/framework/cad3d/`) is purely **deterministic**: JSON
schema validation, dataclass component builders, port/routing geometry math, edit-plan application,
scene persistence, and AutoCAD COM execution. It contains **no LLM calls**. The AI layer that
produces/edits scene JSON lives outside this folder, in `src/ai/cad3d_scene_planner.py` (function
`plan_cad3d_scene_resilient`, strategy metadata `"ai_cad3d_scene_planner"`) and
`src/ai/cad3d_edit_planner.py` (`plan_cad3d_edit_resilient`, strategy `"ai_cad3d_edit_planner"` /
fallback `"deterministic_edit_fallback"`). Those AI planner modules import
`src.framework.cad3d.component_templates.choose_cad3d_template` as their deterministic fallback when
the LLM call fails or produces an invalid plan, and import `scene_editor`/`edit_schema` to validate
and apply LLM-authored edit plans.

The FastAPI HTTP surface is `src/api/routes/cad3d.py` (`APIRouter(prefix="/api/cad3d")`) with four
endpoints:
- `POST /api/cad3d/generate` — plans (AI or example) a scene, stores it in `CAD3DSceneStore`, returns
  a `token`.
- `GET /api/cad3d/state`, `/state/latest`, `/state/{token}` — read back stored scene records.
- `POST /api/cad3d/edit` — plans and applies an edit to an existing stored scene (by token or latest),
  optionally executes it into AutoCAD immediately (`request.execute`).
- `POST /api/cad3d/approve` — takes a previously `/generate`d token (kept in the in-process
  `_CAD3D_CACHE` dict, not the persistent store) and executes it into AutoCAD via COM.

Analogy to the PID framework: PID has `component_templates.py`/`component_examples.py`/
`scene_editor.py`/`scene_schema.py` equivalents too (`src/framework/pid/component_templates.py` is
imported by `src/ai/pid_component_planner.py` the same way). The two frameworks are structurally
parallel (scene schema → component builders → routing/ports → edit schema/editor → store → COM
executor) but are **independent implementations** with no shared base classes — CAD3D works in 3D
mm-space with solids (cylinders/boxes) via `AddCylinder`/`AddBox`/`AddLine`/`AddText`, while PID
works in 2D with lines/circles/polylines/block inserts. Do not assume behavior transfers between them.

---

## 2. Scene schema (`scene_schema.py`)

`CAD3D_SCENE_SCHEMA_VERSION = "1.0"`. Schema object is `CAD3D_SCENE_SCHEMA` (JSON Schema Draft 7,
compiled once into module-level `_VALIDATOR = Draft7Validator(...)`).

### Top-level shape (`additionalProperties: False`)

```json
{
  "schema_version": "1.0",
  "title": "<non-empty string>",
  "units": "mm",
  "assumptions": ["<string>", ...],
  "metadata": {"...": "..."},
  "components": [ {...}, ... ]   // minItems: 1
}
```
Required top-level keys: `schema_version`, `title`, `units`, `assumptions`, `components`.
`units` must be the literal `"mm"` (enum with a single value) — **millimeters is the only supported
unit**, and there is no unit-conversion helper anywhere in this subsystem. `metadata` is optional,
free-form object. `components` is a JSON-Schema `oneOf` list — each entry must match exactly one of
14 component sub-schemas (component type is discriminated by the `component_type` field, a JSON
Schema `const`).

Coordinate system: every point (`center`, `points[]`, `position`) is a 3-element `[x, y, z]` number
array (`_POINT3_SCHEMA`); no separate rotation/quaternion field — orientation is instead expressed via
a coarse `orientation` enum of `"X"`/`"Y"`/`"Z"` (axis-aligned only; no arbitrary rotation is
representable in the schema). All dimensions (`diameter`, `height`, `length`, `width`, `thickness`,
`clearance`) use `_POSITIVE_NUMBER_SCHEMA` (`exclusiveMinimum: 0`).

Every component sub-schema shares a base via `_base_properties(component_type)`:
`component_type` (const), `id` (non-empty string, **required on all types**), `tag` (optional
non-empty string), `center` (optional point3), `metadata` (optional object). Each sub-schema layers
`additionalProperties: False`, so unknown fields on a component are a validation error.

### Per-component-type fields (all 14 `oneOf` branches)

| `component_type` | Required fields (beyond `component_type`, `id`) | Extra optional/typed fields |
|---|---|---|
| `vertical_tank_3d` | `tag`, `center`, `diameter`, `height` | `color` (integer) |
| `horizontal_vessel_3d` | `tag`, `center`, `diameter`, `length`, `orientation` | `orientation` ∈ {X,Y} |
| `heat_exchanger_3d` | `tag`, `center`, `length`, `diameter`, `orientation` | `orientation` ∈ {X,Y} |
| `pump_placeholder_3d` | `tag`, `center`, `length`, `width`, `height` | — |
| `valve_placeholder_3d` | `center`, `length`, `width`, `height`, `orientation` (tag NOT required) | `orientation` ∈ {X,Y,Z}, `valve_type` (string) |
| `nozzle_3d` | `center`, `diameter`, `length`, `orientation` | `orientation` ∈ {X,Y,Z} |
| `flange_3d` | `center`, `diameter`, `thickness`, `orientation` | `orientation` ∈ {X,Y,Z} |
| `support_leg_3d` | `center`, `diameter`, `height` | — |
| `saddle_support_3d` | `center`, `length`, `width`, `height` | — |
| `pipe_support_3d` | `center`, `height`, `width`, `depth` | — |
| `pipe_run_3d` | `points` (≥2 point3 array), `diameter` | `visual_style` ∈ {centerline, solid, solid_with_centerline}, `draw_centerline` (bool) |
| `pipe_connection_3d` (logical, non-geometric) | `from_port`, `to_port`, `diameter` | `tag`, `routing_style` ∈ {direct, orthogonal}, `clearance` (positive number), `axis_order` (array of 1-3 of X/Y/Z), `metadata` |
| `skid_base_3d` | `center`, `length`, `width`, `height` | — |
| `box_3d` | `center`, `length`, `width`, `height` | — |
| `label_3d` | `text`, `position` (point3, **not** `center`), `height` | — |

Notes:
- `pipe_connection_3d` and `label_3d` are defined as raw inline schema objects (not via
  `_component_schema` helper) because they diverge from the common shape: `pipe_connection_3d` has no
  `center` and instead has `from_port`/`to_port` string references; `label_3d` uses `position` instead
  of `center`.
- `pipe_connection_3d` is a **logical/unexpanded** component — it never gets a COM executor handler
  (see §8); it must be expanded into `pipe_run_3d` via `routing.expand_pipe_connections` before
  execution.
- `valve_placeholder_3d` does not require `tag` (all equipment types otherwise require `tag` when
  it's in the base-required list, but valve's base list explicitly omits it).

### Validation helpers
- `validate_cad3d_scene(data: dict) -> list[str]` — runs `_VALIDATOR.iter_errors`, sorts errors by
  `(path, message)`, formats each as `"root.path[index]: message"` via `_format_error`/`_format_path`.
  Returns `[]` when valid.
- `is_valid_cad3d_scene(data: dict) -> bool` — `not validate_cad3d_scene(data)`.

---

## 3. Component architecture

### Base contract — `components/base.py`

- `Point3D = list[float]`, `Port3D = dict[str, Any]`, `PortMap3D = dict[str, Port3D]`.
- Free functions:
  - `normalize_point3(point)` — accepts a 2 or 3-element list/tuple, returns `[x, y, z]` floats
    (z defaults to `0.0` for 2-element input). Raises `ValueError` otherwise.
  - `normalize_vector3(vector)` — requires exactly 3 elements and non-zero; raises `ValueError` on a
    zero vector.
  - `offset_point3(point, dx=0, dy=0, dz=0)` — returns point + offset.
  - `make_port3(position, direction, diameter=None, port_type=None) -> Port3D` — builds
    `{"position": [...], "direction": [...]}` plus optional `"diameter"` (must be `> 0`) and `"type"`
    (non-empty string, stripped).
- `CAD3DComponent` — a `Protocol` (structural typing, not an ABC) requiring `id: str`,
  `tag: str | None`, `ports() -> PortMap3D`, `to_scene_component() -> dict`, `summary() -> str`.
- `BaseCAD3DComponent` — the concrete `@dataclass` every real component subclasses. Fields: `id: str`,
  `tag: str | None = None`, `center: Point3D = [0,0,0]`, `metadata: dict = {}`. `__post_init__`
  strips/validates `id` (non-empty), `tag` (non-empty if provided), normalizes `center` via
  `normalize_point3`, and requires `metadata` to be a dict. Default `ports()` returns `{}`;
  `to_scene_component()` raises `NotImplementedError` (subclasses must override); `summary()` returns
  `"ClassName(id=..., tag=...)"`.
- `RenderedCAD3DComponent` (dataclass): `component_id`, `component_type`, `scene_component` (dict),
  `ports` (PortMap3D), `summary` (str) — the output of:
- `render_cad3d_component(component) -> RenderedCAD3DComponent` — calls `component.to_scene_component()`
  and `component.ports()`, packages the result; `component_type` is read from
  `scene_component.get("component_type", component.__class__.__name__)`.

Every concrete component subclass:
1. Is a `@dataclass` extending `BaseCAD3DComponent` with extra numeric/string fields (defaults given).
2. Overrides `__post_init__` to call `super().__post_init__()` then validate/coerce its own fields
   (positive-number checks via a shared `_validate_positive(value, name)` helper defined in
   `components/equipment.py` and re-imported by `fittings.py`, `supports.py`, `valves.py`).
3. Overrides `ports()` to return named `Port3D` entries (each built with `make_port3`), representing
   physical connection points in local/world space (ports are **not** relative offsets; they're
   already computed in absolute scene coordinates using `self.center`).
4. Overrides `to_scene_component()` to emit the exact dict shape the schema (§2) expects for that
   `component_type` — including `metadata` always, and conditionally including `tag` only if it's not
   `None` (except `VerticalTank3DComponent`/`HorizontalVessel3DComponent`/`HeatExchanger3DComponent`/
   `PumpPlaceholder3DComponent`, which always include `"tag": self.tag` even if `None` — a minor
   inconsistency, see §9).

### `equipment.py` — tanks, vessels, pumps, generic boxes/skids

- `VerticalTank3DComponent(diameter=2000.0, height=5000.0)` — represents a vertical process
  tank/vessel. Ports: `top`/`bottom` (±Z, diameter × 0.15), `side_left`/`side_right` (∓X/±X at
  mid-height, diameter × 0.12). Executor draws it as **one `AddCylinder`** standing on Z (see §8).
- `HorizontalVessel3DComponent(diameter=1400.0, length=4000.0, orientation="X"|"Y")` — a horizontal
  drum/separator. Ports: `end_a`/`end_b` (axial ends, diameter × 0.15), `top`/`bottom` (±Z at
  diameter × 0.12). Executor: `AddCylinder` then `Rotate3D` if orientation is X or Y (Z is the
  cylinder's native axis).
- `HeatExchanger3DComponent(length=2500.0, diameter=600.0, orientation="X"|"Y")` — shell-and-tube
  exchanger placeholder. Ports: `inlet`/`outlet` only (axial ends, diameter × 0.25). Same
  cylinder+rotate execution as vessel.
- `PumpPlaceholder3DComponent(length=900.0, width=600.0, height=500.0)` — a box placeholder for a
  pump. Ports: `suction`/`discharge` (∓X/±X ends, width × 0.25). Executor draws as `AddBox`.
- `SkidBase3DComponent(length=8000.0, width=3500.0, height=250.0)` — a flat skid/baseplate box, no
  `ports()` override (inherits empty `{}`). `to_scene_component()` intentionally omits `tag` entirely
  (not even conditionally) — the field is absent regardless of `self.tag`.
- `Box3DComponent(length=1000.0, width=1000.0, height=1000.0)` — generic placeholder box, no ports.
  Conditionally includes `tag` only if not None (the "normal" pattern most other components follow).

### `fittings.py` — nozzles and flanges

- Shared helpers: `_validate_orientation_xyz(orientation)` (normalizes/validates to X/Y/Z) and
  `_axis_points(center, length, orientation)` (returns `(point_a, point_b, dir_a, dir_b)` along the
  given axis, centered on `center`) — both are **re-imported by `valves.py`** (see below), so this
  module doubles as a shared-geometry module for fittings and valves.
- `Nozzle3DComponent(diameter=150.0, length=400.0, orientation="X")` — represents a nozzle stub
  (e.g. equipment connection point). Ports: `base`/`tip` at the two axis ends, `port_type`
  `"nozzle_base"`/`"nozzle_tip"`. Executor draws as an oriented `AddCylinder`.
- `Flange3DComponent(diameter=250.0, thickness=80.0, orientation="X")` — a flange disc. Ports:
  `face_a`/`face_b` at the two thickness-axis faces, `port_type` `"flange_face"`. Executor draws as an
  oriented `AddCylinder` using `thickness` as the cylinder length.

### `piping.py` — pipe centerlines

- `vector_between_points(a, b) -> Point3D` — normalized unit vector from `a` to `b` (uses
  `normalize_point3`/`normalize_vector3`).
- `PipeRun3DComponent(points: list[Point3D] = [], diameter=100.0)` — represents a routed pipe as an
  ordered polyline of ≥2 points (validated in `__post_init__`; raises `ValueError` if `< 2` points or
  non-positive diameter). Ports: `start` (direction pointing *back* from point[1]→point[0]) and `end`
  (direction pointing forward from point[-2]→point[-1]), both with `port_type="pipe_end"`.
  `to_scene_component()` includes `tag` only if not None. This is the **only** component that carries
  an ordered multi-point path rather than a single `center`.

### `supports.py` — structural/pipe supports

- `SupportLeg3DComponent(diameter=120.0, height=1000.0)` — a vertical equipment support leg. Ports:
  `top`/`bottom` (±Z at half-height), `port_type` `"support_top"`/`"support_bottom"`. Executor: an
  oriented cylinder along Z (using `height` as cylinder length).
- `SaddleSupport3DComponent(length=700.0, width=350.0, height=500.0)` — a saddle support for
  horizontal vessels. No `ports()` override. Executor: `AddBox`.
- `PipeSupport3DComponent(height=800.0, width=300.0, depth=300.0)` — a pipe-rack style support.
  Ports: `top` only (width used as the port diameter proxy), `port_type="pipe_support_top"`.
  Executor: `AddBox` using `(width, depth, height)` as box dims.

### `valves.py` — valve placeholders

- `ValvePlaceholder3DComponent(length=400.0, width=300.0, height=300.0, orientation="X", valve_type="gate")`
  — imports `_axis_points`/`_validate_orientation_xyz` from `fittings.py` and `_validate_positive` from
  `equipment.py` (no new geometry code of its own). `valve_type` is a free-form non-empty string
  (`"gate"`, `"check"`, `"control"`, etc. seen in example/template data — **not schema-constrained**,
  any non-empty string is accepted by both the dataclass and the JSON schema). Ports: `inlet`/`outlet`
  at the two length-axis ends, diameter = `min(width, height) * 0.5`, `port_type="valve_end"`.
  Executor draws as `AddBox` (i.e. valve is visually just a box, same as pump — there's no
  valve-specific geometry, only the `valve_type` string tag distinguishes it semantically).

### `annotations.py` — text labels

- `Label3DComponent(text="", height=250.0)` — validates `text` non-empty and `height > 0`. **No**
  `ports()` override (labels have no connection points). `to_scene_component()` maps
  `self.center` → the schema's `position` field (the dataclass field is still named `center` for
  consistency with the base class, but the JSON key emitted is `position`, matching the schema's
  `label_3d` branch). Executor draws via `AddText`.

### `scene.py` — the composable scene container

- `CAD3DComponentScene` (dataclass): `title: str`, `components: list[CAD3DComponent] = []`,
  `assumptions: list[str] = []`, `units: str = "mm"` (must literally be `"mm"` or raises), `metadata: dict = {}`.
  `__post_init__` validates title/units/assumptions/metadata, then re-adds all initial components one
  by one through `self.add()` (so duplicate-ID checking applies even to the constructor's `components=`
  argument).
  - `add(component)` — raises `ValueError` on duplicate `id`.
  - `get(component_id)` — raises `KeyError` if missing.
  - `all_ports() -> dict[str, Port3D]` — flattens every component's `ports()` into
    `"{component.id}.{port_name}"` keys, via `render_cad3d_component`.
  - `to_scene_data() -> dict` — builds the full schema-shaped dict (`schema_version`, `title`, `units`,
    `assumptions` **with `"Generated from reusable 3D CAD components."` auto-appended**, `metadata`,
    `components` list from each component's `to_scene_component()`), validates it with
    `validate_cad3d_scene`, and **raises `ValueError`** (joining error strings) if invalid — i.e.
    `to_scene_data()` never returns an invalid scene, it throws instead.
  - `summary() -> str` — `"{title}: {N} component(s). Components: id1, id2, ...."`.
- `make_cad3d_component_scene(title, components) -> CAD3DComponentScene` — convenience constructor
  that starts with an empty scene and `.add()`s each component (so it also enforces uniqueness).

This is the **object-oriented / Python-builder path** to constructing scenes (used by
`component_examples.py`), as opposed to the **raw-dict path** (used by `scene_examples.py`,
`component_templates.py`, and anything the AI planner emits directly as JSON). Both paths must
produce dicts that satisfy the same `scene_schema.py` schema, but they are two independently
maintained code paths — see §9 for the port-calculation divergence between them.

---

## 4. `component_templates.py` / `component_examples.py` / `scene_examples.py`

These three modules serve **three different roles** in the generation pipeline, despite looking
superficially similar:

### `scene_examples.py` — oldest/simplest raw-dict demo scenes
- `simple_3d_equipment_layout_scene() -> dict` — a hand-written raw dict (not built via component
  classes) with `metadata.source = "deterministic_example"`. Contains: `skid_base_3d`,
  `vertical_tank_3d` (T101), `pump_placeholder_3d` (P101), `horizontal_vessel_3d` (V201), two
  `pipe_run_3d` (already-routed centerlines, not logical connections), three `label_3d`.
- `available_cad3d_examples() -> {"simple_equipment_layout": simple_3d_equipment_layout_scene}`,
  `get_cad3d_example(name) -> dict` (deep-copies the result; raises `ValueError` for unknown name).
- Used directly by tests (`test_autocad_3d_executor.py` imports `simple_3d_equipment_layout_scene` as
  a canonical executable fixture) and represents the **oldest Phase-30.1-era demo scene** referenced
  in its own docstring/comment ("Phase 30.1 primitives"). Not currently wired into
  `component_examples.available_cad3d_component_examples()`, so it is effectively a legacy/standalone
  fixture rather than part of the live example catalog exposed to the API/AI layer.

### `component_examples.py` — component-builder-based example catalog + one routed example
- `simple_3d_component_layout_scene() -> CAD3DComponentScene` — builds the same conceptual layout as
  `scene_examples.simple_3d_equipment_layout_scene()` but via the OOP component classes
  (`SkidBase3DComponent`, `VerticalTank3DComponent`, `PumpPlaceholder3DComponent`,
  `HorizontalVessel3DComponent`, two `PipeRun3DComponent`, three `Label3DComponent`).
  `metadata.example_name = "simple_component_layout"`, `metadata.source = "deterministic_component_example"`.
  `simple_3d_component_layout_scene_data()` is the `.to_scene_data()` dict form.
- `extended_3d_process_unit_scene() -> CAD3DComponentScene` — a bigger layout: tank T101, pump P101,
  heat exchanger E101, horizontal vessel V201, two `PipeRun3DComponent`s, a gate valve `XV101`, a
  control valve `CV101`, two flanges, two support legs, two saddle supports, one pipe support, four
  labels. `metadata.example_name = "extended_process_unit"`.
- `routed_tank_pump_separator_scene_data() -> dict` — a raw dict (not built via component classes)
  demonstrating the **logical routing path**: it uses `pipe_connection_3d` components
  (`PIPE_T101_P101` from `T101.side_right` to `P101.suction`, `PIPE_P101_V201` from `P101.discharge`
  to `V201.end_a`) instead of pre-routed `pipe_run_3d`. This is the fixture used throughout
  `routing.py`/`scene_editor.py` tests as the canonical "needs expansion" scene.
- `available_cad3d_component_examples() -> dict[str, Callable]` maps
  `"simple_component_layout"` → `simple_3d_component_layout_scene`,
  `"extended_process_unit"` → `extended_3d_process_unit_scene`,
  `"routed_tank_pump_separator"` → a wrapper `_routed_tank_pump_separator_scene()` returning a
  `_CAD3DSceneDataExample` dataclass wrapper (has `.to_scene_data()` to normalize the interface, since
  the underlying factory returns a plain dict rather than a `CAD3DComponentScene`) — **note the
  interface inconsistency**: two of the three catalog entries return `CAD3DComponentScene` objects
  directly, one returns a wrapper object; callers must use `.to_scene_data()` uniformly to be safe
  (which `get_cad3d_component_example` callers/routes do).
- `get_cad3d_component_example(name) -> Any` — dict lookup + call; raises plain `ValueError` (not a
  custom exception) for unknown names.
- **Usage**: `src/api/routes/cad3d.py`'s `/generate` endpoint uses this catalog as the **prompt-less
  fallback** — if the caller doesn't supply a `prompt`, it picks `example_name` (default
  `"simple_component_layout"`) from this catalog rather than invoking the AI planner at all. So this
  module serves double duty: demo/reference scenes AND the no-AI generation mode.

### `component_templates.py` — deterministic AI-planner fallback library
- `CAD3DTemplateError(Exception)`.
- `validate_cad3d_template_scene(scene) -> dict` — validates via `validate_cad3d_scene`, raises
  `CAD3DTemplateError` (joining messages) if invalid, else returns the scene unchanged. Every
  template-producing function funnels through this before returning.
- Internal helpers: `_scene(title, template_name, assumptions, components)` (builds+validates a fresh
  scene dict, tagging `metadata.source="deterministic_template"` and `metadata.template_name=...`),
  `_with_template_metadata(scene, template_name)` (deep-copies an existing scene dict and stamps the
  same metadata), `_replace_components_by_id(scene, replacements)` (deep-copies a scene's component
  list, substituting any component whose `id` is a key in `replacements` — used to turn a plain
  `pipe_run_3d` placeholder from an *example* scene into a logical `pipe_connection_3d` for a
  *template*).
- Five templates, each returning a validated scene dict, all registered in
  `available_cad3d_templates() -> dict[str, Callable[[], dict]]`:
  1. `tank_pump_separator_template_scene()` — reuses `simple_3d_component_layout_scene_data()` from
     `component_examples.py`, replacing its two named pipe-run placeholders with `pipe_connection_3d`
     logical connections (`PIPE_T101_P101`, `PIPE_P101_V201`, both `routing_style="orthogonal"`,
     `clearance` 400).
  2. `extended_process_unit_template_scene()` — same reuse-and-replace trick on
     `extended_3d_process_unit_scene_data()`, producing 3 logical pipe connections
     (`PIPE_T101_P101`, `PIPE_P101_E101`, `PIPE_E101_V201`) with `clearance` 450.
  3. `dual_pump_skid_template_scene()` — entirely hand-written raw-dict scene (not built from an
     existing example): a skid with two pumps (`P101`, `P102`), suction/discharge headers as
     `pipe_run_3d`, four `valve_placeholder_3d` (2 gate on suction, 2 check on discharge), two
     flanges, two pipe supports, four labels.
  4. `heat_exchanger_skid_template_scene()` — hand-written: pump, heat exchanger, inlet/outlet pipe
     runs, one `pipe_connection_3d` (pump→exchanger), a bypass `pipe_run_3d`, 3 valves (inlet, outlet,
     bypass), 2 flanges, 2 pipe supports, 5 labels.
  5. `vertical_scrubber_package_template_scene()` — hand-written: one vertical tank (V301) with gas
     inlet/outlet pipe runs, a vent pipe run, a drain pipe run, 3 valves, 2 flanges, 3 support legs, 1
     pipe support, 5 labels.
- `match_cad3d_template(user_request: str) -> dict{template_name, confidence, reason}` — a **pure
  keyword-scoring heuristic** (`_normalize_prompt` lowercases+collapses whitespace; `_score` counts
  how many of a term-tuple appear as substrings). Checked in this exact order: dual-pump phrase or
  ≥2 dual-pump terms → `dual_pump_skid` (high); scrubber phrase or ≥2 scrubber terms →
  `vertical_scrubber_package` (high); `"heat exchanger skid"` phrase → `heat_exchanger_skid` (high);
  extended-unit phrase or ≥4 extended terms → `extended_process_unit` (high); heat-exchanger phrase or
  ≥2 heat terms → `heat_exchanger_skid` (high); ≥3 tank/pump/vessel/skid terms →
  `tank_pump_separator` (high); ≥3 extended terms (re-check, lower threshold) →
  `extended_process_unit` (high); **default fallback** → `tank_pump_separator` (confidence `"low"`,
  reason `"Default 3D template fallback."`).
- `choose_cad3d_template(user_request) -> (template_name, scene_data)` — calls `match_cad3d_template`
  then invokes the matched factory from `available_cad3d_templates()`; raises `CAD3DTemplateError` if
  the matched name somehow isn't registered (defensive, shouldn't happen given the match function only
  returns registered names).
- **Confirmed usage**: `src/ai/cad3d_scene_planner.py` imports `choose_cad3d_template` and calls it
  inside `plan_cad3d_scene_resilient(..., allow_example_fallback=True)` when the AI planning call
  fails/raises — the result's `metadata["fallback_template_name"]` and
  `metadata["fallback_example_name"]` are both set to the matched `template_name` (see
  `src/api/routes/cad3d.py:152-153`). So: **this module is specifically the deterministic safety net
  invoked when the LLM scene planner errors out**, not a general-purpose example catalog (that role
  belongs to `component_examples.py`/`scene_examples.py`).

---

## 5. `routing.py` — port resolution and pipe-connection expansion

Purpose: resolve `COMPONENT_ID.PORT_NAME` string references against a **raw scene dict** (not
component objects) to compute 3D port positions/directions, then synthesize an executable
`pipe_run_3d` polyline between two ports for each logical `pipe_connection_3d`.

Exceptions: `CAD3DRoutingError` (base), `CAD3DPortResolutionError(CAD3DRoutingError)` (port/reference
lookup failures).

### Port reference parsing
- `normalize_port_reference(reference: str) -> (component_id, port_name)` — requires exactly one `.`
  in the trimmed string, both halves non-empty, else raises `CAD3DPortResolutionError`.
- `get_component_by_id(scene, component_id) -> dict` — linear scan of `scene["components"]`; raises if
  not found.

### `component_ports(component: dict) -> dict[str, dict]` — the routing table

This is a **from-scratch reimplementation** of each component type's port geometry (independent of
the `components/*.py` dataclasses' `ports()` methods — see §9 for the divergence). Dispatch is a long
`if component_type == "...":` chain (not a dict-based lookup like `_COMPONENT_HANDLERS` in the
executor). Mapping of `component_type` → computed ports:

| `component_type` | Computed ports | Extra semantic aliases added via `_add_aliases` |
|---|---|---|
| `vertical_tank_3d` | `top`, `bottom`, `side_left`, `side_right`, `side_front`, `side_back` | `inlet`→side_left, `outlet`→side_right, `drain`→bottom, `vent`→top |
| `horizontal_vessel_3d` | `end_a`, `end_b`, `top`, `bottom` | `inlet`→end_a, `outlet`→end_b, `drain`→bottom, `vent`→top |
| `heat_exchanger_3d` | `inlet`, `outlet` | `end_a`→inlet, `end_b`→outlet |
| `pump_placeholder_3d` | `suction`, `discharge` | `inlet`→suction, `outlet`→discharge |
| `valve_placeholder_3d` | `inlet`, `outlet` | (none — already canonical) |
| `nozzle_3d` | `base`, `tip` | `inlet`→base, `outlet`→tip |
| `flange_3d` | `face_a`, `face_b` | `inlet`→face_a, `outlet`→face_b |
| `pipe_run_3d` | `start`, `end` | (none) |
| `support_leg_3d` | `top`, `bottom` | (none) |
| `pipe_support_3d` | `top` | (none) |
| anything else (skid_base_3d, box_3d, saddle_support_3d, label_3d, pipe_connection_3d) | `{}` | — |

`_add_aliases(ports, aliases)` copies (not references) the canonical port dict under each alias key
when the canonical key exists. All geometry helpers here (`_point3`, `_vector3`, `_center`,
`_orientation`, `_make_port`, `_axis_points`, `_field_float`, `_positive_float`) are **local
re-implementations**, structurally identical to but code-independent from the equivalents in
`components/base.py` and `components/fittings.py`.

### `build_port_index(scene) -> dict[str, dict]`
Flattens every component's `component_ports()` result into `"{id}.{port_name}"` keys across the whole
scene (parallel to `CAD3DComponentScene.all_ports()` in §3, but operating on raw dicts).

### `resolve_port_reference(scene, reference) -> dict`
`normalize_port_reference` + `get_component_by_id` + `component_ports` lookup; raises
`CAD3DPortResolutionError` (listing available ports) if the port name isn't found on that component.

### Route generation
- `dedupe_consecutive_points(points) -> list[list[float]]` — normalizes each point via `_point3`,
  drops consecutive duplicates.
- `_normalize_axis_order(axis_order) -> list[str]` — defaults to `["X","Y","Z"]`; validates 1-3 unique
  axis letters, then appends any missing default axes at the end (so the full route always walks all
  3 axes in some order, even if the caller only specified a subset).
- `orthogonal_pipe_route_3d(from_port, to_port, clearance=500.0, axis_order=None) -> list[point3]` —
  builds a Manhattan/orthogonal route: start at `from_port.position`, step out along
  `from_port.direction * clearance` (first offset), then walk axis-by-axis (per `axis_order`) snapping
  each coordinate to the corresponding coordinate of the "last offset" point (`to_port.position +
  to_port.direction * clearance`), then step in to `to_port.position`. Dedupes consecutive duplicate
  points; falls back to a direct 2-point route if dedup collapses everything below 2 points.
- `direct_pipe_route_3d(from_port, to_port) -> [start, end]` — trivial straight line between port
  positions (ignores directions/clearance entirely).
- `build_pipe_run_from_connection(connection, scene) -> dict` — the core expansion function: resolves
  `from_port`/`to_port` refs, reads `diameter` (positive, required), `routing_style` (default
  `"orthogonal"`, must be `"direct"` or `"orthogonal"` else raises), `clearance` (default `500.0`),
  `axis_order` (optional). Produces a `pipe_run_3d` dict with the connection's `id`, computed `points`,
  `diameter`, and a `metadata` dict merging the connection's original metadata with
  `{"generated_from": "pipe_connection_3d", "from_port", "to_port", "routing_style", "clearance"}`.
  Carries over `tag` if present on the connection.
- `count_pipe_connections(scene) -> int` — count of `pipe_connection_3d` components.
- `expand_pipe_connections(scene) -> dict` — **the main entry point used by the executor and scene
  editor**. Validates the input scene first (raises `CAD3DRoutingError` if invalid — note: NOT
  `CAD3DPortResolutionError`, a plain routing error, wrapping the joined schema-error messages), deep
  copies it, replaces every `pipe_connection_3d` with its expanded `pipe_run_3d` (leaving all other
  components untouched, deep-copied), stamps `metadata.pipe_connections_expanded` (count) and
  `metadata.routing_engine = "cad3d_port_router_v1"`, then validates the **output** scene too (raising
  `CAD3DRoutingError` again if the expansion somehow produced something schema-invalid). Fully
  deterministic — no randomness, same input always produces the same output.

---

## 6. `scene_editor.py` + `edit_schema.py` — incremental scene edits

Together these implement a **validated command pattern**: an "edit plan" (JSON, potentially
LLM-authored) containing one or more typed operations is normalized/validated (`edit_schema.py`) then
applied to a scene dict (`scene_editor.py`), producing a new scene dict.

### `edit_schema.py` — plan shape & normalization

`CAD3D_EDIT_SCHEMA_VERSION = "1.0"`. `CAD3DEditValidationError(Exception)`.

Plan shape:
```json
{
  "schema_version": "1.0",
  "edit_intent": "<non-empty string>",
  "summary": "<non-empty string, defaults to edit_intent if omitted>",
  "metadata": {"...": "..."},
  "operations": [ {...}, ... ]   // non-empty list, required
}
```

Four operation types (`operation_type` field), each validated by
`normalize_cad3d_edit_plan(plan) -> dict`:

1. **`move_component`** — requires `component_id` (non-empty string) and **either** `delta` (a coord3
   offset) **or** `new_center` (a coord3 absolute target) — raises if neither is present. Both, if
   present, are normalized to `[float, float, float]` via `_coord3`.
2. **`update_component`** — requires `component_id` and a non-empty `updates` dict. `updates` keys are
   checked against `_ALLOWED_UPDATE_FIELDS = {center, length, width, height, diameter, orientation,
   tag, metadata, visual_style, draw_centerline, valve_type, thickness, points, from_port, to_port,
   routing_style, clearance, axis_order}` — any key outside this set raises. `_FORBIDDEN_UPDATE_FIELDS
   = {id, component_type}` are explicitly rejected even though they're not in the allowed set anyway
   (belt-and-suspenders, with a distinct error message). Each field's value is normalized by
   `_normalize_update_value`: `center` → coord3, `points` → list of ≥2 coord3s, `{length, width,
   height, diameter, thickness, clearance}` → float, `axis_order` → list of upper-cased axis strings,
   `metadata` → deep-copied dict as-is, everything else (`tag`, `orientation`, `valve_type`,
   `visual_style`, `draw_centerline`, `from_port`, `to_port`, `routing_style`) → deep-copied unchanged
   (no type coercion for these).
3. **`add_component`** — requires a `component` dict (deep-copied verbatim; **not** validated against
   `scene_schema.py` at this stage** — that happens later when the whole edited scene is validated in
   `scene_editor.apply_cad3d_edit_plan`).
4. **`delete_component`** — requires `component_id` (non-empty string).

Any other `operation_type` raises `CAD3DEditValidationError`. `validate_cad3d_edit_plan(plan) -> dict`
wraps `normalize_cad3d_edit_plan` and additionally enforces `schema_version == "1.0"` exactly.

### `scene_editor.py` — applying the plan

`CAD3DSceneEditError(Exception)`, `CAD3DComponentNotFoundError(CAD3DSceneEditError)`. Note this module
has its **own copy** of `_ALLOWED_UPDATE_FIELDS` (identical set to `edit_schema.py`'s) — a second
duplication point to keep in sync if either list ever changes (see §9).

Helpers:
- `find_component_index(scene, component_id) -> int` / `get_component(scene, component_id) -> dict` /
  `list_component_ids(scene) -> list[str]` / `ensure_unique_component_ids(scene)` (raises
  `CAD3DSceneEditError` listing duplicates).
- `move_component(component, delta=None, new_center=None) -> dict` — deep-copies the component; if
  `new_center` given, sets `center` (if the component has one) or `position` (if it has that instead,
  e.g. `label_3d`) directly to `new_center`; else if `delta` given, offsets whichever of
  `center`/`position`/`points` (offsets *every* point in a `points` list, e.g. for `pipe_run_3d`) the
  component has. Raises `CAD3DSceneEditError` if the component has none of `center`, `position`, or
  `points` (shouldn't normally happen given the schema, but is defensive).
- `update_component_fields(component, updates) -> dict` — deep-copies the component, re-validates
  `updates` isn't empty and doesn't touch `id`/`component_type`, re-checks the allowed-fields set
  (redundant with `edit_schema.py`'s check, but this module can also be called directly/independently
  of the edit-plan flow, e.g. from tests), then overwrites each field.
- `add_component_to_scene(scene, component) -> dict` — requires `component["id"]` non-empty, rejects
  duplicate IDs, appends, re-checks uniqueness, and **validates the resulting scene against
  `scene_schema.py`** (raising `CAD3DSceneEditError` with the prefix `"Invalid CAD3D scene after
  add_component"` if invalid) — this is where a malformed `add_component.component` dict from
  `edit_schema.py` (which doesn't itself schema-validate) finally gets caught.
- `_references_component(reference, component_id) -> bool` — checks if a string port-reference like
  `"T101.side_right"` starts with `"{component_id}."`.
- `delete_component_from_scene(scene, component_id, remove_connected_pipes=True) -> dict` — removes the
  named component; if `remove_connected_pipes` (default `True`), also cascades deletion to any
  `pipe_connection_3d` whose `from_port`/`to_port` references the deleted component, **and** any
  already-expanded `pipe_run_3d` whose `metadata.from_port`/`metadata.to_port` (stamped by
  `build_pipe_run_from_connection`) reference it. This is how deleting `P101` in the routed example
  also removes `PIPE_T101_P101` and `PIPE_P101_V201` (confirmed by test
  `test_delete_component_from_scene_removes_connected_pipe_connection`).
- `apply_cad3d_edit_plan(scene, edit_plan) -> dict` — the top-level entry point:
  1. Deep-copies the input scene, validates it against `scene_schema.py`, checks ID uniqueness.
  2. Validates the edit plan via `edit_schema.validate_cad3d_edit_plan` (wrapping any
     `CAD3DEditValidationError` into `CAD3DSceneEditError`).
  3. Applies each operation in order (dispatch on `operation_type`; unsupported types raise even
     though `edit_schema.py` should have already rejected them — defensive double-check).
  4. Re-checks uniqueness, then stamps scene `metadata`: `last_edit_intent`, `last_edit_summary`,
     `last_edit_operation_count`, and `edited_from` — the latter is set to the **original** scene's
     `metadata.scene_token` or `.token` or `.template_name` or `.example_name` (first non-null, in that
     priority order), or, if none of those exist, the **entire original metadata dict** verbatim
     (this is why the example scene JSON in `outputs/cad3d/scenes/*.json` shows nested
     `edited_from: {edited_from: {...}}` chains — each edit stores the *whole prior metadata blob* as
     provenance when no short token/name field was available).
  5. Validates the final edited scene against `scene_schema.py` (raises with prefix `"Invalid CAD3D
     scene after edit"`).
  6. Runs `routing.expand_pipe_connections` on the edited scene purely as a **sanity check** (its
     result is discarded — the returned scene from this function is still the *unexpanded* edited
     scene) — this is how a dangling `pipe_connection_3d.to_port` referencing a just-deleted component
     is caught and surfaced as `CAD3DSceneEditError` (wrapping the underlying `CAD3DRoutingError`)
     even though expansion normally happens later at execution time.
- `summarize_scene_edit(original_scene, edited_scene) -> dict` — returns
  `{original_component_count, edited_component_count, added_component_ids, removed_component_ids,
  unchanged_component_ids, component_types}` (all id lists sorted; computed via set difference/
  intersection on component IDs).

**Resilience pattern in the API layer** (`src/api/routes/cad3d.py:280-291`): when the AI-produced edit
plan fails to *apply* (`CAD3DSceneEditError`), the route catches it and retries with
`deterministic_edit_plan_from_request` (in `src/ai/cad3d_edit_planner.py`, outside this subsystem's
scope but referenced here for completeness) — a keyword/regex-based fallback edit-plan generator
(handles simple "move X direction N mm", "delete X", "change X dimension to N" phrasings; raises
`CAD3DSceneEditError` itself for anything it can't parse, per
`test_fallback_fails_cleanly_for_unsupported_edit`).

---

## 7. `scene_store.py` — persistence

`CAD3DSceneStoreError(Exception)`.

### Record shape — `CAD3DSceneRecord` (dataclass)
Fields: `token`, `prompt`, `drawing_style`, `scene` (full scene dict), `component_ids`,
`component_types`, `created_at`, `updated_at` (both UTC ISO-8601 via `_utc_now_iso()`, which formats as
`...Z` not `+00:00`), `status` (one of `"generated"`, `"approved"`, `"failed"` — enforced by
`_validate_status`), `document_name: str | None`, `approval_result: dict | None`,
`generation_metadata: dict | None`, `expanded_scene: dict | None`.
- `to_dict()` — `dataclasses.asdict(self)` (plain nested-dict serialization).
- `from_dict(data)` — reconstructs from a dict, requiring all of `{token, prompt, drawing_style,
  scene, component_ids, component_types, created_at, updated_at, status}` to be present (raises
  listing missing fields), and **re-validates** both `scene` and (if present) `expanded_scene` against
  `scene_schema.py` on load — so a hand-edited or corrupted JSON file on disk with an invalid scene
  will fail to load.

### `CAD3DSceneStore` class
Constructor takes optional `persist_dir: str | Path | None`. In-memory state:
`self._records: dict[str, CAD3DSceneRecord]`, `self._latest_token: str | None`.

- `put_generated_scene(token, prompt, scene, drawing_style=None, generation_metadata=None)` —
  validates the scene, computes `extract_scene_component_summary(scene)` (returns
  `{component_count, component_ids, component_types (sorted set), type_counts (sorted dict)}`),
  builds a new record with `status="generated"`, stores it in memory, sets it as latest, and
  **persists to disk** (see below). Note: calling this again with an existing token fully **replaces**
  the record (no merge) — this is how `/api/cad3d/edit` with `create_new_token=False` overwrites the
  source token's record in place.
- `mark_approved(token, approval_result: dict, expanded_scene: dict | None = None)` — fetches the
  existing record (raises if missing), sets `status = "approved" if approval_result.get("ok") else
  "failed"`, stores `approval_result` and `document_name` (from `approval_result.get("document_name")`),
  optionally stores `expanded_scene` (validated if provided), bumps `updated_at`, re-persists.
- `get(token)` — checks memory first, else attempts `_load_record_from_disk(token)` (raises
  `CAD3DSceneStoreError` if `persist_dir` is `None` or the file doesn't exist or fails to parse/
  validate); caches the loaded record and marks it latest.
- `get_latest()` — returns the record for `self._latest_token` if set; otherwise calls
  `_load_all_records_from_disk()` (scans `persist_dir.glob("*.json")`, loading any not-yet-cached
  token, skipping ones that fail to load) and then picks the max by `updated_at` string comparison
  (ISO-8601 timestamps sort correctly as strings). Raises if nothing is available at all.
- `list_records(limit=20)` — validates `limit` is a positive int (rejects bools explicitly, since
  `isinstance(True, int)` is `True` in Python), loads all records from disk first, then returns up to
  `limit` sorted by `updated_at` descending.
- `delete(token)` — removes from memory and, if `persist_dir` set, deletes the corresponding JSON
  file. Recomputes `_latest_token` (picks the new max by `updated_at` among remaining records, or
  `None` if none remain) if the deleted token was the latest.
- `clear()` — wipes in-memory state only (does **not** touch disk files).
- `_persist_record(record)` — no-op if `persist_dir is None`; otherwise creates the directory
  (`mkdir(parents=True, exist_ok=True)`), writes to a `"{token}.json.tmp"` temp file
  (`json.dumps(..., indent=2, sort_keys=True)`), then **atomically renames** it over the real path via
  `Path.replace()` — this is a proper crash-safe write pattern (no partial-file corruption on a mid-
  write crash). Raises `CAD3DSceneStoreError` wrapping any `OSError`.
- `_clean_token(token)` — strips the token, rejects empty strings, and rejects any token containing
  `/`, `\`, or `..` (**path-traversal protection** — since the token becomes a filename directly:
  `self.persist_dir / f"{clean_token}.json"`).

### Default singleton
```python
_DEFAULT_CAD3D_SCENE_STORE = CAD3DSceneStore(persist_dir=Path("outputs") / "cad3d" / "scenes")
get_default_cad3d_scene_store() -> CAD3DSceneStore   # returns this singleton
```
This **confirms** the `outputs/cad3d/scenes/*.json` directory on disk (41 files present at analysis
time) is exactly this store's persistence directory, with each file named `"{token}.json"` where
`token` is a `uuid.uuid4().hex` string minted in `src/api/routes/cad3d.py` (`/generate` and `/edit`
endpoints). Inspecting one such file
(`outputs/cad3d/scenes/00db50be0a0840bc8074c1a5de61bf21.json`) confirms the on-disk shape matches
`CAD3DSceneRecord.to_dict()` exactly (`token`, `prompt`, `drawing_style`, `scene`, `component_ids`,
`component_types`, `created_at`, `updated_at`, `status="approved"`, `document_name`,
`approval_result`, `generation_metadata`, `expanded_scene`), and that `scene.metadata.edited_from`
nests prior metadata blobs exactly as described in §6 (the sample file is the result of two chained
edits: "Add a small valve handle..." then "Move H-101 500 mm to the left.").

**Concurrency**: there is **no locking** of any kind — not on the in-memory dict, not on the on-disk
files. The atomic temp-file-rename pattern protects against partial writes from a *single* writer
crashing mid-write, but two concurrent requests writing the same token race freely (last write wins,
in-memory dict assignment is not synchronized). Since the FastAPI app is presumably single-worker/
single-process for local desktop use (per the project's nature — a local Windows automation tool
driving one AutoCAD COM instance), this is a low-risk gap in practice but would matter under any
concurrent-request scenario. There's also no file-locking against external processes/editors touching
the same `outputs/cad3d/scenes/*.json` files while the app runs.

---

## 8. `autocad_3d_executor.py` — COM execution

`AutoCAD3DExecutionError(Exception)`. Depends on shared helpers from
`src/framework/commands/executor.py` (`_activate_regen_zoom`, `_safe_get_document_name`,
`_safe_get_dwg_path`, `_safe_modelspace_count`, `acad_point`) and
`src/parametric/vessel/dwg_export.py` (`_com_retry`, `_get_acad`) — these are **shared with the 2D/
command-based executor**, i.e. CAD3D reuses the PID/general command executor's COM-connection and
retry infrastructure rather than reimplementing it. `_com_retry(operation, description, attempts=5,
delay_seconds=0.5)` retries only on COM "busy" errors (specific HRESULTs like `RPC_E_CALL_REJECTED`);
`_get_acad()` calls `win32com.client.GetActiveObject("AutoCAD.Application")`, raising
`AutoCADNotRunningError` if AutoCAD isn't running. `acad_point(x,y,z)` builds a COM-safe
`VARIANT(VT_ARRAY|VT_R8, (x,y,z))` (falls back to a plain tuple if `pythoncom`/`win32com` aren't
importable, e.g. under non-Windows test collection).

### Presentation layers
A fixed palette of 11 named layers with AutoCAD ACI color indices, defined as
`CAD3D_PRESENTATION_LAYERS: dict[str, int]`:

| Layer | Color (ACI) | For |
|---|---|---|
| `CAD3D_TANKS` | 5 (blue) | `vertical_tank_3d` |
| `CAD3D_VESSELS` | 4 (cyan) | `horizontal_vessel_3d` |
| `CAD3D_PUMPS` | 30 (orange-ish) | `pump_placeholder_3d` |
| `CAD3D_EXCHANGERS` | 1 (red) | `heat_exchanger_3d` |
| `CAD3D_PIPES` | 3 (green) | `pipe_run_3d` |
| `CAD3D_VALVES` | 6 (magenta) | `valve_placeholder_3d` |
| `CAD3D_FLANGES` | 2 (yellow) | `flange_3d` |
| `CAD3D_SUPPORTS` | 8 (gray) | `support_leg_3d`, `saddle_support_3d`, `pipe_support_3d` |
| `CAD3D_SKID` | 9 (neutral gray) | `skid_base_3d` |
| `CAD3D_LABELS` | 7 (white/fg) | `label_3d` |
| `CAD3D_GENERIC` | 9 | anything unmatched (`nozzle_3d`, `box_3d` fall through to this) |

`_ensure_layer(doc, layer_name, color)` — gets-or-creates the layer (`doc.Layers.Item` then
`doc.Layers.Add` on failure), sets `.Color` best-effort (swallows exceptions — "layer color is
presentation polish, should never block geometry"). `_ensure_cad3d_presentation_layers(doc)` creates
all 11 up front. `_cad3d_layer_for_component(component)` maps `component_type` → layer name per the
table above. `_apply_presentation_style(entity, component)` — sets `entity.Layer` (explicit
`component["layer"]` wins over the type-based default) and `entity.Color` (explicit
`component["color"]` wins over the layer's default color); both assignments are individually
try/excepted so a styling failure never aborts geometry creation.

### Geometry creation — one handler function per `component_type`, dispatched via `_COMPONENT_HANDLERS`

```python
_COMPONENT_HANDLERS: dict[str, Callable[[Any, dict], int]] = {
    "vertical_tank_3d": _execute_vertical_tank_3d,
    "horizontal_vessel_3d": _execute_horizontal_vessel_3d,
    "heat_exchanger_3d": _execute_heat_exchanger_3d,
    "pump_placeholder_3d": _execute_pump_placeholder_3d,
    "valve_placeholder_3d": _execute_valve_placeholder_3d,
    "nozzle_3d": _execute_nozzle_3d,
    "flange_3d": _execute_flange_3d,
    "support_leg_3d": _execute_support_leg_3d,
    "saddle_support_3d": _execute_saddle_support_3d,
    "pipe_support_3d": _execute_pipe_support_3d,
    "pipe_run_3d": _execute_pipe_run_3d,
    "skid_base_3d": _execute_skid_base_3d,
    "box_3d": _execute_box_3d,
    "label_3d": _execute_label_3d,
}
```
Note **`pipe_connection_3d` has no handler** — it must always be expanded to `pipe_run_3d` before
reaching `_execute_component_3d` (enforced by `execute_cad3d_scene` calling
`routing.expand_pipe_connections` unconditionally before the execution loop). `_execute_component_3d`
raises `AutoCAD3DExecutionError` for any `component_type` not in the dict.

Only three actual COM creation calls are used across all 14 handlers:
- **`msp.AddCylinder(center_point, radius, height)`** — used for `vertical_tank_3d`,
  `horizontal_vessel_3d`, `heat_exchanger_3d`, `nozzle_3d`, `flange_3d` (thickness as height),
  `support_leg_3d` (height as height), and per-segment for axis-aligned `pipe_run_3d` segments. Native
  cylinder axis is Z; `_rotate_cylinder_to_orientation(entity, center, orientation)` calls
  `entity.Rotate3D(acad_point(center), acad_point(axis_end), angle)` to tip it onto X (`angle=+π/2`
  about a Y-offset axis) or Y (`angle=-π/2` about an X-offset axis) when needed — best-effort, silently
  ignored if `Rotate3D` isn't available or fails (leaves an upright placeholder cylinder rather than
  failing the whole component).
- **`msp.AddBox(center_point, length, width, height)`** — used for `pump_placeholder_3d`,
  `valve_placeholder_3d`, `saddle_support_3d`, `pipe_support_3d` (as `width, depth, height`),
  `skid_base_3d`, `box_3d`. So **pumps and valves are visually indistinguishable boxes** — only layer
  color (magenta vs orange) and the `tag`/`valve_type` metadata differentiate them.
- **`msp.AddLine(start_point, end_point)`** — used for pipe centerlines (`_add_pipe_centerline_segment`)
  and as the **fallback** when a pipe solid-cylinder segment can't be created (non-axis-aligned, or
  `AddCylinder`/`Rotate3D` raises).
- **`msp.AddText(text, position_point, height)`** — used only for `label_3d`.

There is **no mesh, no block/`AddBlock`, no true extrusion API** (`AddExtrudedSolid`, etc.) anywhere in
this executor — everything is a primitive solid (cylinder/box) or a 2D-in-3D-space line/text entity.

### Pipe run execution detail (`_execute_pipe_run_3d`)
- `_pipe_visual_options(component) -> (draw_solid, draw_centerline)` derived from `visual_style`
  (default `"solid_with_centerline"`; must be one of `centerline`/`solid`/`solid_with_centerline` else
  raises) and optional explicit `draw_centerline` bool override.
- For each consecutive point pair in `points`: skips zero-length segments; if `draw_solid`, attempts
  `_add_axis_aligned_pipe_cylinder` (computes segment midpoint+length via `_distance_3d`/
  `_segment_midpoint`, requires the segment be axis-aligned via `_is_axis_aligned_segment` — checks
  that only one of the 3 deltas exceeds `1e-6`; raises `AutoCAD3DExecutionError` "Pipe cylinder
  segments must be axis-aligned" if not, or "Pipe diameter must be positive" if `diameter <= 0`) —
  builds a cylinder along Z then rotates for X/Y axis exactly like other cylinders, **deleting** the
  unrotated entity and re-raising if rotation fails/`Rotate3D` unavailable; on **any** exception from
  this whole solid-cylinder attempt, it catches and falls back to drawing a plain centerline
  (`_add_pipe_centerline_segment`) instead for that segment, counting it as created either way. If
  `draw_centerline` is also true (and the fallback didn't already draw one), it additionally draws the
  centerline line on top of the solid. Each created entity is styled via `_apply_presentation_style`
  using a `style_component` copy that carries forward `component.get("layer") or
  component.get("metadata", {}).get("layer")` as an explicit layer override if present.

### `execute_cad3d_scene(scene, target_dwg_path=None, save=False, zoom_extents=True) -> dict`
Top-level orchestration:
1. Validates the incoming `scene` against `scene_schema.py` — raises `AutoCAD3DExecutionError` if
   invalid (this is checked **before** expansion, so a raw pipe_connection_3d-containing scene is
   valid at this stage since `pipe_connection_3d` is itself a valid schema branch).
2. Records `original_component_count` and `pipe_connections_expanded = count_pipe_connections(scene)`
   (counted **before** expansion).
3. Calls `routing.expand_pipe_connections(scene)` — wraps any `CAD3DRoutingError` into
   `AutoCAD3DExecutionError("CAD3D pipe routing failed: ...")`.
4. Re-validates the **expanded** scene (defensive double-check — raises with a distinct message if
   somehow invalid).
5. `acad = _get_acad()`; opens `target_dwg_path` via `acad.Documents.Open(...)` if given, else uses
   `_active_document(acad)` (raises `AutoCAD3DExecutionError` if `acad.ActiveDocument` is `None` or
   raises).
6. Best-effort `_ensure_cad3d_presentation_layers(doc)` — failure is captured into
   `presentation_layer_error` in the result but never raises.
7. Records `entity_count_before` via `_safe_modelspace_count(msp)`.
8. Loops over every (expanded) component, calling `_execute_component_3d(doc, component)`. If the
   handler returns `<= 0` (created zero entities), that's treated as a failure too (raises internally
   inside the loop, caught by the same `except Exception` below). **Per-component failures are
   caught individually** and appended to an `errors` list (with `component_index`, `component_id`,
   `component_type`, `error` string) — **execution continues** for all remaining components rather
   than aborting (this is why the result includes `ok = not errors` rather than raising on first
   failure — a partial-failure scene still gets as much geometry created as possible).
9. If `save=True`, calls `doc.Save()` — failure appends an error row with `component_type="SAVE"` (does
   not raise).
10. Records `entity_count_after`.
11. If `zoom_extents=True`, calls the shared `_activate_regen_zoom(acad, doc)` (activates the document,
    `Regen(1)`, `ZoomExtents()`) — returns `(called: bool, error: str|None)`, never raises.
12. Returns a result dict with keys: `ok`, `executed_count`, `total_count`,
    `pipe_connections_expanded`, `executable_component_count`, `original_component_count`, `errors`,
    `dwg_path`, `document_name`, `entity_count_before`, `entity_count_after`, `zoom_extents_called`,
    `zoom_error`, `presentation_layers_created`, `presentation_layer_error`.

This result dict shape is exactly what's stored as `approval_result` in `CAD3DSceneRecord` (§7) and
returned as `execution_result` from the `/edit` and `/approve` API routes.

---

## 9. Test coverage summary and cross-cutting observations

### Test coverage summary
All 17 listed test files were read; coverage is thorough and maps 1:1 to source modules:
- `test_cad3d_components_base.py` — normalize/offset/make_port3 helpers, `BaseCAD3DComponent`
  validation, `render_cad3d_component`.
- `test_cad3d_equipment_components.py`, `test_cad3d_fitting_components.py`,
  `test_cad3d_piping_components.py`, `test_cad3d_support_components.py`,
  `test_cad3d_valve_components.py`, `test_cad3d_annotation_components.py` — per-component
  ports/validation/scene-integration tests, one file per `components/*.py` module.
- `test_cad3d_component_scene.py` — `CAD3DComponentScene` container behavior (dedup, get, ports,
  to_scene_data validation, error propagation from an intentionally-invalid fake component).
- `test_cad3d_component_examples.py`, `test_cad3d_scene_examples.py`,
  `test_cad3d_component_templates.py` — catalog completeness, schema validity of every example/
  template, `match_cad3d_template`/`choose_cad3d_template` keyword-matching table (parametrized over
  the exact prompts/expected templates/confidences shown in §4).
- `test_cad3d_scene_schema.py` — exhaustive per-field/per-type schema validation including every
  `visual_style` value, `pipe_connection_3d` routing_style/clearance edge cases, unknown component
  type, negative dimensions.
- `test_cad3d_routing.py` — port reference parsing, `component_ports` for every branch, direct/
  orthogonal route generation determinism, full `expand_pipe_connections` round-trips.
- `test_cad3d_edit_schema.py` — every operation type's validation rules including numeric-string
  coercion (`"1000"` → `1000.0`) and forbidden-field rejection.
- `test_cad3d_scene_editor.py` — move/update/add/delete operations, cascade-delete of connected pipes,
  multi-operation plans, failure when a pipe connection is left dangling after an edit.
- `test_cad3d_scene_store.py` — CRUD, status transitions, `list_records`/`get_latest` ordering,
  disk persistence + reload from a fresh store instance, invalid-scene rejection.
- `test_autocad_3d_executor.py` — uses hand-rolled `FakeAcad`/`FakeDoc`/`FakeModelSpace`/`FakeEntity`
  COM stand-ins (no real AutoCAD needed) covering every handler's entity type, pipe visual-style
  branches (centerline/solid/solid_with_centerline/diagonal-fallback/zero-length-skip), full-scene
  execution with routing expansion, partial-failure error recording, `target_dwg_path` open flow.
- `test_cad3d_edit_planner.py` — technically tests `src/ai/cad3d_edit_planner.py` (outside this
  subsystem's own folder) but exercises this subsystem's `edit_schema`/`scene_editor` exceptions as
  its API contract (`CAD3DEditValidationError`, `CAD3DSceneEditError` propagate through
  `plan_cad3d_edit`/`plan_cad3d_edit_resilient`).

No test file exercises `scene_store.py`'s lack of locking/concurrency, nor the `_CAD3D_CACHE`
in-process dict in `src/api/routes/cad3d.py` (which is separate, ephemeral, and unbounded — approve
tokens never expire or get cleaned up, a minor memory-leak-shaped risk for a long-running server
process, though low-impact for this local desktop tool).

### Cross-cutting observations / risk areas

1. **Duplicated port-geometry math (biggest risk area).** The exact same per-component-type port
   position/direction formulas exist in two independent places: the OOP `ports()` methods in
   `components/equipment.py`/`fittings.py`/`piping.py`/`supports.py`/`valves.py`, and the raw-dict
   `component_ports()` dispatch chain in `routing.py`. **They have already drifted**: `routing.py`'s
   version is a strict superset for `vertical_tank_3d` (adds `side_front`/`side_back` plus semantic
   aliases `inlet`/`outlet`/`drain`/`vent`), `horizontal_vessel_3d` (adds `inlet`/`outlet`/`drain`/
   `vent` aliases), `pump_placeholder_3d` (adds `inlet`/`outlet` aliases), `heat_exchanger_3d` (adds
   `end_a`/`end_b` aliases), `nozzle_3d` (adds `inlet`/`outlet` aliases), and `flange_3d` (adds
   `inlet`/`outlet` aliases) — but is identical for `valve_placeholder_3d`, `support_leg_3d`,
   `pipe_support_3d`, and `pipe_run_3d`. Any future change to one geometry formula must be
   manually mirrored in the other location, and the OOP component-builder path
   (`CAD3DComponentScene.all_ports()`) will silently expose *fewer* port names/aliases than a
   raw-dict scene processed through `routing.build_port_index()` for the exact same component types —
   a scene built with `T101 = VerticalTank3DComponent(...)` cannot be pipe-connected via `T101.inlet`
   the way an AI-planner-authored raw-dict scene can.
2. **Two independent normalization/geometry helper sets.** `components/base.py`
   (`normalize_point3`/`normalize_vector3`/`make_port3`) and `routing.py` (`_point3`/`_vector3`/
   `_make_port`) and `autocad_3d_executor.py` (`_point3`/`_distance3`) each reimplement 3D point/
   vector coercion from scratch rather than sharing one utility module. Low risk (they're simple and
   behaviorally equivalent today) but a maintenance smell.
3. **`_ALLOWED_UPDATE_FIELDS` is defined identically in two files** — `edit_schema.py` and
   `scene_editor.py` — with no shared constant. If a new updatable field is ever added to one, the
   other must be remembered separately (`scene_editor.update_component_fields` is also callable
   directly, bypassing `edit_schema.py` entirely, so it needs its own guard regardless — but the
   duplication is still a drift risk).
4. **Inconsistent `tag` emission in `to_scene_component()`.** Most components include `"tag"` in the
   output dict only when `self.tag is not None` (the majority pattern: `Nozzle3DComponent`,
   `Flange3DComponent`, `PipeRun3DComponent`, `SupportLeg3DComponent`, `SaddleSupport3DComponent`,
   `PipeSupport3DComponent`, `ValvePlaceholder3DComponent`, `Box3DComponent`). But
   `VerticalTank3DComponent`, `HorizontalVessel3DComponent`, `HeatExchanger3DComponent`, and
   `PumpPlaceholder3DComponent` unconditionally emit `"tag": self.tag` (which can be `None` — a value
   the JSON schema's `_STRING_SCHEMA` for `tag` would actually reject, since it requires
   `minLength: 1`/string type... **note**: since `tag` isn't in each component-type's `required` list
   except where explicitly listed (e.g. `vertical_tank_3d` requires `tag`), emitting `null` there would
   only fail validation if the schema branch requires `tag` — which `vertical_tank_3d`,
   `horizontal_vessel_3d`, `heat_exchanger_3d`, and `pump_placeholder_3d` all do — so in practice this
   is masked by those same four types *requiring* a tag anyway, but it's inconsistent style and would
   break if a caller ever constructed one of these dataclasses without a tag then called
   `to_scene_component()` directly outside a schema-validating context). `SkidBase3DComponent` is the
   odd one out — it **never** emits `tag` at all, even conditionally, matching the schema (skid_base_3d
   doesn't include `tag` in its property set... actually it does allow `tag` via `_base_properties`,
   just doesn't require it — so `SkidBase3DComponent` simply can't express a tag if given one, a
   minor feature gap).
5. **`component_examples.available_cad3d_component_examples()` has a heterogeneous return-value
   contract**: two entries return `CAD3DComponentScene` instances (which have `.to_scene_data()`), one
   (`"routed_tank_pump_separator"`) returns a `_CAD3DSceneDataExample` wrapper dataclass (also has
   `.to_scene_data()`, but is a different type) — callers must treat the catalog as
   "anything with a `.to_scene_data()` method", not as a single concrete type. This is exactly why
   `_CAD3DSceneDataExample` exists (to paper over the raw-dict-vs-object mismatch), but it means the
   catalog's advertised return type (`dict[str, Callable[[], Any]]`) is deliberately loose.
6. **`pump_placeholder_3d` and `valve_placeholder_3d` render identically** (both `AddBox`) — there is
   no visual distinction between equipment types beyond layer color and tag/metadata text; anyone
   inspecting the resulting DWG geometry without reading layer/tag data cannot tell a pump from a
   valve from a generic box. Same is true for `saddle_support_3d`/`pipe_support_3d`/`skid_base_3d`/
   `box_3d` (all boxes) and for `heat_exchanger_3d`/`nozzle_3d`/`flange_3d`/`support_leg_3d` (all
   cylinders, differentiated only by aspect ratio/orientation).
7. **No arbitrary rotation support.** `orientation` is always one of `X`/`Y`/`Z` (axis-aligned only).
   There's no way to place equipment at an arbitrary yaw/pitch/roll — consistent across the schema,
   the component dataclasses, and the executor's `_rotate_cylinder_to_orientation` (which only handles
   the 3 cardinal cases and raises `AutoCAD3DExecutionError` for anything else, though schema
   validation would already reject a non-X/Y/Z orientation before execution is reached).
8. **`pipe_run_3d` solid-cylinder segments must be strictly axis-aligned** (`_is_axis_aligned_segment`,
   tolerance `1e-6`). A diagonal segment (any two points not sharing exactly 2 of 3 coordinates)
   silently downgrades that segment to a plain centerline `AddLine`, even if `visual_style="solid"`
   was requested — this is a deliberate, tested fallback
   (`test_pipe_run_diagonal_segment_falls_back_to_add_line`), not a bug, but it means **AI- or
   template-authored pipe routes with diagonal jogs will render as thin lines for those segments**
   rather than solid pipe, which could look inconsistent in a "solid" style scene without the caller
   realizing it (the return value only reports `created` counts, not which segments fell back).
9. **No mesh/extrusion/block-insert geometry anywhere** in the executor — everything is `AddCylinder`/
   `AddBox`/`AddLine`/`AddText`. This is much simpler than a "real" piping isometric tool (no true
   pipe fittings like elbows/tees, no bolted-flange detail, no valve handle geometry) — it's
   explicitly a **placeholder/schematic-block visualization**, not a fabrication-grade 3D model. This
   matches the naming convention (`*_placeholder_3d` for pump/valve) and the `assumptions` arrays
   present in nearly every example/template scene (e.g. "Pipe runs are represented as 3D centerline
   placeholders in this phase.").
10. **`scene_store.py` has zero concurrency control** (see §7) — acceptable for the app's apparent
    single-user/single-process local-desktop usage pattern, but would need locking (file locks or a
    real DB) before any multi-worker/multi-request-concurrency deployment.
11. **The `_CAD3D_CACHE` dict in `src/api/routes/cad3d.py`** (module-level, in-process, never expires
    or bounds its size) is a *separate* ephemeral store from `CAD3DSceneStore`, used only by
    `/approve`. A restart of the API process loses all cached-but-not-yet-approved tokens (by design —
    approval must happen in the same process lifetime as generation), which is a UX trap if the server
    restarts between `/generate` and `/approve` calls (the user would get a 404 "token was not found or
    has expired").
12. **Deterministic-fallback confidence is a blunt heuristic.** `match_cad3d_template`'s keyword
    scoring (§4) has no fuzzy matching, synonyms beyond the hardcoded term tuples, or negation handling
    — e.g. a prompt saying "NOT a dual pump skid, just one pump" would still match `dual_pump_skid` if
    it contains the phrase "dual pump" as a substring. This is a low-stakes fallback path (only invoked
    when the AI planner itself fails), so the risk is limited to degraded-but-still-valid output in an
    already-degraded scenario.
13. **Parallel structure with the PID framework, but zero code sharing** beyond the very low-level COM
    helpers (`_com_retry`, `_get_acad`, `_activate_regen_zoom`, etc. from
    `src/framework/commands/executor.py` and `src/parametric/vessel/dwg_export.py`). Anyone extending
    both frameworks in tandem (e.g. adding a new "auto-layout" feature) will need to implement it
    twice with no shared abstraction layer to hook into.

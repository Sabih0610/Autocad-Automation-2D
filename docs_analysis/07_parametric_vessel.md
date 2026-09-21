# Parametric Vessel Subsystem — Deep Reference (`src/parametric/vessel/`)

This document is a from-scratch, exhaustive read of the parametric-vessel code, its four
reference docs (`docs/vessel_geometry_rules.md`, `docs/vessel_known_issues.md`,
`docs/vessel_output_format.md`, `docs/vessel_parameters.md`), and its test suite
(`tests/parametric/test_geometry.py`, `test_parameters.py`, `test_view_consistency.py`,
`test_vessel_planner.py`, `test_vessel_planner_live.py`). All file references below are
repo-relative paths from `F:\RC-Projects\autocad-ai\autocad-ai`. Line numbers refer to the
state of the files as read on 2026-09-19.

All findings in Section 7 that claim a specific runtime behavior (e.g. sheet-scale selection)
were **verified by actually executing the code** against the project's own `venv`
(`venv\Scripts\python.exe`), not inferred from reading alone.

---

## 1. Role in the system

`src/parametric/vessel/` is the **deterministic, non-AI engineering core** of the vessel
feature. It takes a fully-specified set of pressure-vessel parameters (shell diameter,
tangent-to-tangent length, head type, nozzles, saddles) and produces exact 2D geometry and a
complete multi-view engineering drawing (front/side/top views, dimensions, title block, BOM)
with no reliance on a language model. Every number it produces — shell radius, head ellipse
axes, nozzle insertion points, flange sizes, saddle positions — is computed from closed-form
formulas and lookup tables (ASME/ANSI-style conventions, `fluids` schedule-40 pipe data), not
generated or guessed by AI. The only AI-touching code adjacent to this subsystem is
`src/ai/vessel_planner.py`, which turns a natural-language request into the same JSON shape
this subsystem's `VesselParameters` expects, and is a *one-way, best-effort* translator: the
AI "does not validate engineering... does not draw CAD" (its own module docstring, 
`src/ai/vessel_planner.py:9-12`); `validate_parameters()` in this subsystem is the actual
authority, called again independently by every render entry point. The FastAPI route
`src/api/routes/vessel.py` wires the two together as a two-step web workflow:
`POST /api/generate-vessel/extract` (AI extraction, cached under a UUID token with a 10-minute
TTL) then `POST /api/generate-vessel/confirm` (deterministic `validate_parameters()` +
`render_vessel()`, optionally spinning up a `pythoncom` context for DWG export). If validation
fails at confirm-time, the token is discarded and the caller must re-extract.

Within this subsystem, `parameters.py` and `geometry.py` are pure math with no I/O and no
`ezdxf`/COM imports; everything from `dimstyle.py` onward writes real DXF/DWG output using
`ezdxf`, and only `dwg_export.py` touches AutoCAD (via COM).

---

## 2. Parameter model (`src/parametric/vessel/parameters.py`)

All linear values are millimeters; nozzle sizes are inches NPS; angles are degrees (module
docstring, lines 1-5).

### Enums

| Enum | Members | Notes |
| --- | --- | --- |
| `HeadType` (line 13) | `ELLIPSOIDAL_2_1 = "ELLIPSOIDAL_2_1"` | Only one member exists; "future head types are reserved" per docs. |
| `Orientation` (line 19) | `HORIZONTAL = "HORIZONTAL"` | Only horizontal vessels supported. |
| `NozzlePosition` (line 25) | `TOP`, `BOTTOM`, `LEFT_END`, `RIGHT_END`, `SIDE_FRONT`, `SIDE_BACK` | String values equal member names. |

### `Nozzle` dataclass (line 37)

| Field | Type | Units | Default | Validation (in `validate_parameters`) |
| --- | --- | --- | --- | --- |
| `tag` | `str` | n/a | — (required) | non-empty; unique across the vessel's nozzles (`"Duplicate nozzle tag: {tag}."`) |
| `nominal_size_inches` | `float` | in NPS | — (required) | `> 0.0` else `"Nozzle {tag} must have nominal size > 0."` |
| `position` | `NozzlePosition` | n/a | — (required) | must be one of the 6 enum members |
| `axial_position_mm` | `float` | mm | — (required) | `0 <= x <= tangent_to_tangent_mm` else `"...axial position must be between 0 and the tangent-to-tangent length."`; **for `LEFT_END`/`RIGHT_END` this field is still validated but is ignored by the geometry solver**, which places end nozzles on the head apex instead (see §3). |
| `radial_angle_degrees` | `float` | deg | `0.0` | `0 <= x <= 360` else `"...radial angle must be between 0 and 360 degrees."`; only meaningful for `SIDE_FRONT`/`SIDE_BACK`. |
| `projection_mm` | `float` | mm | `150.0` | not explicitly range-checked in `validate_parameters` (docs claim `> 0`, but the code has no such check — see §7). |

Duplicate-location check (lines 159-170): builds a key
`(position.value, axial_position_mm, angle)` where `angle` is `0.0` for
`TOP`/`BOTTOM`/`LEFT_END`/`RIGHT_END` and the nozzle's `radial_angle_degrees` for side
positions (`_location_angle_for_validation`, line 186); a repeated key produces
`"Nozzle {tag} duplicates another nozzle location at {location_key}."`.

### `Saddle` dataclass (line 49)

| Field | Type | Units | Default | Validation |
| --- | --- | --- | --- | --- |
| `axial_position_mm` | `float` | mm | — (required) | `0 <= x <= tangent_to_tangent_mm` |
| `width_mm` | `float` | mm | `200.0` | not directly range-checked; used in the no-overlap check |
| `height_mm` | `float` | mm | `1000.0` | not directly range-checked; **replaced with `0.5 * internal_diameter_mm` only when the whole saddle list starts empty** (see `default_saddles_for`, and §7c for the important caveat) |

No-overlap check (lines 172-181): saddles sorted by `axial_position_mm`; for each adjacent
pair, if `left.axial_position_mm + left.width_mm/2 >= right.axial_position_mm - right.width_mm/2`
the errors list gets `"Saddles must not overlap."`.

### `VesselParameters` dataclass (line 58)

| Field | Type | Units | Default | Validation |
| --- | --- | --- | --- | --- |
| `tag` | `str` | n/a | — (required) | non-empty after `.strip()` else `"Vessel tag must be a non-empty string."` |
| `internal_diameter_mm` | `float` | mm | — (required) | `>= 100.0` else `"Internal diameter must be at least 100 mm."` |
| `tangent_to_tangent_mm` | `float` | mm | — (required) | `>= 200.0` else `"Tangent-to-tangent length must be at least 200 mm."` |
| `head_type` | `HeadType` | n/a | `ELLIPSOIDAL_2_1` | not independently checked (enum already constrains it) |
| `wall_thickness_mm` | `float` | mm | `10.0` | `> 0.0`, and (if diameter `> 0`) strictly `< internal_diameter_mm / 4.0`, else `"Wall thickness must be less than one quarter of the internal diameter."` |
| `orientation` | `Orientation` | n/a | `HORIZONTAL` | not independently checked |
| `nozzles` | `list[Nozzle]` | n/a | `[]` | see above, per-nozzle |
| `saddles` | `list[Saddle]` | n/a | `[]` | if empty at validation time, **mutated in place** to `default_saddles_for(...)` before any error checks run (lines 113-117) |

### Module-level helper functions

- **`default_projection_mm(nominal_size_inches)`** (lines 71-82): `<= 4.0` → `150.0`; `< 10.0`
  (i.e. `4 < x < 10`) → `200.0`; else → `250.0`. Docstring: "The 5 in case is intentionally
  grouped with the 6-8 in band." **This function is defined but never called anywhere in
  `src/`** except by its own test — see §7e; the `Nozzle.projection_mm` dataclass default of
  `150.0` is what every real code path actually uses.
- **`default_saddles_for(diameter_mm, tangent_length_mm)`** (lines 85-100): returns exactly two
  `Saddle`s at `0.2 * tangent_length_mm` and `0.8 * tangent_length_mm`, both with
  `width_mm=200.0` and `height_mm=0.5 * diameter_mm`.
- **`validate_parameters(params) -> list[str]`** (lines 103-183): as described above. It
  **never raises**; it returns an accumulated list of human-readable error strings (empty list
  = valid). It has the important **side effect** of populating `params.saddles` in place
  whenever the incoming list is empty, *before* any validation logic runs — so simply calling
  any of the render functions below (which all call `validate_parameters` internally as a
  guard) is enough to populate default saddles on the caller's own `params` object, even if the
  caller never calls `validate_parameters` directly.
- **`_location_angle_for_validation(nozzle)`** (line 186): private helper used only by the
  duplicate-location check, described above.

### AI hand-off shape (for context — implemented in `src/ai/vessel_planner.py`, not in scope)

`plan_vessel(user_request) -> dict` returns JSON matching `VESSEL_PARAMETER_SCHEMA`
(`src/ai/vessel_planner.py:31-150`): `tag`, `internal_diameter_mm` (100-10000),
`tangent_to_tangent_mm` (200-30000), `wall_thickness_mm` (1-200, default 10),
`head_type`/`orientation` (single enum value each), `nozzles[]` (each with `tag`,
`nominal_size_inches` restricted to the **enum** `[1, 1.5, 2, 3, 4, 6, 8, 10, 12]`, `position`,
`axial_position_mm`, optional `radial_angle_degrees`), `saddles[]` (optional,
`axial_position_mm` + optional `width_mm`/`height_mm`), and `assumptions[]` (free text). Note
the AI schema's nozzle object has **no `projection_mm` property**, and
`extracted_to_vessel_parameters()` (`src/ai/vessel_planner.py:499-550`) never passes
`projection_mm` when constructing `Nozzle(...)` — so every AI-produced nozzle silently gets the
dataclass default of `150.0`mm regardless of size (reinforces §7e).

---

## 3. Geometry engine (`src/parametric/vessel/geometry.py`)

Coordinate system (module docstring, lines 1-11): origin at the left tangent line on the
vessel axis; `+X` = axial length direction (toward the right head); `+Y` = vertical up;
`+Z` = out of the side elevation toward the viewer. All linear values mm; nozzle sizes inches
NPS. Only non-stdlib imports: `math` and `from fluids import piping` (line 17-18) — **no
numpy/scipy import anywhere in this module or the rest of `src/parametric/vessel/`**, even
though both are pinned in `requirements.txt` (`numpy==2.4.4`, `scipy==1.17.1`); those are
transitive dependencies of `fluids==1.3.0` and/or used elsewhere in the app (e.g. CAD3D), not
by this subsystem directly.

### `ANSI_B16_5_150_RF_FLANGE_OD_MM` (lines 22-32)

Hardcoded dict, Class 150 RF slip-on flange OD by NPS (inches → mm):
`1→110, 1.5→125, 2→150, 3→190, 4→230, 6→280, 8→345, 10→405, 12→485`. **Only these 9 NPS
values are supported** — any other NPS raises `ValueError` (see `_lookup_flange_od_mm` below).
This is the exact same set the AI schema's nozzle `nominal_size_inches` enum restricts to
(`src/ai/vessel_planner.py:95`), so the two lists must be kept in sync manually if a new NPS is
ever added.

### `compute_shell_outline(params) -> dict` (lines 35-50)

- `shell_outer_radius_mm = internal_diameter_mm/2 + wall_thickness_mm` (via
  `_shell_outer_radius_mm`, line 223-224).
- `shell_inner_radius_mm = internal_diameter_mm/2`.
- `top_line` = `((0, +shell_outer_radius_mm), (tangent_to_tangent_mm, +shell_outer_radius_mm))`;
  `bottom_line` is the mirror at `-shell_outer_radius_mm`.
- `left_tangent_x = 0.0`, `right_tangent_x = tangent_to_tangent_mm`.
- For V-201 (ID 2000, wall 10): outer radius = 1010mm, inner radius = 1000mm — verified by
  `tests/parametric/test_geometry.py:30-42`.

### `compute_head_arc(params, side) -> dict` (lines 53-87)

For a 2:1 ellipsoidal head:
- `major_axis_mm = shell_outer_radius_mm` (e.g. 1010mm for V-201).
- `minor_axis_mm = major_axis_mm / 2.0` (e.g. 505mm for V-201).
- Left head: `center=(0,0)`, `start_angle_degrees=90`, `end_angle_degrees=270`,
  `extends_negative_x=True`. Right head: `center=(tangent_to_tangent_mm, 0)`,
  `start_angle_degrees=270`, `end_angle_degrees=90`, `extends_negative_x=False`.
- `side` must be `"left"`/`"right"` (case-insensitive) or `ValueError("Head side must be
  'left' or 'right'.")`.
- **`extends_negative_x` is computed but never read by any drawing code** — see §7h.
- Internal (nominal) head depth used elsewhere for length/centerline math is a *separate*
  quantity: `_head_depth_inner_mm(params) = internal_diameter_mm / 4.0` (line 227-228; 500mm for
  V-201) — this is the value `docs/vessel_geometry_rules.md` calls the "internal head depth,"
  distinct from the 505mm outer-profile `minor_axis_mm` above. The two numbers are intentionally
  different (documented in `vessel_geometry_rules.md` and confirmed by
  `test_overall_length_uses_internal_head_depth` vs. `test_compute_head_arc_left_returns_expected_minor_axis`
  in `tests/parametric/test_geometry.py`): overall vessel length uses the 500mm internal depth;
  the drawn head ellipse outline uses the 505mm outer-profile minor axis.

### `compute_nozzle_geometry(params, nozzle) -> dict` (lines 90-147)

Per-position insertion point and direction (vessel-local X/Y/Z):

| `position` | `insertion_point` | `direction` |
| --- | --- | --- |
| `TOP` | `(axial_position_mm, +shell_outer_radius_mm, 0)` | `(0, 1, 0)` |
| `BOTTOM` | `(axial_position_mm, -shell_outer_radius_mm, 0)` | `(0, -1, 0)` |
| `LEFT_END` | `(-head_depth_mm, 0, 0)` — **ignores `axial_position_mm`** | `(-1, 0, 0)` |
| `RIGHT_END` | `(tangent_to_tangent_mm + head_depth_mm, 0, 0)` — **ignores `axial_position_mm`** | `(1, 0, 0)` |
| `SIDE_FRONT`/`SIDE_BACK` | `(axial_position_mm, R·sin(θ), R·cos(θ))` where `R=shell_outer_radius_mm`, `θ = _resolved_side_angle_degrees(nozzle)` | `(0, sin θ, cos θ)` |

`_resolved_side_angle_degrees` (lines 231-236): `SIDE_FRONT` → `radial_angle_degrees` as-is;
`SIDE_BACK` → `(180 + radial_angle_degrees) % 360` (so a stored `0°` on `SIDE_BACK` resolves to
physical `180°`, i.e. `-Z`, pointing away from the viewer by default). Per the sin/cos formula:
`0°→+Z`, `90°→+Y (top)`, `180°→-Z`, `270°→-Y (bottom)` — matches
`docs/vessel_geometry_rules.md`'s "Nozzle Projection Rules" table exactly, confirmed by
`test_compute_nozzle_geometry_for_side_front_90_deg_rotates_to_top` and the `SIDE_BACK`
equivalents in `tests/parametric/test_geometry.py`.

`tip_point = insertion_point + direction * projection_mm` (lines 122-126).

Pipe/flange metadata (lines 128-146):
- `_, pipe_id_m, pipe_od_m, pipe_wall_m = piping.nearest_pipe(NPS=nozzle.nominal_size_inches,
  schedule="40")` — this is the **only** use of the `fluids` library in the subsystem. It
  returns schedule-40 pipe dimensions in **meters**; the code converts to mm and rounds to 3
  decimals (`round(x * 1000.0, 3)`) for `pipe_od_mm`, `pipe_id_mm`, `wall_thickness_mm` (pipe
  wall, not vessel wall — same key name as the vessel-level field, easy to confuse).
- `flange_od_mm = _lookup_flange_od_mm(nominal_size_inches)` — raises `ValueError(f"No ANSI
  B16.5 Class 150 RF flange OD reference is defined for NPS {nominal_size_inches}.")` for any
  NPS not in the 9-entry table (confirmed by
  `test_compute_nozzle_geometry_rejects_unsupported_flange_size` using `5.0`in).
- Returned dict also carries `nozzle_tag`, `nominal_size_inches`, `position`,
  `axial_position_mm`, `insertion_point`, `tip_point`, `centerline_direction`, `projection_mm`.
  **`pipe_id_mm` and the pipe `wall_thickness_mm` are computed but never consumed by any
  drawing module** — see §7h.

### `compute_saddle_geometry(params, saddle) -> dict` (lines 150-189)

Longitudinal (front-view-style) 2D outline for one saddle, sampled with **11 points across the
saddle width (10 segments)**:
- `half_width_mm = saddle.width_mm/2`; `base_half_width_mm = half_width_mm + 50.0`;
  `base_y = -shell_outer_radius_mm - saddle.height_mm`.
- For `index in range(11)`: `x_offset` steps linearly from `-half_width_mm` to `+half_width_mm`
  in `width_mm/10` increments; `y_on_shell = -sqrt(max(shell_outer_radius_mm² - x_offset², 0))`
  (i.e. samples the underside of the shell circle), plus a `1.0`mm overlap fudge.
- Final `outline_points` = `[base-left, shell-left-edge, *11 top points, shell-right-edge,
  base-right]` = **15 points total** (matches
  `test_compute_saddle_geometry_returns_expected_point_count`).
- `contact_angle_degrees = 120.0` (fixed design metadata, not geometrically derived from the
  outline).
- For V-201's first default saddle: `base_y = -1010 - 1000 = -2010`mm (matches
  `test_compute_saddle_geometry_returns_expected_base_level`).

### `compute_centerlines(params) -> dict` (lines 192-220)

- `main_horizontal` = `((-head_depth_mm - 100, 0), (tangent_to_tangent_mm + head_depth_mm +
  100, 0))` using the **internal** head depth (`_head_depth_inner_mm`). For V-201:
  `((-600, 0), (5100, 0))` (matches
  `test_compute_centerlines_returns_expected_main_horizontal_line`).
- For each nozzle: `nozzle_centerlines[i].line = (start_point, end_point)` where
  `start_point = _axis_point_for_nozzle(params, nozzle)` (on the vessel axis; for `LEFT_END`/
  `RIGHT_END` this is the head-apex point, for everything else it's
  `(axial_position_mm, 0)` — line 247-253) and
  `end_point = tip_point[:2] + direction[:2] * 25.0` (extends 25mm past the flange face, in the
  X-Y plane only — the Z component is dropped).
- Side nozzles with a purely-Z direction (e.g. default `SIDE_FRONT`/`SIDE_BACK` at 0°) have
  `direction[:2] == (0, 0)`, so their 2D centerline **collapses to a single point**
  (`start_point == end_point`), confirmed by
  `test_compute_centerlines_projects_side_front_default_to_axis_point_in_side_view`. This X-Y
  projection is what feeds `draw_front_view_centerlines` (front elevation), **not**
  `draw_side_view.py`'s own centerline drawing (see §4 and §7c for the terminology nuance).

---

## 4. Drawing generation

### `dimstyle.py` — `setup_vessel_dimstyle(doc)` (lines 17-49)

Creates/updates one ezdxf `DIMSTYLE` named `STANDARD_VESSEL` (`DIMSTYLE_NAME`, line 14). Sets
`doc.header["$INSUNITS"] = 4` (DXF code for millimeters). Style settings: `dimtxt=120.0` (text
height, mm at model scale), `dimasz=90.0` (arrow size), `dimexe=60.0` (extension line beyond
dim line), `dimexo=35.0` (offset from measured point), `dimdec=0` (whole-mm display),
`dimtad=1` (text above the dimension line), `dimtih=0`/`dimtoh=0` (text stays horizontal, not
aligned to the dimension line), `dimclrd=dimclre=dimclrt=2` (ACI color 2 = yellow, for the
dimension line/extension lines/text). This style is only actually registered when
`render.py`'s `ensure_vessel_layers()` calls it (line 88 of `render.py`) — the standalone
`render_front_view()`/`render_side_view()`/`render_top_view()` CLI helpers in the individual
view modules do **not** call `setup_vessel_dimstyle`, but they also never add dimension
entities, so this is internally consistent (not a bug).

### `draw_dimensions.py` — front-view dimensioning only

All functions take `msp`, `params`, `origin_x`/`origin_y` and draw onto layer `DIMENSION`
(`LAYER_DIMENSION`, line 23). Every `msp.add_linear_dim(...)` call is immediately followed by
`_render_dimension(dim)` → `dim.render()` (lines 26-28) — **required by ezdxf**: a linear
dimension entity added this way stays an empty/inert `DIMENSION` block reference until
`.render()` builds its actual line/arrow/text geometry, so any future dimension-adding code
must remember this call.

- **`draw_front_view_basic_dimensions`** (lines 68-169): draws, in order —
  1. Tangent-to-tangent length (horizontal dim at `y = -shell_outer_radius - 650`, label
     `"TANGENT-TO-TANGENT"` at `y - 180` more).
  2. Overall design length (from `-design_head_depth` to `tangent_length + design_head_depth`,
     at `y = -shell_outer_radius - 1150`, label `"OVERALL DESIGN LENGTH"`). Note
     `design_head_depth` here is recomputed locally as `internal_diameter_mm/4.0` (line 87)
     rather than imported from `geometry.py`'s private helper — duplicated logic, same formula.
  3. Outside diameter (vertical dim at `x = tangent_length + 900`, label `"OUTSIDE DIA."`).
  4. Delegates to the three helper functions below.
- **`draw_front_view_nozzle_position_dimensions`** (lines 172-252): TOP nozzles get a
  horizontal location dimension from the left tangent, stacked upward by
  `450 + index*350` mm per nozzle (sorted by axial position); BOTTOM nozzles similarly stacked
  downward by `300 + index*300` mm. **All offsets are fixed constants — none scale with vessel
  diameter, length, or nozzle count** (relevant to `docs/vessel_known_issues.md` Issues 2-4;
  see §7f).
  side nozzles (`SIDE_FRONT`/`SIDE_BACK`) get **no position dimension** here, only a callout
  (below).
- **`draw_front_view_saddle_dimensions`** (lines 255-329): draws a width dimension under each
  saddle (`y = -shell_outer_radius - 1650`, label `"SADDLE WIDTH"`) and a from-left-tangent
  position dimension per saddle, stacked downward by `300`mm per saddle index
  (`y = -shell_outer_radius - 2450 - index*300`, label `"SADDLE {n} LOCATION"`).
- **`draw_front_view_nozzle_callouts`** (lines 332-404): draws a text label + leader line per
  nozzle, formatted as `"{tag} - {size}\" 150# RF"` (`_format_nozzle_size`, lines 61-65, drops
  the decimal for whole sizes). Placement is position-specific and uses more fixed offsets
  (e.g. TOP callouts at `y = shell_outer_radius + 2300`, nudged `+250` if `x < 1000`). **`SIDE_BACK`
  nozzles are explicitly skipped** ("Hidden in front view for now", line 392-394) — no callout,
  no leader.

### `draw_front_view.py` — shell/heads/nozzles/saddles/centerlines

`_ensure_layers(doc)` (lines 51-83) creates a custom linetype `CENTER_VESSEL` (dash pattern
`"A,120,-30,30,-30"`, wrapped in `try/except` in case it already exists) and 5 layers:
`SHELL` (color 7), `NOZZLE` (4), `SADDLE` (8), `CENTERLINE` (1, linetype `CENTER_VESSEL`),
`DIMENSION` (2); sets `$LTSCALE=1.0`, `$PSLTSCALE=1` so the dashed centerline linetype displays
correctly at vessel scale.

- **`draw_front_view_shell`** (86-108): two horizontal lines (top/bottom) from
  `compute_shell_outline`.
- **`draw_front_view_heads`** (111-144): for each of `compute_head_arc("left")`/`("right")`,
  draws an `ezdxf` `ELLIPSE` entity with `major_axis=(0, major_axis_mm, 0)` (i.e. the ellipse's
  intrinsic "major axis" is oriented **vertically** on the sheet, magnitude =
  `shell_outer_radius_mm`) and `ratio = minor_axis_mm/major_axis_mm = 0.5`, with
  `start_param`/`end_param` selecting the west half (`0..π`) for the left head or the east half
  (`π..2π`) for the right head. **This means the ellipse's large (major, 1010mm for V-201)
  radius is drawn vertically and the small (minor, 505mm) radius is drawn horizontally/axially
  — see §7a for how this compares with the docs' "horizontal/vertical semi-axis" labels.**
- **`draw_front_view_nozzles`** (236-289): dispatches per position —
  `_draw_vertical_nozzle` (TOP/BOTTOM: two parallel vertical body lines at `±pipe_od/2` plus a
  flange-face line at `±flange_od/2`), `_draw_horizontal_nozzle` (LEFT_END/RIGHT_END: mirror of
  the above along X), `_draw_front_side_nozzle` (SIDE_FRONT: two concentric circles — flange OD
  and pipe OD — since the front elevation looks straight down this nozzle's axis).
  **`SIDE_BACK` nozzles are skipped entirely in front view** (line 287-288).
- **`draw_front_view_saddles`** (291-324): for each saddle, draws the 15-point
  `compute_saddle_geometry` outline as a closed `LWPOLYLINE` on layer `SADDLE`, plus a short
  120mm vertical "tick" line down from the shell at the saddle's axial centerline (not
  documented anywhere, purely a visual marker).
- **`draw_front_view_centerlines`** (327-357): draws the main horizontal centerline and every
  nozzle centerline from `compute_centerlines`, all on layer `CENTERLINE` with linetype
  `CENTER_VESSEL`.
- **`render_front_view(params, output_path)`** (360-380): standalone helper — calls
  `validate_parameters` (raises `ValueError` joining all error strings if any), creates
  `ezdxf.new(dxfversion="R2010", setup=True)`, draws shell+heads+nozzles+saddles+centerlines
  (**no dimensions, no title block**), and `doc.saveas(...)`. Has a `_cli_render_v201()` /
  `if __name__ == "__main__":` entry point for manual testing against `examples.V201`.

### `draw_side_view.py` — end-on (looking down the vessel axis) view

Same `_ensure_layers` pattern, plus an extra `VIEW_LABEL` layer (color 3).

- **`draw_side_view_shell`** (82-96): the shell is drawn as a single **circle** of radius
  `shell_outer_radius_mm` — this is the defining feature of the side/end view.
- **`draw_side_view_nozzles`** (163-243): TOP/BOTTOM nozzles draw as two vertical body lines
  `±pipe_od/2` from the shell circle outward to `shell_outer_radius + projection_mm`, plus a
  flange-face line — same logic for both, since in end view TOP and BOTTOM nozzles look
  identical except for direction. `SIDE_FRONT`/`SIDE_BACK` draw the horizontal equivalent
  (protruding left/right from the circle). `LEFT_END`/`RIGHT_END` nozzles, which point straight
  at/away from the viewer in this view, are drawn as **two concentric circles at the vessel
  center** (flange OD, pipe OD) — same visual convention as `SIDE_FRONT` in the front view.
  Docstring explicitly warns: "Multiple top nozzles with the same radial direction will overlap
  in side view. That is normal for an end projection because axial positions collapse."
  (lines 172-175).
- **`draw_side_view_saddle`** (245-275): draws **exactly one** generic trapezoid saddle symbol
  under the circle — `support_top_y = -shell_outer_radius`, `support_bottom_y =
  -shell_outer_radius - 0.5*internal_diameter_mm`, with a **hardcoded `half_width = 300.0`mm**
  that ignores the actual `saddle.width_mm` of any real `Saddle` in `params.saddles`. Docstring:
  "Since side view collapses both saddles into the same projection, we show one representative
  support under the shell." This function does **not** call `compute_saddle_geometry` at all —
  it is a wholly separate, simplified representation from the front/top views.
- **`draw_side_view_centerlines`** (278-308): draws a horizontal and a vertical centerline
  through the circle, each extending `250`mm past the shell OD (`overhang`). **This is
  independent of `compute_centerlines()` in `geometry.py`** — it does not draw per-nozzle
  centerlines at all in side view.
- **`draw_side_view`** (311-322) composes shell+nozzles+saddle+centerlines and, if
  `include_label` (default `True`), adds a `"SIDE VIEW"` text at `(origin_x - 500, origin_y -
  2300)` on layer `VIEW_LABEL`.
- **`render_side_view`** (334-349): standalone renderer, same pattern as `render_front_view`
  (**no dimensions**).

### `draw_top_view.py` — plan view

Same `_ensure_layers` pattern (with `VIEW_LABEL`).

- **`draw_top_view_shell`/`draw_top_view_heads`** (82-145): same capsule shape as the front
  view — two straight lines plus two ellipse halves, using the *same* `compute_head_arc` major
  axis mapped to the top view's Y (`vessel_half_width`) and minor axis mapped to X
  (`head_depth`) — i.e. the ellipse's intrinsic major axis (1010mm) is again drawn along the
  view's Y and the minor axis (505mm) along X, exactly mirroring `draw_front_view_heads`'s
  convention (the top view's Y represents the vessel's radial/width direction here, analogous
  to the front view's vertical direction).
- **`draw_top_view_nozzles`** (219-330): **TOP** nozzles → two concentric circles (flange
  OD/pipe OD) on the vessel centerline (`center_y=0`) — i.e. drawn as if looking straight down
  the nozzle. **BOTTOM nozzles are skipped entirely** ("Hidden in top view for this pilot",
  line 258-260). `SIDE_FRONT` is drawn **below** the centerline, `SIDE_BACK` **above** it, both
  as a pair of body lines + flange-face line protruding from the shell OD outward by
  `projection_mm` (`_draw_side_nozzle_in_top_view`, lines 173-216). `LEFT_END`/`RIGHT_END` draw
  as protruding body-line pairs + flange face at the actual head-apex `x`/`tip_x` from
  `compute_nozzle_geometry`.
- **`draw_top_view_saddles`** (333-365): unlike the side view, this draws **every** saddle in
  `params.saddles` as its own rectangular band (`x1..x2` from the saddle's real
  `axial_position_mm ± width_mm/2`, full shell width `-shell_or..+shell_or`) — respects real
  per-saddle parameters, unlike `draw_side_view_saddle`.
- **`draw_top_view_centerline`** (368-386): one centerline line only (no per-nozzle
  centerlines), same extents formula as `compute_centerlines`'s `main_horizontal` but
  recomputed locally rather than calling `geometry.py`.
- **`draw_top_view`/`render_top_view`**: same composition pattern; label `"TOP VIEW"` at
  `(origin_x, origin_y - 1350)`; **no dimensions**.

### Cross-view consistency (validated by `tests/parametric/test_view_consistency.py`)

The tests in this file (10 tests, all pure-geometry, explicitly **not** pixel/screenshot
comparisons — see its own docstring, lines 6-11) assert that front/top/side views all derive
from the same shared numbers rather than independently re-deriving them with drift:
tangent-to-tangent length (`shell["right_tangent_x"]`), shell outer radius (used identically by
`compute_shell_outline` and both `compute_head_arc` calls' `major_axis_mm`), head depth/minor
axis equality between left and right heads, overall length (`tangent + 2*internal_head_depth`),
nozzle axial positions surviving unchanged through `compute_nozzle_geometry` regardless of
which view will render them, default saddle positions (`0.2L`/`0.8L`), and that the side view's
circle diameter (`2 * shell_outer_radius_mm`) numerically equals the front view's total OD
height (`2 * shell_outer_radius_mm`, phrased in the test as a hardcoded `2020.0`). **Important
scope note**: nothing in this test file (or elsewhere) checks that the *drawn dimension values*
in `draw_dimensions.py` agree with these numbers — the consistency checks are entirely at the
`geometry.py` data layer, not at the DXF-entity layer.

**All dimensioning in the current codebase is front-view-only.** Neither `draw_top_view.py` nor
`draw_side_view.py` (nor their call sites in `render.py`'s `draw_three_view_layout`) ever invoke
any dimension-drawing function; only `draw_front_view` (the wrapper in `render.py`, not
`draw_front_view.py`'s lower-level shell/heads/nozzles functions) calls
`draw_front_view_basic_dimensions`. This is not stated in any of the four docs (see §7g).

---

## 5. Sheet/export (`sheet.py`, `dwg_export.py`, `render.py`, `batch_render.py`)

### `sheet.py` — title block, BOM, scale selection, view placement

- **`PaperSize`** (frozen dataclass, lines 33-39) and the one instance `A1_LANDSCAPE =
  PaperSize("A1 LANDSCAPE", 841.0, 594.0)` (line 82) — real ISO A1 landscape paper size in mm.
- **`SheetLayout`** (frozen dataclass, lines 41-79) bundles: chosen `paper`,
  `scale_denominator`/`scale_text` (e.g. `"1:20"`), overall `sheet_width`/`sheet_height` (paper
  mm × scale denominator = *modelspace* mm), border coordinates (`border_left` wider than
  `border_other`, ISO drafting convention for a binding margin), `inner_*`/`title_*`/`bom_*`/
  `drawing_area_*` rectangles, and the three views' chosen `*_origin_x`/`*_origin_y`.
- **`SCALE_OPTIONS = [10, 20, 50, 100]`** (line 85) — tried in this order (tightest first).
  `FIT_TOLERANCE_MM = 500.0` (line 90) — a deliberate slack added when checking whether the
  view union fits the drawing area, "because the view bounding box is an estimate, not exact
  geometry" (comment, lines 87-90); this prevents flapping between adjacent scales over a few
  hundred mm of padding uncertainty.
- **`_view_extents_for_current_dimensioned_views(params)`** (lines 170-219): returns hand-tuned
  conservative bounding boxes (in local, undimensioned-origin coordinates) for each of the three
  views, explicitly padded to account for the current dimension/callout layout (comment:
  "Tuned for Phase 18 so V-201 fits A1 at 1:20", line 195). These are **not** derived from the
  actual DXF entities that will be drawn — they are estimates maintained by hand alongside
  `draw_dimensions.py`'s offset constants, so if those offsets change, these estimates must be
  updated manually or the fit/scale decision can silently become wrong.
- **`_compute_raw_view_origins(params)`** (lines 222-286): lays the three views out with FRONT
  at local `(0,0)`, TOP directly above FRONT (`gap_y=120`mm), SIDE to the right of FRONT
  (`gap_x=300`mm), then returns each view's raw origin plus the union bounding box of all three.
- **`_make_layout_for_scale(params, scale_denominator, paper)`** (lines 289-387): for a given
  scale, computes the full `SheetLayout` — paper→modelspace conversion via `_model_value` (mm ×
  scale), a bottom-right title block (200×80 **paper** mm), a bottom-left BOM table (320×80
  paper mm), and centers the three-view union inside whatever drawing area remains above the
  title/BOM row.
- **`choose_sheet_layout(params)`** (lines 390-419): tries each scale in `SCALE_OPTIONS` in
  order, returns the first whose `drawing_area` (width and height) is `>=` the view union minus
  `FIT_TOLERANCE_MM`; if none fit, returns the layout for the *last* (loosest, `1:100`) option
  as a fallback (never raises).
- **`draw_sheet_border`** (422-435): outer sheet rectangle + inner border rectangle.
- **`draw_title_block`** (438-521): bottom-right table, 4 rows × 4 columns, with
  Phase-2-compatible field names `REV`, `DATE`, `DRAWN_BY`, `DRAWING_NO` (per the module
  docstring, lines 10-11) alongside `TITLE`, `SIZE` (`"ID {int(ID)}mm x T/T {int(T-T)}mm"`),
  `PROJECT` ("PARAMETRIC VESSEL PILOT"), `SCALE`, `PROJECTION` ("THIRD ANGLE"), `SHEET`
  ("1 OF 1"), `STATUS` ("PRELIMINARY"), `CHECKED`/`APPROVED`/`ZONE`/`CLIENT`/`PAGE` (all
  placeholder `"-"`/`"1"`). `DRAWN_BY` comes from `_safe_username()` (line 155-157): the
  Windows `USERNAME` (or `USER`) env var, falling back to `"AUTO"`.
- **`draw_nozzle_bom`** (524-611): bottom-left table titled `"NOZZLE SCHEDULE / BOM"`, columns
  `TAG, SIZE, RATING, POSITION, AXIAL POSITION` (rating is **hardcoded** `"150# RF"` for every
  row regardless of actual flange class — there is no per-nozzle rating field in the parameter
  model at all), sorted by nozzle tag, capped at **12 rows** (`max_rows = 12`, line 582) — a
  13th+ nozzle is silently omitted from the BOM table with no warning.
- **`draw_sheet_frame_and_tables`** (614-622): composes border + BOM + title block.

### `dwg_export.py` — AutoCAD COM conversion (module docstring: "AutoCAD must be running.")

- DWG version constants (lines 17-22): `DWG_R2018=64`, `DWG_R2013=60`, `DWG_R2010=48`,
  `DWG_R2007=36` (these are `AcSaveAsType` COM enum values used with `Document.SaveAs`); default
  export target is `DWG_R2018`, matching `docs/vessel_output_format.md`'s "Target DWG version:
  DWG 2018".
- **`_get_acad()`** (lines 76-83): `win32com.client.GetActiveObject("AutoCAD.Application")` —
  attaches to an **already-running** AutoCAD instance; it never launches AutoCAD. Failure raises
  `AutoCADNotRunningError` with a user-facing message ("Open AutoCAD with any drawing active and
  try again.") — this is exactly the exception `src/api/routes/vessel.py:230-241` catches to
  return a friendly `ok:false` response.
- **`_com_retry(operation, description, attempts=5, delay_seconds=0.5)`** (lines 52-73): retries
  up to 5 times with linearly-increasing backoff (`delay_seconds * attempt`) when
  `_is_busy_error(exc)` is true. `_is_busy_error` (lines 36-49) treats a `pywintypes.com_error`
  with HRESULT `RPC_E_CALL_REJECTED` (`-2147418111`) or `RPC_E_SERVERCALL_RETRYLATER`
  (`-2147417846`) as busy, **and also treats any bare `AttributeError` as busy** — a fairly
  broad catch that could mask unrelated bugs inside the wrapped lambda as if they were transient
  COM contention.
- **`convert_dxf_to_dwg(dxf_path, dwg_path, dwg_version=DWG_R2018)`** (lines 86-138): resolves
  paths, requires the source DXF to exist, creates the DWG's parent directory, attaches to
  AutoCAD, `acad.Documents.Open(dxf)` → `time.sleep(0.3)` → `doc.SaveAs(dwg_path, dwg_version)`
  → `doc.Close(False)` (discard changes on close since it was just saved as the target). Any
  failure during save/close is wrapped as `DwgExportError`, and the code makes a best-effort
  `doc.Close(False)` in the `except` block too (swallowing secondary close failures).
- **`convert_batch(pairs, dwg_version, pause_between_seconds=1.5)`** (141-165): sequential
  conversions with a fixed pause between each (not used anywhere in the current pipeline —
  `batch_render.py` only produces DXFs, never calls this).

### `render.py` — combines everything into one sheet DXF, optional DWG

- **`ensure_vessel_layers(doc)`** (54-88): the "complete" layer setup — all 7 layers (`SHELL`,
  `NOZZLE`, `SADDLE`, `CENTERLINE`, `DIMENSION`, `VIEW_LABEL`, `SHEET` [color 6]) plus the
  `CENTER_VESSEL` linetype, **and** calls `setup_vessel_dimstyle(doc)` — this is the only place
  in the codebase where the dimstyle actually gets registered.
- **`draw_front_view(msp, params, origin_x, origin_y, include_label=True,
  include_dimensions=True)`** (108-132): this is `render.py`'s **own** wrapper (not to be
  confused with `draw_front_view.py`'s lower-level functions it calls) — composes shell + heads
  + nozzles + saddles + centerlines, optionally dimensions
  (`draw_front_view_basic_dimensions`), optionally a `"FRONT VIEW"` label at
  `(origin_x, origin_y - 4300)`.
- **`draw_three_view_layout(msp, params, layout)`** (135-164): calls the front-view wrapper
  above plus `draw_top_view`/`draw_side_view` (imported directly from their own modules) at the
  `SheetLayout`'s computed origins — **only the front view gets `include_dimensions=True`**
  (top/side calls don't even expose that parameter).
- **`render_vessel_dxf(params, output_path) -> SheetLayout`** (167-193): validates params,
  `choose_sheet_layout(params)`, `ezdxf.new(dxfversion="R2010", setup=True)`,
  `ensure_vessel_layers`, draws frame+tables then the three-view layout, `doc.saveas(...)`,
  returns the chosen `SheetLayout` (so callers can report the selected scale/paper).
- **`render_vessel(params, output_path, output_format="dxf", dwg_version=DWG_R2018) -> dict`**
  (196-254): the public entry point used by `src/api/routes/vessel.py`. For `"dxf"`: just calls
  `render_vessel_dxf` and returns `{ok, format, path, scale, sheet, message}`. For `"dwg"`:
  forces the output path's suffix to `.dwg`, derives an intermediate path by swapping the
  suffix to `.dxf` (i.e. **same basename**, so the DXF intermediate is always kept alongside the
  final DWG — "Keeps the intermediate DXF for debugging" per the module docstring), renders that
  DXF via `render_vessel_dxf`, then calls `convert_dxf_to_dwg`. Any other `output_format` raises
  `ValueError`. **The intermediate DXF is always written with `dxfversion="R2010"`** regardless
  of the requested/target DWG version — AutoCAD's `SaveAs` is what actually up-converts to the
  target DWG schema (2018/2013/2010/2007); this distinction is not called out in
  `docs/vessel_output_format.md` (see §7i).
- Has its own `_cli_render_v201()` test entry point (writes only a DXF, not DWG).

### `batch_render.py` — render every example vessel in one pass

- **`safe_filename(name)`** (25-32): replaces ` `, `/`, `\`, `:` with `_` for filesystem safety.
- **`batch_render_all() -> Path`** (35-97): creates
  `outputs/vessels/batch_{YYYY-MM-DD_HH-MM-SS}/` under the project root
  (`Path(__file__).resolve().parents[3]`, i.e. 3 levels up from
  `src/parametric/vessel/batch_render.py` → project root), iterates
  `examples.get_all_examples()`, for each: runs `validate_parameters` first (skips render and
  counts as a failure if there are errors, printing each error), else calls
  `render_vessel_dxf` and prints `STATUS: OK`, the output path, paper name, scale text, and
  modelspace sheet size; on any exception during render, prints `STATUS: FAILED RENDER` plus
  the full traceback (`traceback.format_exc()`). Prints a final `Success`/`Failed` tally. **DXF
  only — never produces DWGs and never calls `dwg_export.py`.**
- `main()` is the `python -m src.parametric.vessel.batch_render` CLI entry point.
- This is exactly the tool `docs/vessel_known_issues.md` describes running to produce its
  Phase-18 "batch_2026-04-28_23-54-11" folder and the 5 example DXFs it discusses.

---

## 6. `examples.py` — canonical vessel fixtures

`get_all_examples() -> dict[str, VesselParameters]` (lines 221-228) returns exactly these five,
used both by the test suite (`test_parameters.py::test_get_all_examples_returns_v201`) and by
`batch_render.py`:

| Key | Tag | ID (mm) | T-T (mm) | Wall (mm) | Nozzles | Purpose (inferred from name/shape and `vessel_known_issues.md`) |
| --- | --- | --- | --- | --- | --- | --- |
| `V201` | `V-201` | 2000 | 4500 | 10 | N1 6" TOP@1500, N2 8" BOTTOM@3000, N3 2" SIDE_FRONT@2250, N4 3" TOP@500 | **The** canonical reference vessel used throughout the docs (`vessel_parameters.md`'s worked example) and most tests; exercises every nozzle position except LEFT/RIGHT_END and SIDE_BACK. |
| `V202_SMALL` | `V202_SMALL` | 500 | 1500 | 6 | N1 2" TOP@500, N2 2" BOTTOM@1000 | Smallest vessel in the set — exercises the "dimension crowding relative to small body" scenario (known-issues Issue 2). |
| `V203_LONG` | `V203_LONG` | 1500 | 8000 | 12 | 8 nozzles (N1-N8), incl. one `SIDE_FRONT` and one `SIDE_BACK` | Longest vessel with the most nozzles — exercises nozzle/callout crowding along a long shell (known-issues Issue 3) and is the only example using `SIDE_BACK`. |
| `V204_END_NOZZLES` | `V204_END_NOZZLES` | 1200 | 3500 | 10 | N1 4" LEFT_END@0, N2 4" RIGHT_END@3500 | Only example exercising `LEFT_END`/`RIGHT_END` nozzle geometry and drawing paths; also the "too much sheet space" scale-selection edge case (known-issues Issue 5). |
| `V205_CLUSTERED` | `V205_CLUSTERED` | 1800 | 4200 | 10 | N1 3" TOP@1600, N2 3" TOP@1800, N3 4" TOP@2000, N4 2" BOTTOM@1900, N5 2" SIDE_FRONT@1950 | Deliberately tight nozzle spacing (three TOP nozzles 200mm apart) — exercises the "clustered nozzles" dimension/callout collision scenario (known-issues Issues 3-4), described in the doc as intentionally exposing the problem. |

All five omit `saddles` (`saddles=[]`), relying on `validate_parameters`'s default-saddle
population.

---

## 7. Documentation-vs-code diff

Findings are grouped by which doc they relate to. Each is something a future agent should
double-check before trusting the doc text at face value.

### a. `vessel_geometry_rules.md` — ellipse "horizontal/vertical semi-axis" labels don't match the axis the code actually draws them on

The doc says (lines 8-10): "horizontal semi-axis: `ID/2 + wall_thickness`" (the *larger* value,
1010mm for V-201) and "vertical semi-axis: `(ID/2+wall)/2`" (the *smaller* value, 505mm). But in
`draw_front_view_heads` (`draw_front_view.py:124-129`), the **larger** value
(`head["major_axis_mm"]`) is assigned to `vertical_radius` and used as the ellipse's vertical
(`major_axis=(0, vertical_radius, 0)`) direction, while the **smaller** value
(`head["minor_axis_mm"]`) becomes `horizontal_depth` and drives the ratio that determines the
horizontal (axial) extent. `draw_top_view_heads` does the analogous thing
(`vessel_half_width`/`head_depth`, lines 125-129 of `draw_top_view.py`). In other words: the
**numeric values match** between doc and code (1010/505 for V-201), but the doc's plain-English
labels for which one is "horizontal" and which is "vertical" are the **opposite** of how the
code actually orients them when drawing. A future agent relying on the doc's prose to reason
about which direction the head bulges should re-derive it from the code
(`compute_head_arc`/`draw_front_view_heads`) rather than trust the "horizontal"/"vertical"
words.

### b. `vessel_geometry_rules.md`'s "Phase 13 returns pure geometry data only. No drawing entities are created yet." is stale

This is true of `geometry.py` itself (still pure math, no `ezdxf` import), but the sentence
reads as a subsystem-wide statement and the subsystem now includes an extensive DXF/DWG
drawing and export pipeline (`draw_front_view.py`, `draw_side_view.py`, `draw_top_view.py`,
`draw_dimensions.py`, `sheet.py`, `dwg_export.py`, `render.py`, `batch_render.py`) built in
later phases (14-19+) after this doc's "Phase 13" framing. Worth flagging as an outdated
snapshot rather than a live contract for anything beyond `geometry.py` proper.

### c. `vessel_geometry_rules.md`'s "may collapse to a point in the X-Y side elevation" is a confusing label for what the code does

The doc's Centerline Conventions section (lines 63) says side nozzles "may collapse to a point
in the `X-Y` side elevation." The X-Y projection described is actually
`compute_centerlines()`'s output, which is consumed only by **`draw_front_view_centerlines`**
(the front/elevation view) — `draw_side_view.py` has its own, unrelated centerline function
(`draw_side_view_centerlines`, a fixed horizontal/vertical cross through the circle) that never
calls `compute_centerlines()` at all. Calling the X-Y plane the "side elevation" is inconsistent
with how "side view" is used everywhere else in this codebase (a circular end-on projection).
The underlying math claim (a side nozzle whose direction is purely `+Z`/`-Z` projects to a
single point in `X`-`Y`) is correct; only the view-name terminology is misleading.

### d. `vessel_parameters.md`'s saddle-height auto-correction claim is narrower than it reads

The doc says: "Validation replaces default-generated saddles with `0.5 x
internal_diameter_mm`." In the actual code (`validate_parameters`, `parameters.py:113-117`)
this only happens when `params.saddles` is **completely empty** at validation time (it calls
`default_saddles_for`, which always sets `height_mm=0.5*diameter_mm`). If a caller supplies a
**non-empty** saddle list where an individual `Saddle` was constructed without an explicit
`height_mm` (using the dataclass default of `1000.0`mm), `validate_parameters` does **not**
correct it — the `1000.0`mm placeholder survives untouched. This is concretely reachable through
the AI hand-off path: `src/ai/vessel_planner.py:524-533`'s `extracted_to_vessel_parameters`
builds `Saddle(axial_position_mm=..., width_mm=..., height_mm=float(saddle_data.get("height_mm",
1000.0)))` for every saddle the AI schema supplies (even one with only `axial_position_mm` set),
so an AI-specified single saddle can end up with a silently-wrong `1000.0`mm placeholder height
that no validation step will catch.

### e. `default_projection_mm()` is described as a real feature but is dead code

`docs/vessel_parameters.md`'s "Projection helper" section and `docs/vessel_geometry_rules.md`'s
"Nozzle Projection Rules" section both describe `default_projection_mm(nominal_size_inches)`
(bands: `<=4in→150mm`, `4-10in→200mm`, `>=10in→250mm`) as if it were an active part of the
pipeline ("provided for future callers that want a size-based starting point... callers can opt
in deliberately"). A repo-wide search shows it is **never called** anywhere in `src/` except its
own definition (`parameters.py:71-82`) — not by `geometry.py`, not by `examples.py` (all example
nozzles rely on the flat `150.0`mm dataclass default), and not by `src/ai/vessel_planner.py`
(whose `VESSEL_PARAMETER_SCHEMA` has no `projection_mm` property for nozzles at all, and whose
`extracted_to_vessel_parameters` never passes `projection_mm` to `Nozzle(...)`). In the current
system, **every nozzle, regardless of size, gets a flat 150mm projection** unless a caller
manually constructs a `Nozzle(..., projection_mm=...)` in Python — which no shipped code path
does.

### f. `vessel_known_issues.md`'s "Issue 1 — Scale Selection Too Conservative" is stale; Issues 2-4 are still accurate

Running `choose_sheet_layout()` against every current `examples.py` vessel (verified by
executing the code, not just reading it) gives:

```
V201               scale= 1:20
V202_SMALL         scale= 1:20
V203_LONG          scale= 1:20
V204_END_NOZZLES   scale= 1:20
V205_CLUSTERED     scale= 1:20
```

`docs/vessel_known_issues.md` states the *current* behavior selects `1:50` for V201, V204, and
V205 and that this "is not complete yet because the visual issues still need to be fixed" — but
the code as it stands today already selects `1:20` for **all five** examples. This matches
`sheet.py`'s own inline comment ("Phase 18 update: Tightened view bounding boxes so V-201 can
select 1:20 instead of 1:50," lines 13-15), which post-dates the known-issues narrative. **Issue
1 (and Issue 5, the identical root cause for V204) appears to already be fixed** in the current
code; the doc has not been updated to reflect this. By contrast, **Issues 2-4 (dimension
crowding, nozzle callout crowding, clustered-nozzle handling) remain genuinely unfixed**: reading
`draw_dimensions.py` confirms nozzle position dimensions and callouts still use simple
fixed-step offsets (`450 + index*350`, `300 + index*300`, etc. — see §4) with no clustering
detection, no shared/stacked baseline dimension, no staggered leader-line logic, and no dynamic
scaling by vessel diameter or tangent length — i.e. none of the doc's "Proposed fix" bullet
points for Issues 2-4 have been implemented.

### g. Undocumented: dimensioning is front-view-only

None of the four docs state this explicitly, but it's an important scope limit: only the front
view ever receives dimension entities (`draw_front_view_basic_dimensions`, called from
`render.py`'s `draw_front_view` wrapper). `draw_top_view`/`draw_side_view` and their call sites
in `render.py`'s `draw_three_view_layout` never call any dimensioning function. A drafter opening
the generated DXF/DWG will see zero dimensions on the top and side views.

### h. Undocumented: several computed geometry fields are never consumed downstream

`compute_head_arc()`'s `extends_negative_x` key (`geometry.py:76,86`) and
`compute_nozzle_geometry()`'s `pipe_id_mm` and (pipe) `wall_thickness_mm` keys
(`geometry.py:143-144`) are computed and tested, but are never read by any of
`draw_front_view.py`/`draw_side_view.py`/`draw_top_view.py`/`draw_dimensions.py`/`sheet.py`.
They may be intended for future detail (e.g., drawing the nozzle bore/ID, or determining head
orientation logic that hasn't been written yet) but are effectively inert today.

### i. Undocumented: DXF intermediate schema version vs. DWG target version

`docs/vessel_output_format.md` states the target DWG version is "DWG 2018" (matches
`DWG_R2018` = AutoCAD COM `SaveAs` type `64`, the default in both `dwg_export.py` and
`render.py`). It does not mention that the DXF file generated as the intermediate step is
**always** written with `dxfversion="R2010"` (`render.py:183`, and independently in each
standalone view module's `render_*` function) — an older DXF schema that AutoCAD upgrades on
`SaveAs`. Anyone debugging the "R2010 intermediate, R2018 final" mismatch should know this is by
design, not an oversight.

### j. Undocumented: 4 scale options exist, not 2

`vessel_known_issues.md` frames the scale discussion entirely around `1:20` vs `1:50`.
`sheet.py`'s `SCALE_OPTIONS = [10, 20, 50, 100]` (line 85) actually tries `1:10` first (tighter
than anything discussed in the docs) and falls back to `1:100` (looser) if even `1:50` doesn't
fit. None of the docs mention `1:10` or `1:100` as possible outputs.

### k. Documented-but-easy-to-miss: `validate_parameters()` mutates its argument

`vessel_parameters.md`'s "Validation behavior" section does state this ("`validate_parameters(params)`
mutates `params.saddles` when the list is empty"), so it is not undocumented — but it's worth
restating precisely for a future agent: because every render entry point
(`render_front_view`, `render_side_view`, `render_top_view`, `render_vessel_dxf`) calls
`validate_parameters(params)` internally as a guard, simply *rendering* a `VesselParameters`
object with an empty `saddles` list is enough to populate `params.saddles` with two default
`Saddle`s as a side effect — even if the caller never explicitly calls `validate_parameters`
themselves first.

---

## 8. Test coverage summary

All counts below were confirmed by actually running the suite:
`venv\Scripts\python.exe -m pytest tests/parametric/test_geometry.py
tests/parametric/test_parameters.py tests/parametric/test_view_consistency.py
tests/parametric/test_vessel_planner.py -q` → **59 passed** (2026-09-19).
`test_vessel_planner_live.py` (1 test) is skipped by default (`pytest.skip(...,
allow_module_level=True)` unless the `RUN_LIVE_AI=1` env var is set — it calls the real AI
provider end-to-end).

| File | Test count | Coverage |
| --- | --- | --- |
| `test_geometry.py` | 26 | `compute_shell_outline` (tangent length, outer/inner radius, top line); `compute_head_arc` (left/right center, minor axis, `extends_negative_x`); `compute_nozzle_geometry` for every position (TOP, BOTTOM, `SIDE_FRONT` at 0°/90°, `SIDE_BACK` at 0°/90° default+rotated, `LEFT_END`, `RIGHT_END`); fluids schedule-40 pass-through; flange OD lookup success + `ValueError` for unsupported NPS (5in); default saddle placement (0.2L/0.8L); `compute_saddle_geometry` point count (15) and base level; `compute_centerlines` main-horizontal extents, nozzle centerline extension length, and side-nozzle point-collapse. |
| `test_parameters.py` | 16 | `validate_parameters` happy path on V-201; default saddle auto-population; every individual error string (missing tag, diameter<100, T-T<200, wall≥ID/4, duplicate nozzle tag, duplicate nozzle location, nominal size≤0, axial position out of range, radial angle out of range, saddle overlap, saddle out of range); `default_projection_mm` bands; enum round-trip through dataclasses; `get_all_examples()` sanity. |
| `test_view_consistency.py` | 10 | Pure cross-checks that front/top/side view math shares the same tangent length, shell outer radius, head depth/minor axis, overall length, nozzle axial positions, default saddle positions, and side-view-diameter == front-view-height. Explicitly documented as *not* visual/pixel tests. |
| `test_vessel_planner.py` | 7 | (Adjacent AI module, not this subsystem, but defines the JSON→`VesselParameters` contract this subsystem consumes.) Conversion correctness, validation pass-through, `format_for_review` text, duplicate-nozzle repair heuristic, missing-default backfill, `plan_vessel` with mocked `ask_ai`. |
| `test_vessel_planner_live.py` | 1 (skipped by default) | End-to-end live-AI extraction of the V-201 prompt, checked against the same shape/counts as `examples.V201`. |

**Coverage gap**: nothing in the test suite opens a generated DXF/DWG and asserts on its actual
entities, layers, dimension placement, or sheet layout. All verification of
`draw_front_view.py`/`draw_side_view.py`/`draw_top_view.py`/`draw_dimensions.py`/`dimstyle.py`/
`sheet.py`/`dwg_export.py`/`render.py`/`batch_render.py` is manual — every module's
`_cli_render_v201()` helper prints "Open this DXF in AutoCAD to verify..." and
`vessel_known_issues.md` documents an actual manual "Visual review completed" pass. A future
agent changing anything in the drawing/sheet/export layer has no automated safety net beyond the
geometry-data-level consistency checks in `test_view_consistency.py`.

---

## 9. Cross-cutting observations

1. **Scale-selection fix already landed; crowding fixes have not.** See §7f — update
   expectations accordingly; don't assume `vessel_known_issues.md`'s "current behavior" section
   still describes the code without re-verifying.
2. **Dimensioning is front-view-only** (§7g) — a real functional gap relative to what a
   finished 3-view engineering drawing would need, and not documented anywhere.
3. **Two inert/dead code surfaces**: `default_projection_mm()` (§7e) and the geometry fields
   `extends_negative_x`/`pipe_id_mm`/nozzle `wall_thickness_mm` (§7h). Anyone asked to "wire up
   size-based nozzle projections" should know the helper already exists but nothing calls it.
4. **`validate_parameters()` mutates its input** (§7k) — a caller inspecting `params.saddles`
   before vs. after calling any `render_*` function will see it change from `[]` to two
   populated `Saddle`s.
5. **Layout constants throughout `draw_dimensions.py` and `sheet.py` are hardcoded mm offsets**,
   not derived from vessel diameter or length (e.g. `650.0`, `1150.0`, `900.0`, `2450.0`,
   `2300.0` in `draw_dimensions.py`; the tuned bounding-box constants in
   `sheet.py:_view_extents_for_current_dimensioned_views`). This is exactly the pattern
   `vessel_known_issues.md` Issue 2's "Proposed fix: Add dynamic dimension offsets based on
   vessel diameter and tangent length" calls out as still needed.
6. **Saddle representation strategy differs per view.** Front view
   (`draw_front_view_saddles`) and top view (`draw_top_view_saddles`) each draw one shape **per
   real saddle** in `params.saddles` (front view via `compute_saddle_geometry`'s 15-point
   outline; top view via a simple rectangle using the saddle's real `axial_position_mm`/
   `width_mm`). Side view (`draw_side_view_saddle`) draws exactly **one generic, hardcoded
   `half_width=300`mm trapezoid** regardless of how many saddles exist or their real widths —
   intentional per its docstring ("side view collapses both saddles into the same projection"),
   but the hardcoded width (not tied to any saddle's actual `width_mm`) is worth knowing before
   trusting the side view's saddle symbol as dimensionally meaningful.
7. **Intentional visibility omissions, not hidden-line rendering.** `BOTTOM` nozzles are fully
   absent from the top view (`draw_top_view_nozzles`, "Hidden in top view for this pilot") and
   `SIDE_BACK` nozzles are fully absent from the front view (`draw_front_view_nozzles` and
   `draw_front_view_nozzle_callouts`, "Hidden in front view for now") — there is no dashed/hidden
   linetype representation, they simply don't get drawn in those views at all.
8. **NPS support is gated by the smaller of two independent lookup tables**, and the AI schema
   duplicates the same 9-value enum a third time. Adding support for a new nozzle size (e.g.
   14in) requires updating `ANSI_B16_5_150_RF_FLANGE_OD_MM` in `geometry.py`, the `nominal_size_inches`
   enum in `src/ai/vessel_planner.py`'s `VESSEL_PARAMETER_SCHEMA`, and confirming `fluids`'s
   schedule-40 table actually has that NPS — three places, no single source of truth.
9. **No numpy/scipy usage anywhere in this subsystem** despite both being pinned in
   `requirements.txt`; the only third-party import in `geometry.py` is `fluids.piping`
   (specifically `nearest_pipe(NPS=..., schedule="40")`), and the only import anywhere in
   `src/parametric/vessel/` beyond `ezdxf`/`fluids`/stdlib is `pywin32`
   (`win32com.client`, `pywintypes`) in `dwg_export.py`.
10. **DWG export requires AutoCAD to already be running** — `dwg_export._get_acad()` uses
    `GetActiveObject`, never `CreateObject`/`Dispatch`, so it will not launch AutoCAD itself; the
    resulting `AutoCADNotRunningError` is what the FastAPI layer (`src/api/routes/vessel.py`)
    surfaces to the user as an actionable message.
11. **The COM-busy retry logic is broad**: `_is_busy_error` in `dwg_export.py` treats *any*
    bare `AttributeError` inside the wrapped COM call as "AutoCAD is busy, retry" — a genuine bug
    in the wrapped lambda that happens to raise `AttributeError` (e.g. a typo'd attribute access)
    would be silently retried up to 5 times before surfacing.
12. **Output directories are consistent** between the CLI/batch tools
    (`Path(__file__).resolve().parents[3] / "outputs" / "vessels"`, computed independently in
    `batch_render.py` and each view module's CLI helper) and the FastAPI route
    (`src/api/routes/vessel.py`'s `VESSEL_OUTPUT_DIR`) — both resolve to the same
    `outputs/vessels/` folder under the project root, so batch-rendered and web-generated files
    are co-located.
13. **The BOM table silently truncates at 12 nozzle rows** (`sheet.py:582`,
    `max_rows = 12`) with no warning or overflow indication — a vessel with 13+ nozzles (none of
    the current examples reach this) would have some nozzles missing from the printed schedule
    even though they're still drawn in the views.

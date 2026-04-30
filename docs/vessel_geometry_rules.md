# Vessel Geometry Rules

All linear dimensions in the vessel geometry math are in millimeters. Nozzle nominal sizes use inches NPS. Angles use degrees.

## 2:1 Ellipsoidal Heads

- Internal head depth is `ID / 4`.
- The outer head profile used by the geometry solver is based on the outer radius, so the ellipse semi-axes are:
  - horizontal semi-axis: `ID / 2 + wall_thickness`
  - vertical semi-axis: `(ID / 2 + wall_thickness) / 2`
- For V-201 with `ID = 2000 mm` and `wall = 10 mm`, the internal head depth is `500 mm` and the outer-profile vertical semi-axis is `505 mm`.
- The Phase 13 math keeps those two numbers distinct on purpose:
  - overall vessel length uses the nominal internal head depth
  - head outline metadata uses the outer-profile ellipse
- The head curve is modeled as the left or right half of an ellipse centered on the tangent line at `(0, 0)` or `(L, 0)`.

## Tangent Line Definition

- The left tangent line is the origin plane: `x = 0`.
- The right tangent line is at `x = tangent_to_tangent_mm`.
- Tangent-to-tangent length is the straight shell length between those two planes.
- The main vessel axis is the horizontal centerline at `y = 0`.

## Coordinate Convention

- Origin: left tangent line on the vessel axis.
- `+X`: vessel length direction, toward the right head.
- `+Y`: vertical upward.
- `+Z`: out of the side elevation toward the viewer.
- Phase 13 returns pure geometry data only. No drawing entities are created yet.

## Nozzle Projection Rules

- Nozzle `projection_mm` is measured from the shell or head outer surface to the flange face.
- Default stub-out convention for this phase is `150 mm`.
- The helper `default_projection_mm()` provides a size-based alternative:
  - `<= 4 in`: `150 mm`
  - `> 4 in` and `< 10 in`: `200 mm`
  - `>= 10 in`: `250 mm`
- Flange face position is the nozzle tip point returned by `compute_nozzle_geometry`.
- Top, bottom, and end nozzles infer their radial direction directly from `position`.
- Side nozzles use rotation about the vessel `X` axis:
  - `0 deg` = `+Z` (`SIDE_FRONT`, toward the viewer)
  - `90 deg` = `+Y` (top)
  - `180 deg` = `-Z` (`SIDE_BACK`, away from the viewer)
  - `270 deg` = `-Y` (bottom)
- For `SIDE_BACK`, the solver adds `180 deg` to the stored radial angle so a stored `0 deg` points away from the viewer by default.

## Saddle Rules

- Default saddles are placed at `0.2L` and `0.8L`, where `L` is tangent-to-tangent length.
- Default saddle height is `0.5 x ID`.
- Default saddle width is `200 mm`.
- Design contact angle is `120 deg`.
- For this pure-math 2D longitudinal phase, the saddle top contour is approximated by sampling the vessel outer shell across the specified saddle width with 10 polyline segments.
- The reported `contact_angle_degrees = 120` remains the design convention that later drawing phases will reuse.
- Web thickness and base plate width are not yet parametrized. Phase 13 returns a simple trapezoid-plus-arc outline for downstream drawing code.

## Centerline Conventions

- The main horizontal centerline runs along the vessel axis and extends `100 mm` beyond each nominal head apex.
- Nozzle centerlines start on the vessel axis, pass through the shell insertion point, and extend slightly beyond the flange face.
- Side nozzles may collapse to a point in the `X-Y` side elevation when their direction is purely along `Z`. That is expected in this phase.

## ANSI B16.5 150# RF Flange OD Reference Table

This phase hardcodes flange outside diameters for nozzle-facing flanges using Class 150 RF slip-on values commonly published from ASME B16.5 tables, rounded to whole millimeters where the reference tables do so.

| NPS (in) | Flange OD (mm) |
| --- | --- |
| `1` | `110` |
| `1.5` | `125` |
| `2` | `150` |
| `3` | `190` |
| `4` | `230` |
| `6` | `280` |
| `8` | `345` |
| `10` | `405` |
| `12` | `485` |

## References

- ASME Section VIII Division 1
- ANSI/ASME B16.5

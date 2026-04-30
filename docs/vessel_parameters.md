# Vessel Parameter Contract

All linear dimensions in the parametric vessel generator are in millimeters. Nozzle nominal sizes use inches NPS. Angles use degrees.

## VesselParameters

| Name | Type | Units | Valid Range | Default | Notes |
| --- | --- | --- | --- | --- | --- |
| `tag` | `str` | n/a | non-empty | none | Equipment tag, for example `V-201`. |
| `internal_diameter_mm` | `float` | mm | `>= 100.0` | none | Internal vessel diameter. |
| `tangent_to_tangent_mm` | `float` | mm | `>= 200.0` | none | Straight shell length between head tangent lines. |
| `head_type` | `HeadType` | n/a | `ELLIPSOIDAL_2_1` | `ELLIPSOIDAL_2_1` | Future head types are reserved. |
| `wall_thickness_mm` | `float` | mm | `> 0` and `< internal_diameter_mm / 4` | `10.0` | Uniform shell and head wall thickness for Phases 11-13. |
| `orientation` | `Orientation` | n/a | `HORIZONTAL` | `HORIZONTAL` | Tier 3a currently supports horizontal vessels only. |
| `nozzles` | `list[Nozzle]` | n/a | zero or more | `[]` | Nozzle definitions. |
| `saddles` | `list[Saddle]` | n/a | zero or more | `[]` | If empty, validation populates two default saddles at `0.2L` and `0.8L`. |

### Validation behavior

- `validate_parameters(params)` mutates `params.saddles` when the list is empty.
- Default saddles are created by `default_saddles_for(diameter_mm, tangent_length_mm)`.
- Validation collects all errors and returns them as a list of strings. It does not raise.

## Nozzle

| Name | Type | Units | Valid Range | Default | Notes |
| --- | --- | --- | --- | --- | --- |
| `tag` | `str` | n/a | non-empty and unique within a vessel | none | Identifier such as `N1`. |
| `nominal_size_inches` | `float` | in NPS | `> 0` | none | Industry-standard nominal pipe size. |
| `position` | `NozzlePosition` | n/a | `TOP`, `BOTTOM`, `LEFT_END`, `RIGHT_END`, `SIDE_FRONT`, `SIDE_BACK` | none | Locates the nozzle on the vessel. |
| `axial_position_mm` | `float` | mm | `0 <= value <= tangent_to_tangent_mm` | none | Measured from the left tangent line along the vessel axis. End nozzles still carry the field for schema consistency, but the geometry solver ignores it and places them on the head apex. |
| `radial_angle_degrees` | `float` | deg | `0 <= value <= 360` | `0.0` | Used for side nozzles. Top, bottom, and end nozzles infer direction from `position`. |
| `projection_mm` | `float` | mm | `> 0` | `150.0` | Stub-out length from the shell or head outer surface to the flange face. |

### Projection helper

`default_projection_mm(nominal_size_inches)` is provided for future callers that want a size-based starting point:

- `<= 4 in`: `150 mm`
- `> 4 in` and `< 10 in`: `200 mm`
- `>= 10 in`: `250 mm`

The dataclass default remains `150 mm` so callers can opt in deliberately.

## Saddle

| Name | Type | Units | Valid Range | Default | Notes |
| --- | --- | --- | --- | --- | --- |
| `axial_position_mm` | `float` | mm | `0 <= value <= tangent_to_tangent_mm` | none | Saddle center measured from the left tangent line. |
| `width_mm` | `float` | mm | positive practical value | `200.0` | Longitudinal saddle footprint used for overlap checks and 2D outline generation. |
| `height_mm` | `float` | mm | positive practical value | `1000.0` | Placeholder default. Validation replaces default-generated saddles with `0.5 x internal_diameter_mm`. |

## Worked Example: V-201

Reference vessel for Phases 11-13:

- Tag: `V-201`
- Internal diameter: `2000 mm`
- Tangent-to-tangent length: `4500 mm`
- Head type: `ELLIPSOIDAL_2_1`
- Wall thickness: `10 mm`
- Orientation: `HORIZONTAL`
- Saddles: omitted in input, therefore defaults populate at `900 mm` and `3600 mm`

Nozzles:

| Tag | Service | Size | Position | Axial Position | Radial Angle | Projection |
| --- | --- | --- | --- | --- | --- | --- |
| `N1` | Process inlet | `6 in` | `TOP` | `1500 mm` | `0 deg` | `150 mm` |
| `N2` | Process outlet | `8 in` | `BOTTOM` | `3000 mm` | `0 deg` | `150 mm` |
| `N3` | Level instrument | `2 in` | `SIDE_FRONT` | `2250 mm` | `0 deg` | `150 mm` |
| `N4` | Relief valve | `3 in` | `TOP` | `500 mm` | `0 deg` | `150 mm` |

## Units Reminder

- All lengths are in millimeters.
- Nozzle nominal sizes are in inches NPS.
- Angles are in degrees.

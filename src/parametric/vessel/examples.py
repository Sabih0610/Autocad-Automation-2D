"""
Canonical vessel examples for parametric generation.

Phase 12:
- V201 reference vessel

Phase 18:
- Additional vessels for batch rendering and edge-case validation:
  - V202_SMALL
  - V203_LONG
  - V204_END_NOZZLES
  - V205_CLUSTERED
"""

from __future__ import annotations

from src.parametric.vessel.parameters import (
    HeadType,
    Nozzle,
    NozzlePosition,
    Orientation,
    VesselParameters,
)


V201 = VesselParameters(
    tag="V-201",
    internal_diameter_mm=2000.0,
    tangent_to_tangent_mm=4500.0,
    head_type=HeadType.ELLIPSOIDAL_2_1,
    wall_thickness_mm=10.0,
    orientation=Orientation.HORIZONTAL,
    nozzles=[
        Nozzle(
            tag="N1",
            nominal_size_inches=6.0,
            position=NozzlePosition.TOP,
            axial_position_mm=1500.0,
        ),
        Nozzle(
            tag="N2",
            nominal_size_inches=8.0,
            position=NozzlePosition.BOTTOM,
            axial_position_mm=3000.0,
        ),
        Nozzle(
            tag="N3",
            nominal_size_inches=2.0,
            position=NozzlePosition.SIDE_FRONT,
            axial_position_mm=2250.0,
            radial_angle_degrees=0.0,
        ),
        Nozzle(
            tag="N4",
            nominal_size_inches=3.0,
            position=NozzlePosition.TOP,
            axial_position_mm=500.0,
        ),
    ],
    saddles=[],
)


V202_SMALL = VesselParameters(
    tag="V202_SMALL",
    internal_diameter_mm=500.0,
    tangent_to_tangent_mm=1500.0,
    head_type=HeadType.ELLIPSOIDAL_2_1,
    wall_thickness_mm=6.0,
    orientation=Orientation.HORIZONTAL,
    nozzles=[
        Nozzle(
            tag="N1",
            nominal_size_inches=2.0,
            position=NozzlePosition.TOP,
            axial_position_mm=500.0,
        ),
        Nozzle(
            tag="N2",
            nominal_size_inches=2.0,
            position=NozzlePosition.BOTTOM,
            axial_position_mm=1000.0,
        ),
    ],
    saddles=[],
)


V203_LONG = VesselParameters(
    tag="V203_LONG",
    internal_diameter_mm=1500.0,
    tangent_to_tangent_mm=8000.0,
    head_type=HeadType.ELLIPSOIDAL_2_1,
    wall_thickness_mm=12.0,
    orientation=Orientation.HORIZONTAL,
    nozzles=[
        Nozzle(
            tag="N1",
            nominal_size_inches=6.0,
            position=NozzlePosition.TOP,
            axial_position_mm=800.0,
        ),
        Nozzle(
            tag="N2",
            nominal_size_inches=8.0,
            position=NozzlePosition.BOTTOM,
            axial_position_mm=2000.0,
        ),
        Nozzle(
            tag="N3",
            nominal_size_inches=4.0,
            position=NozzlePosition.TOP,
            axial_position_mm=3200.0,
        ),
        Nozzle(
            tag="N4",
            nominal_size_inches=3.0,
            position=NozzlePosition.BOTTOM,
            axial_position_mm=5000.0,
        ),
        Nozzle(
            tag="N5",
            nominal_size_inches=2.0,
            position=NozzlePosition.SIDE_FRONT,
            axial_position_mm=1500.0,
            radial_angle_degrees=0.0,
        ),
        Nozzle(
            tag="N6",
            nominal_size_inches=2.0,
            position=NozzlePosition.SIDE_BACK,
            axial_position_mm=6200.0,
            radial_angle_degrees=180.0,
        ),
        Nozzle(
            tag="N7",
            nominal_size_inches=3.0,
            position=NozzlePosition.TOP,
            axial_position_mm=7100.0,
        ),
        Nozzle(
            tag="N8",
            nominal_size_inches=4.0,
            position=NozzlePosition.BOTTOM,
            axial_position_mm=7600.0,
        ),
    ],
    saddles=[],
)


V204_END_NOZZLES = VesselParameters(
    tag="V204_END_NOZZLES",
    internal_diameter_mm=1200.0,
    tangent_to_tangent_mm=3500.0,
    head_type=HeadType.ELLIPSOIDAL_2_1,
    wall_thickness_mm=10.0,
    orientation=Orientation.HORIZONTAL,
    nozzles=[
        Nozzle(
            tag="N1",
            nominal_size_inches=4.0,
            position=NozzlePosition.LEFT_END,
            axial_position_mm=0.0,
        ),
        Nozzle(
            tag="N2",
            nominal_size_inches=4.0,
            position=NozzlePosition.RIGHT_END,
            axial_position_mm=3500.0,
        ),
    ],
    saddles=[],
)


V205_CLUSTERED = VesselParameters(
    tag="V205_CLUSTERED",
    internal_diameter_mm=1800.0,
    tangent_to_tangent_mm=4200.0,
    head_type=HeadType.ELLIPSOIDAL_2_1,
    wall_thickness_mm=10.0,
    orientation=Orientation.HORIZONTAL,
    nozzles=[
        Nozzle(
            tag="N1",
            nominal_size_inches=3.0,
            position=NozzlePosition.TOP,
            axial_position_mm=1600.0,
        ),
        Nozzle(
            tag="N2",
            nominal_size_inches=3.0,
            position=NozzlePosition.TOP,
            axial_position_mm=1800.0,
        ),
        Nozzle(
            tag="N3",
            nominal_size_inches=4.0,
            position=NozzlePosition.TOP,
            axial_position_mm=2000.0,
        ),
        Nozzle(
            tag="N4",
            nominal_size_inches=2.0,
            position=NozzlePosition.BOTTOM,
            axial_position_mm=1900.0,
        ),
        Nozzle(
            tag="N5",
            nominal_size_inches=2.0,
            position=NozzlePosition.SIDE_FRONT,
            axial_position_mm=1950.0,
            radial_angle_degrees=0.0,
        ),
    ],
    saddles=[],
)


def get_all_examples() -> dict[str, VesselParameters]:
    """Return all vessel examples for tests and batch rendering."""
    return {
        "V201": V201,
        "V202_SMALL": V202_SMALL,
        "V203_LONG": V203_LONG,
        "V204_END_NOZZLES": V204_END_NOZZLES,
        "V205_CLUSTERED": V205_CLUSTERED,
    }
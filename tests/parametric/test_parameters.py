from __future__ import annotations

import copy

from src.parametric.vessel.examples import V201, get_all_examples
from src.parametric.vessel.parameters import (
    HeadType,
    Nozzle,
    NozzlePosition,
    Orientation,
    Saddle,
    VesselParameters,
    default_projection_mm,
    validate_parameters,
)


def make_v201() -> VesselParameters:
    return copy.deepcopy(V201)


def test_validate_accepts_v201_reference_vessel() -> None:
    params = make_v201()
    assert validate_parameters(params) == []


def test_validate_populates_default_saddles_when_missing() -> None:
    params = make_v201()
    params.saddles = []
    errors = validate_parameters(params)
    assert errors == []
    assert len(params.saddles) == 2
    assert params.saddles[0].axial_position_mm == 900.0
    assert params.saddles[1].axial_position_mm == 3600.0


def test_validate_rejects_missing_tag() -> None:
    params = make_v201()
    params.tag = "   "
    assert "Vessel tag must be a non-empty string." in validate_parameters(params)


def test_validate_rejects_negative_diameter() -> None:
    params = make_v201()
    params.internal_diameter_mm = -1.0
    assert "Internal diameter must be at least 100 mm." in validate_parameters(params)


def test_validate_rejects_tangent_length_below_minimum() -> None:
    params = make_v201()
    params.tangent_to_tangent_mm = 150.0
    assert "Tangent-to-tangent length must be at least 200 mm." in validate_parameters(params)


def test_validate_rejects_wall_thickness_that_is_too_large() -> None:
    params = make_v201()
    params.wall_thickness_mm = 600.0
    assert "Wall thickness must be less than one quarter of the internal diameter." in validate_parameters(params)


def test_validate_rejects_duplicate_nozzle_tags() -> None:
    params = make_v201()
    params.nozzles[1].tag = "N1"
    assert "Duplicate nozzle tag: N1." in validate_parameters(params)


def test_validate_rejects_duplicate_nozzle_locations() -> None:
    params = make_v201()
    params.nozzles.append(
        Nozzle(
            tag="N5",
            nominal_size_inches=4.0,
            position=NozzlePosition.TOP,
            axial_position_mm=1500.0,
        )
    )
    errors = validate_parameters(params)
    assert any("duplicates another nozzle location" in error for error in errors)


def test_validate_rejects_nozzle_with_nominal_size_below_zero() -> None:
    params = make_v201()
    params.nozzles[0].nominal_size_inches = 0.0
    errors = validate_parameters(params)
    assert "Nozzle N1 must have nominal size > 0." in errors


def test_validate_rejects_nozzle_axial_position_beyond_tangent_length() -> None:
    params = make_v201()
    params.nozzles[0].axial_position_mm = 5000.0
    errors = validate_parameters(params)
    assert any("axial position must be between 0 and the tangent-to-tangent length" in error for error in errors)


def test_validate_rejects_radial_angle_out_of_range() -> None:
    params = make_v201()
    params.nozzles[2].radial_angle_degrees = 361.0
    errors = validate_parameters(params)
    assert any("radial angle must be between 0 and 360 degrees" in error for error in errors)


def test_validate_rejects_saddle_overlap() -> None:
    params = make_v201()
    params.saddles = [
        Saddle(axial_position_mm=1000.0, width_mm=400.0, height_mm=1000.0),
        Saddle(axial_position_mm=1100.0, width_mm=400.0, height_mm=1000.0),
    ]
    assert "Saddles must not overlap." in validate_parameters(params)


def test_validate_rejects_saddle_out_of_range() -> None:
    params = make_v201()
    params.saddles = [Saddle(axial_position_mm=-1.0)]
    assert "Each saddle axial position must be between 0 and the tangent-to-tangent length." in validate_parameters(params)


def test_default_projection_mm_returns_expected_bands() -> None:
    assert default_projection_mm(2.0) == 150.0
    assert default_projection_mm(6.0) == 200.0
    assert default_projection_mm(10.0) == 250.0


def test_enums_round_trip_through_dataclass() -> None:
    nozzle = Nozzle(
        tag="NT",
        nominal_size_inches=2.0,
        position=NozzlePosition.SIDE_BACK,
        axial_position_mm=1000.0,
    )
    params = VesselParameters(
        tag="V-TEST",
        internal_diameter_mm=1000.0,
        tangent_to_tangent_mm=2000.0,
        head_type=HeadType.ELLIPSOIDAL_2_1,
        orientation=Orientation.HORIZONTAL,
        nozzles=[nozzle],
    )
    assert params.head_type.value == "ELLIPSOIDAL_2_1"
    assert params.orientation.value == "HORIZONTAL"
    assert params.nozzles[0].position.value == "SIDE_BACK"


def test_get_all_examples_returns_v201() -> None:
    examples = get_all_examples()
    assert "V201" in examples
    assert examples["V201"].tag == "V-201"

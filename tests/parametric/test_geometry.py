from __future__ import annotations

import copy

import pytest
from fluids import piping

from src.parametric.vessel.examples import V201
from src.parametric.vessel.geometry import (
    compute_centerlines,
    compute_head_arc,
    compute_head_depth,
    compute_nozzle_geometry,
    compute_saddle_geometry,
    compute_shell_outline,
)
from src.parametric.vessel.parameters import Nozzle, NozzlePosition, VesselParameters, validate_parameters


def make_v201() -> VesselParameters:
    params = copy.deepcopy(V201)
    assert validate_parameters(params) == []
    return params


def test_compute_shell_outline_returns_expected_tangent_length() -> None:
    outline = compute_shell_outline(make_v201())
    assert outline["right_tangent_x"] == pytest.approx(4500.0, abs=0.01)


def test_compute_shell_outline_returns_expected_outer_radius() -> None:
    outline = compute_shell_outline(make_v201())
    assert outline["shell_outer_radius_mm"] == pytest.approx(1010.0, abs=0.01)


def test_compute_shell_outline_returns_expected_inner_radius() -> None:
    outline = compute_shell_outline(make_v201())
    assert outline["shell_inner_radius_mm"] == pytest.approx(1000.0, abs=0.01)


def test_compute_shell_outline_top_line_uses_outer_radius() -> None:
    outline = compute_shell_outline(make_v201())
    assert outline["top_line"] == ((0.0, 1010.0), (4500.0, 1010.0))


def test_compute_head_arc_left_returns_expected_minor_axis() -> None:
    arc = compute_head_arc(make_v201(), "left")
    assert arc["minor_axis_mm"] == pytest.approx(505.0, abs=0.01)


def test_compute_head_arc_left_uses_left_tangent_center() -> None:
    arc = compute_head_arc(make_v201(), "left")
    assert arc["center"] == (0.0, 0.0)
    assert arc["extends_negative_x"] is True


def test_compute_head_arc_right_uses_right_tangent_center() -> None:
    arc = compute_head_arc(make_v201(), "right")
    assert arc["center"] == (4500.0, 0.0)
    assert arc["extends_negative_x"] is False


def test_overall_length_uses_drawn_outer_head_depth() -> None:
    params = make_v201()
    overall_length_mm = params.tangent_to_tangent_mm + (2.0 * compute_head_depth(params))
    assert overall_length_mm == pytest.approx(5510.0, abs=0.01)


def test_compute_nozzle_geometry_for_top_nozzle_returns_expected_insertion_and_direction() -> None:
    nozzle_geometry = compute_nozzle_geometry(make_v201(), make_v201().nozzles[0])
    assert nozzle_geometry["insertion_point"] == pytest.approx((1500.0, 1010.0, 0.0), abs=0.01)
    assert nozzle_geometry["centerline_direction"] == pytest.approx((0.0, 1.0, 0.0), abs=0.01)


def test_compute_nozzle_geometry_for_bottom_nozzle_returns_expected_insertion_and_direction() -> None:
    nozzle_geometry = compute_nozzle_geometry(make_v201(), make_v201().nozzles[1])
    assert nozzle_geometry["insertion_point"] == pytest.approx((3000.0, -1010.0, 0.0), abs=0.01)
    assert nozzle_geometry["centerline_direction"] == pytest.approx((0.0, -1.0, 0.0), abs=0.01)


def test_compute_nozzle_geometry_for_side_front_default_points_toward_viewer() -> None:
    nozzle_geometry = compute_nozzle_geometry(make_v201(), make_v201().nozzles[2])
    assert nozzle_geometry["insertion_point"] == pytest.approx((2250.0, 0.0, 1010.0), abs=0.01)
    assert nozzle_geometry["centerline_direction"] == pytest.approx((0.0, 0.0, 1.0), abs=0.01)


def test_compute_nozzle_geometry_for_side_front_uses_projection() -> None:
    nozzle_geometry = compute_nozzle_geometry(make_v201(), make_v201().nozzles[2])
    assert nozzle_geometry["tip_point"] == pytest.approx((2250.0, 0.0, 1160.0), abs=0.01)


def test_compute_nozzle_geometry_for_side_back_default_points_away_from_viewer() -> None:
    params = make_v201()
    nozzle = Nozzle(
        tag="NB",
        nominal_size_inches=2.0,
        position=NozzlePosition.SIDE_BACK,
        axial_position_mm=2000.0,
    )
    nozzle_geometry = compute_nozzle_geometry(params, nozzle)
    assert nozzle_geometry["insertion_point"] == pytest.approx((2000.0, 0.0, -1010.0), abs=0.01)
    assert nozzle_geometry["centerline_direction"] == pytest.approx((0.0, 0.0, -1.0), abs=0.01)


def test_compute_nozzle_geometry_for_side_front_90_deg_rotates_to_top() -> None:
    params = make_v201()
    nozzle = Nozzle(
        tag="NF90",
        nominal_size_inches=2.0,
        position=NozzlePosition.SIDE_FRONT,
        axial_position_mm=2000.0,
        radial_angle_degrees=90.0,
    )
    nozzle_geometry = compute_nozzle_geometry(params, nozzle)
    assert nozzle_geometry["insertion_point"][1] == pytest.approx(1010.0, abs=0.01)
    assert nozzle_geometry["insertion_point"][2] == pytest.approx(0.0, abs=0.01)


def test_compute_nozzle_geometry_for_side_back_90_deg_rotates_to_bottom() -> None:
    params = make_v201()
    nozzle = Nozzle(
        tag="NB90",
        nominal_size_inches=2.0,
        position=NozzlePosition.SIDE_BACK,
        axial_position_mm=2000.0,
        radial_angle_degrees=90.0,
    )
    nozzle_geometry = compute_nozzle_geometry(params, nozzle)
    assert nozzle_geometry["insertion_point"][1] == pytest.approx(-1010.0, abs=0.01)
    assert nozzle_geometry["insertion_point"][2] == pytest.approx(0.0, abs=0.01)


def test_compute_nozzle_geometry_for_left_end_uses_head_depth() -> None:
    params = make_v201()
    nozzle = Nozzle(
        tag="NL",
        nominal_size_inches=2.0,
        position=NozzlePosition.LEFT_END,
        axial_position_mm=1000.0,
    )
    nozzle_geometry = compute_nozzle_geometry(params, nozzle)
    assert nozzle_geometry["insertion_point"] == pytest.approx((-505.0, 0.0, 0.0), abs=0.01)
    assert nozzle_geometry["centerline_direction"] == pytest.approx((-1.0, 0.0, 0.0), abs=0.01)


def test_compute_nozzle_geometry_for_right_end_uses_head_depth() -> None:
    params = make_v201()
    nozzle = Nozzle(
        tag="NR",
        nominal_size_inches=2.0,
        position=NozzlePosition.RIGHT_END,
        axial_position_mm=1000.0,
    )
    nozzle_geometry = compute_nozzle_geometry(params, nozzle)
    assert nozzle_geometry["insertion_point"] == pytest.approx((5005.0, 0.0, 0.0), abs=0.01)
    assert nozzle_geometry["centerline_direction"] == pytest.approx((1.0, 0.0, 0.0), abs=0.01)


def test_compute_nozzle_geometry_uses_fluids_schedule_40_dimensions() -> None:
    params = make_v201()
    nozzle_geometry = compute_nozzle_geometry(params, params.nozzles[0])
    _, pipe_id_m, pipe_od_m, pipe_wall_m = piping.nearest_pipe(NPS=6.0, schedule="40")
    assert nozzle_geometry["pipe_od_mm"] == pytest.approx(pipe_od_m * 1000.0, abs=0.01)
    assert nozzle_geometry["pipe_id_mm"] == pytest.approx(pipe_id_m * 1000.0, abs=0.01)
    assert nozzle_geometry["wall_thickness_mm"] == pytest.approx(pipe_wall_m * 1000.0, abs=0.01)


def test_compute_nozzle_geometry_uses_expected_flange_od_reference() -> None:
    params = make_v201()
    nozzle_geometry = compute_nozzle_geometry(params, params.nozzles[0])
    assert nozzle_geometry["flange_od_mm"] == pytest.approx(280.0, abs=0.01)


def test_compute_nozzle_geometry_rejects_unsupported_flange_size() -> None:
    params = make_v201()
    nozzle = Nozzle(
        tag="N5",
        nominal_size_inches=5.0,
        position=NozzlePosition.TOP,
        axial_position_mm=1000.0,
    )
    with pytest.raises(ValueError, match="No ANSI B16.5 Class 150 RF flange OD reference"):
        compute_nozzle_geometry(params, nozzle)


def test_default_saddles_land_at_point_two_and_point_eight_tangent_length() -> None:
    params = make_v201()
    assert params.saddles[0].axial_position_mm == pytest.approx(900.0, abs=0.01)
    assert params.saddles[1].axial_position_mm == pytest.approx(3600.0, abs=0.01)


def test_compute_saddle_geometry_returns_expected_base_level() -> None:
    params = make_v201()
    saddle_geometry = compute_saddle_geometry(params, params.saddles[0])
    assert saddle_geometry["base_y"] == pytest.approx(-2010.0, abs=0.01)


def test_compute_saddle_geometry_returns_expected_point_count() -> None:
    params = make_v201()
    saddle_geometry = compute_saddle_geometry(params, params.saddles[0])
    assert len(saddle_geometry["outline_points"]) == 15
    assert saddle_geometry["contact_angle_degrees"] == pytest.approx(120.0, abs=0.01)


def test_compute_centerlines_returns_expected_main_horizontal_line() -> None:
    centerlines = compute_centerlines(make_v201())
    assert centerlines["main_horizontal"] == ((-605.0, 0.0), (5105.0, 0.0))


def test_compute_centerlines_returns_extended_top_nozzle_line() -> None:
    params = make_v201()
    centerlines = compute_centerlines(params)
    n1_line = next(item["line"] for item in centerlines["nozzle_centerlines"] if item["nozzle_tag"] == "N1")
    assert n1_line[0] == (1500.0, 0.0)
    assert n1_line[1][1] == pytest.approx(1185.0, abs=0.01)


def test_compute_centerlines_projects_side_front_default_to_axis_point_in_side_view() -> None:
    params = make_v201()
    centerlines = compute_centerlines(params)
    n3_line = next(item["line"] for item in centerlines["nozzle_centerlines"] if item["nozzle_tag"] == "N3")
    assert n3_line[0] == (2250.0, 0.0)
    assert n3_line[1] == pytest.approx((2250.0, 0.0), abs=0.01)

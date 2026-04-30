"""
Phase 15 view consistency tests.

These tests verify that the front, top, and side views are based on the
same vessel geometry.

Important:
- These tests do NOT inspect pixels or screenshots.
- They verify the shared geometry numbers that the views use.
- Drawing/visual quality is still manually checked in AutoCAD.
"""

from __future__ import annotations

import pytest

from src.parametric.vessel.examples import V201
from src.parametric.vessel.geometry import (
    compute_head_arc,
    compute_nozzle_geometry,
    compute_shell_outline,
)
from src.parametric.vessel.parameters import NozzlePosition, validate_parameters


def test_v201_validates_cleanly():
    """The canonical V-201 example should be valid before view rendering."""
    assert validate_parameters(V201) == []


def test_front_and_top_share_same_tangent_length():
    """
    Front and top views both use the same tangent-to-tangent length.

    For V-201 this is 4500 mm.
    """
    shell = compute_shell_outline(V201)

    assert shell["left_tangent_x"] == pytest.approx(0.0, abs=0.01)
    assert shell["right_tangent_x"] == pytest.approx(4500.0, abs=0.01)
    assert V201.tangent_to_tangent_mm == pytest.approx(4500.0, abs=0.01)


def test_front_top_and_side_share_same_outer_radius():
    """
    All three views must use the same shell outer radius.

    V-201:
    ID = 2000 mm
    wall = 10 mm
    outer radius = 1000 + 10 = 1010 mm
    """
    shell = compute_shell_outline(V201)

    assert shell["shell_outer_radius_mm"] == pytest.approx(1010.0, abs=0.01)

    left_head = compute_head_arc(V201, "left")
    right_head = compute_head_arc(V201, "right")

    assert left_head["major_axis_mm"] == pytest.approx(1010.0, abs=0.01)
    assert right_head["major_axis_mm"] == pytest.approx(1010.0, abs=0.01)


def test_head_depth_is_consistent_for_left_and_right_heads():
    """
    Both heads must use the same outer head depth.

    V-201 outer head depth:
    shell outer radius / 2 = 1010 / 2 = 505 mm
    """
    left_head = compute_head_arc(V201, "left")
    right_head = compute_head_arc(V201, "right")

    assert left_head["minor_axis_mm"] == pytest.approx(505.0, abs=0.01)
    assert right_head["minor_axis_mm"] == pytest.approx(505.0, abs=0.01)


def test_overall_length_used_by_views_is_consistent():
    """
    Overall vessel length for view layout is tangent length plus two head depths.

    The design convention uses internal head depth:
    ID / 4 = 2000 / 4 = 500 mm per side

    Overall length:
    4500 + 500 + 500 = 5500 mm
    """
    internal_head_depth = V201.internal_diameter_mm / 4.0
    overall_length = V201.tangent_to_tangent_mm + (2.0 * internal_head_depth)

    assert internal_head_depth == pytest.approx(500.0, abs=0.01)
    assert overall_length == pytest.approx(5500.0, abs=0.01)


def test_top_nozzles_keep_same_axial_positions_across_views():
    """
    Top nozzles should keep their X/axial positions in front and top views.

    V-201 has:
    N1 top nozzle at x=1500
    N4 relief valve at x=500
    """
    top_nozzles = [n for n in V201.nozzles if n.position == NozzlePosition.TOP]
    by_tag = {n.tag: n for n in top_nozzles}

    n1_geom = compute_nozzle_geometry(V201, by_tag["N1"])
    n4_geom = compute_nozzle_geometry(V201, by_tag["N4"])

    assert n1_geom["insertion_point"][0] == pytest.approx(1500.0, abs=0.01)
    assert n4_geom["insertion_point"][0] == pytest.approx(500.0, abs=0.01)


def test_bottom_nozzle_keeps_same_axial_position_across_views():
    """
    Bottom nozzle should keep its X/axial position in front view.

    V-201 has N2 bottom outlet at x=3000.
    """
    bottom_nozzles = [n for n in V201.nozzles if n.position == NozzlePosition.BOTTOM]
    assert len(bottom_nozzles) == 1

    n2_geom = compute_nozzle_geometry(V201, bottom_nozzles[0])

    assert n2_geom["insertion_point"][0] == pytest.approx(3000.0, abs=0.01)
    assert n2_geom["insertion_point"][1] == pytest.approx(-1010.0, abs=0.01)


def test_side_front_nozzle_position_is_consistent():
    """
    SIDE_FRONT nozzle should keep its axial position.

    V-201 has N3 level instrument at x=2250.
    """
    side_nozzles = [n for n in V201.nozzles if n.position == NozzlePosition.SIDE_FRONT]
    assert len(side_nozzles) == 1

    n3_geom = compute_nozzle_geometry(V201, side_nozzles[0])

    assert n3_geom["insertion_point"][0] == pytest.approx(2250.0, abs=0.01)


def test_saddles_default_to_20_and_80_percent_of_tangent_length():
    """
    Default saddles should be placed at 0.2L and 0.8L.

    V-201 tangent length = 4500 mm
    0.2L = 900 mm
    0.8L = 3600 mm
    """
    # validate_parameters populates default saddles when missing.
    assert validate_parameters(V201) == []

    assert len(V201.saddles) == 2
    assert V201.saddles[0].axial_position_mm == pytest.approx(900.0, abs=0.01)
    assert V201.saddles[1].axial_position_mm == pytest.approx(3600.0, abs=0.01)


def test_side_view_diameter_matches_front_view_height():
    """
    Side view circle diameter should match front view shell outside height.

    shell OR = 1010 mm
    OD height = 2020 mm
    """
    shell = compute_shell_outline(V201)

    side_view_diameter = shell["shell_outer_radius_mm"] * 2.0
    front_view_height = 1010.0 * 2.0

    assert side_view_diameter == pytest.approx(front_view_height, abs=0.01)
    assert side_view_diameter == pytest.approx(2020.0, abs=0.01)
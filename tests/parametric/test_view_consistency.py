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

from src.parametric.vessel import draw_dimensions
from src.parametric.vessel.examples import V201, get_all_examples
from src.parametric.vessel.geometry import (
    compute_head_arc,
    compute_nozzle_geometry,
    compute_shell_outline,
)
from src.parametric.vessel.parameters import Nozzle, NozzlePosition, validate_parameters


ALL_EXAMPLES = list(get_all_examples().items())


class _RecordedDimension:
    def render(self) -> None:
        pass


class _DimensionRecorder:
    def __init__(self) -> None:
        self.linear_dimensions: list[dict] = []

    def add_linear_dim(self, **kwargs):
        self.linear_dimensions.append(kwargs)
        return _RecordedDimension()


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


@pytest.mark.parametrize(
    ("example_name", "params"),
    ALL_EXAMPLES,
    ids=[name for name, _params in ALL_EXAMPLES],
)
def test_overall_length_used_by_views_is_consistent(
    example_name,
    params,
    monkeypatch,
):
    """The rendered overall dimension must span the drawn outer head tips."""
    recorder = _DimensionRecorder()
    monkeypatch.setattr(draw_dimensions, "_add_text", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        draw_dimensions,
        "draw_front_view_nozzle_position_dimensions",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        draw_dimensions,
        "draw_front_view_saddle_dimensions",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        draw_dimensions,
        "draw_front_view_nozzle_callouts",
        lambda **_kwargs: None,
    )

    draw_dimensions.draw_front_view_basic_dimensions(recorder, params)

    overall_dimension = recorder.linear_dimensions[1]
    dimensioned_length = (
        overall_dimension["p2"][0] - overall_dimension["p1"][0]
    )
    left_head = compute_head_arc(params, "left")
    right_head = compute_head_arc(params, "right")
    drawn_left_x = left_head["center"][0] - left_head["minor_axis_mm"]
    drawn_right_x = right_head["center"][0] + right_head["minor_axis_mm"]
    drawn_length = drawn_right_x - drawn_left_x

    assert dimensioned_length == pytest.approx(drawn_length, abs=0.01), example_name


@pytest.mark.parametrize(
    ("example_name", "params"),
    ALL_EXAMPLES,
    ids=[name for name, _params in ALL_EXAMPLES],
)
@pytest.mark.parametrize(
    ("position", "side", "direction"),
    [
        (NozzlePosition.LEFT_END, "left", -1.0),
        (NozzlePosition.RIGHT_END, "right", 1.0),
    ],
)
def test_head_nozzle_positions_sit_on_drawn_head_outline(
    example_name,
    params,
    position,
    side,
    direction,
):
    nozzle = Nozzle(
        tag=f"{example_name}_{side}",
        nominal_size_inches=2.0,
        position=position,
        axial_position_mm=0.0,
    )

    nozzle_geometry = compute_nozzle_geometry(params, nozzle)
    head = compute_head_arc(params, side)
    head_tip_x = head["center"][0] + (direction * head["minor_axis_mm"])

    assert nozzle_geometry["insertion_point"] == pytest.approx(
        (head_tip_x, 0.0, 0.0),
        abs=0.01,
    )


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

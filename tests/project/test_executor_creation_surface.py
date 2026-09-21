"""Every entity-creation branch of `executor.py`, run against a COM-shaped fake.

Before `fake_cad.ModelSpace` grew a real `Add*` surface it was a plain Python
list, so `executor.py`'s creation branches (its LINE/CIRCLE/ARC/ELLIPSE/
POLYLINE/TEXT/DIM_LINEAR handlers, lines ~204-354) could never execute under
test at all. Everything asserting "AutoCAD was written correctly" was
unverified. These tests run the real executor end to end and check the DXF it
actually produces.
"""
import math

import ezdxf
import pytest

from src.framework.commands import executor
from tests.project.fake_cad import Acad, Document


COMMANDS = [
    {"command": "LAYER", "layer_name": "PIPES", "color": 1},
    {"command": "LINE", "from": [0, 0], "to": [100, 0], "layer": "PIPES"},
    {"command": "CIRCLE", "center": [50, 50], "radius": 10, "layer": "PIPES"},
    {
        "command": "ARC",
        "center": [0, 0],
        "radius": 20,
        "start_angle_degrees": 0,
        "end_angle_degrees": 90,
        "layer": "PIPES",
    },
    {
        "command": "ELLIPSE",
        "center": [1000, 500],
        "major_axis_endpoint": [1100, 500],
        "ratio": 0.5,
        "layer": "PIPES",
    },
    {"command": "POLYLINE", "points": [[0, 0], [10, 0], [10, 10]], "closed": True, "layer": "PIPES"},
    {"command": "TEXT", "text": "P-101", "position": [5, 5], "height": 2.5, "layer": "PIPES"},
    {
        "command": "DIM_LINEAR",
        "from": [0, 0],
        "to": [100, 0],
        "dim_line_position": [50, -20],
        "layer": "PIPES",
    },
]


@pytest.fixture
def executed(tmp_path, monkeypatch):
    path = tmp_path / "creation.dxf"
    doc = ezdxf.new()
    doc.units = 4
    doc.saveas(path)

    fake_doc = Document(path)
    monkeypatch.setattr(executor, "_get_acad", lambda: Acad([fake_doc]))
    monkeypatch.setattr(executor, "_active_document", lambda acad: fake_doc)

    result = executor.execute_commands(COMMANDS, save=False, zoom_extents=False)
    return result, fake_doc.data.modelspace()


def _one(msp, dxftype):
    matches = [entity for entity in msp if entity.dxftype() == dxftype]
    assert len(matches) == 1, f"expected exactly one {dxftype}, got {len(matches)}"
    return matches[0]


def test_every_command_type_executes_and_creates_its_entity(executed):
    result, msp = executed

    assert result["errors"] == []
    assert result["ok"] is True
    assert result["executed_count"] == len(COMMANDS)

    produced = sorted(entity.dxftype() for entity in msp)
    assert produced == sorted(["LINE", "CIRCLE", "ARC", "ELLIPSE", "LWPOLYLINE", "TEXT", "DIMENSION"])


def test_arc_angles_are_converted_from_radians_to_degrees(executed):
    """AutoCAD COM `AddArc` takes radians; DXF stores degrees. A fake that
    forwarded them unchanged would store a 0-1.57 degree sliver and any test
    asserting on it would lock that in."""
    _, msp = executed
    arc = _one(msp, "ARC")

    assert arc.dxf.start_angle == pytest.approx(0.0)
    assert arc.dxf.end_angle == pytest.approx(90.0)


def test_ellipse_major_axis_is_relative_to_its_centre(executed):
    """COM `AddEllipse(Center, MajorAxis, Ratio)` takes MajorAxis as a vector
    RELATIVE to the centre. Passing the absolute endpoint drew a ~2236-unit
    axis rotated 26 degrees where a 200-unit horizontal one was intended, and
    the preview renderer disagreed with the executor as a result."""
    _, msp = executed
    ellipse = _one(msp, "ELLIPSE")

    assert tuple(ellipse.dxf.center)[:2] == pytest.approx((1000.0, 500.0))
    # endpoint [1100,500] - centre [1000,500] == a 100-unit vector along +X
    assert tuple(ellipse.dxf.major_axis)[:2] == pytest.approx((100.0, 0.0))
    assert ellipse.dxf.ratio == pytest.approx(0.5)


def test_polyline_geometry_and_closed_flag_round_trip(executed):
    _, msp = executed
    polyline = _one(msp, "LWPOLYLINE")

    points = [(round(p[0], 6), round(p[1], 6)) for p in polyline.get_points("xy")]
    assert points == [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
    assert polyline.closed is True


def test_line_and_circle_geometry_is_exact(executed):
    _, msp = executed

    line = _one(msp, "LINE")
    assert tuple(line.dxf.start)[:2] == pytest.approx((0.0, 0.0))
    assert tuple(line.dxf.end)[:2] == pytest.approx((100.0, 0.0))

    circle = _one(msp, "CIRCLE")
    assert tuple(circle.dxf.center)[:2] == pytest.approx((50.0, 50.0))
    assert circle.dxf.radius == pytest.approx(10.0)


def test_text_content_position_and_height(executed):
    _, msp = executed
    text = _one(msp, "TEXT")

    assert text.dxf.text == "P-101"
    assert tuple(text.dxf.insert)[:2] == pytest.approx((5.0, 5.0))
    assert text.dxf.height == pytest.approx(2.5)


def test_every_entity_lands_on_the_requested_layer(executed):
    _, msp = executed

    drawn = [entity for entity in msp if entity.dxftype() != "DIMENSION"]
    assert drawn, "no entities were created"
    assert {entity.dxf.layer for entity in drawn} == {"PIPES"}


def test_real_variant_points_reach_the_fake_unstubbed(tmp_path, monkeypatch):
    """`src/cad/session.py`'s `point()` wraps coordinates in a
    `win32com.client.VARIANT`, which real AutoCAD requires and which is NOT
    iterable. The suite used to monkeypatch `point` to `tuple` everywhere,
    so that conversion was never exercised. Assert a genuine VARIANT survives
    the round trip."""
    pythoncom = pytest.importorskip("pythoncom")
    win32com_client = pytest.importorskip("win32com.client")

    from src.cad.session import point

    variant = point((1.0, 2.0, 3.0))
    assert isinstance(variant, win32com_client.VARIANT)
    with pytest.raises(TypeError):
        list(variant)  # a real VARIANT is not iterable; .value holds the data

    path = tmp_path / "variant.dxf"
    doc = ezdxf.new()
    doc.units = 4
    line = doc.modelspace().add_line((0, 0, 0), (10, 0, 0))
    handle = line.dxf.handle
    doc.saveas(path)

    fake_doc = Document(path)
    entity = fake_doc.HandleToObject(handle)
    entity.EndPoint = point((42.0, 7.0, 0.0))

    assert tuple(fake_doc.data.entitydb[handle].dxf.end) == pytest.approx((42.0, 7.0, 0.0))


def test_schema_valid_optional_properties_execute_in_fake(
    tmp_path,
    monkeypatch,
):
    from src.framework.commands.schema import (
        validate_command_sequence,
    )

    commands = [
        {
            "command": "TEXT",
            "text": "ROTATED",
            "position": [10, 20],
            "height": 5,
            "rotation_degrees": 90,
        },
        {
            "command": "ELLIPSE",
            "center": [100, 100],
            "major_axis_endpoint":
                [140, 100],
            "ratio": 0.5,
            "start_angle_degrees": 30,
            "end_angle_degrees": 150,
        },
        {
            "command": "DIM_LINEAR",
            "from": [0, 0],
            "to": [100, 0],
            "dim_line_position":
                [50, -20],
            "text_override":
                "100 TYP",
        },
    ]

    assert validate_command_sequence(
        {
            "schema_version": "1.0",
            "summary":
                "Exercise schema-valid "
                "optional command properties.",
            "assumptions": [],
            "commands": commands,
        }
    ) == []

    path = (
        tmp_path
        / "optional-properties.dxf"
    )

    doc = ezdxf.new("R2010")
    doc.units = 4
    doc.saveas(path)

    fake_doc = Document(path)

    monkeypatch.setattr(
        executor,
        "_get_acad",
        lambda: Acad([fake_doc]),
    )

    monkeypatch.setattr(
        executor,
        "_active_document",
        lambda acad: fake_doc,
    )

    result = executor.execute_commands(
        commands,
        save=False,
        zoom_extents=False,
    )

    assert result["ok"] is True
    assert result["errors"] == []

    msp = (
        fake_doc.data.modelspace()
    )

    text = next(
        iter(
            msp.query("TEXT")
        )
    )

    assert (
        text.dxf.rotation
        == pytest.approx(90.0)
    )

    ellipse = next(
        iter(
            msp.query("ELLIPSE")
        )
    )

    assert (
        ellipse.dxf.start_param
        == pytest.approx(
            math.radians(30.0)
        )
    )

    assert (
        ellipse.dxf.end_param
        == pytest.approx(
            math.radians(150.0)
        )
    )

    dimension = next(
        iter(
            msp.query("DIMENSION")
        )
    )

    assert (
        dimension.dxf.text
        == "100 TYP"
    )

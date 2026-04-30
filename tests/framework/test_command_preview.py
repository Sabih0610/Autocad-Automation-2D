from __future__ import annotations

import ezdxf
import pytest

from src.framework.commands.preview import (
    PreviewRenderError,
    render_preview,
    render_preview_sequence,
)


def _read_modelspace(path):
    doc = ezdxf.readfile(path)
    return doc, doc.modelspace()


def _valid_sequence() -> dict:
    return {
        "schema_version": "1.0",
        "summary": "Preview test",
        "estimated_drawing_type": "test",
        "assumptions": [],
        "commands": [
            {"command": "LAYER", "layer_name": "TEST", "color": 3},
            {"command": "LINE", "from": [0, 0], "to": [100, 0], "layer": "TEST"},
        ],
    }


def test_render_preview_rejects_empty_command_list(tmp_path) -> None:
    with pytest.raises(PreviewRenderError, match="commands must be a non-empty list"):
        render_preview([], str(tmp_path / "empty.dxf"))


def test_render_preview_sequence_rejects_invalid_command_sequence(tmp_path) -> None:
    sequence = _valid_sequence()
    sequence["commands"] = []

    with pytest.raises(PreviewRenderError, match="Invalid command sequence"):
        render_preview_sequence(sequence, str(tmp_path / "invalid.dxf"))


def test_line_command_creates_dxf_line_entity(tmp_path) -> None:
    output = tmp_path / "line.dxf"
    render_preview(
        [{"command": "LINE", "from": [0, 0], "to": [100, 0]}],
        str(output),
    )

    _doc, msp = _read_modelspace(output)

    assert len(list(msp.query("LINE"))) == 1


def test_circle_command_creates_dxf_circle_entity(tmp_path) -> None:
    output = tmp_path / "circle.dxf"
    render_preview(
        [{"command": "CIRCLE", "center": [0, 0], "radius": 50}],
        str(output),
    )

    _doc, msp = _read_modelspace(output)

    assert len(list(msp.query("CIRCLE"))) == 1


def test_text_command_creates_dxf_text_entity(tmp_path) -> None:
    output = tmp_path / "text.dxf"
    render_preview(
        [{"command": "TEXT", "text": "Hello", "position": [0, 0], "height": 25}],
        str(output),
    )

    _doc, msp = _read_modelspace(output)

    assert len(list(msp.query("TEXT"))) == 1


def test_polyline_command_creates_dxf_lwpolyline_entity(tmp_path) -> None:
    output = tmp_path / "polyline.dxf"
    render_preview(
        [
            {
                "command": "POLYLINE",
                "points": [[0, 0], [100, 0], [100, 50]],
                "closed": True,
            }
        ],
        str(output),
    )

    _doc, msp = _read_modelspace(output)

    assert len(list(msp.query("LWPOLYLINE"))) == 1


def test_arc_command_creates_dxf_arc_entity(tmp_path) -> None:
    output = tmp_path / "arc.dxf"
    render_preview(
        [
            {
                "command": "ARC",
                "center": [0, 0],
                "radius": 50,
                "start_angle_degrees": 0,
                "end_angle_degrees": 90,
            }
        ],
        str(output),
    )

    _doc, msp = _read_modelspace(output)

    assert len(list(msp.query("ARC"))) == 1


def test_ellipse_command_creates_dxf_ellipse_entity(tmp_path) -> None:
    output = tmp_path / "ellipse.dxf"
    render_preview(
        [
            {
                "command": "ELLIPSE",
                "center": [0, 0],
                "major_axis_endpoint": [100, 0],
                "ratio": 0.5,
            }
        ],
        str(output),
    )

    _doc, msp = _read_modelspace(output)

    assert len(list(msp.query("ELLIPSE"))) == 1


def test_layer_command_creates_requested_layer(tmp_path) -> None:
    output = tmp_path / "layer.dxf"
    render_preview(
        [{"command": "LAYER", "layer_name": "TEST", "color": 3}],
        str(output),
    )

    doc, _msp = _read_modelspace(output)

    assert "TEST" in doc.layers
    assert doc.layers.get("TEST").color == 3


def test_entity_layer_is_applied_correctly(tmp_path) -> None:
    output = tmp_path / "entity_layer.dxf"
    render_preview(
        [{"command": "LINE", "from": [0, 0], "to": [100, 0], "layer": "TEST"}],
        str(output),
    )

    _doc, msp = _read_modelspace(output)
    line = list(msp.query("LINE"))[0]

    assert line.dxf.layer == "TEST"


def test_insert_without_block_definition_renders_placeholder(tmp_path) -> None:
    output = tmp_path / "insert_placeholder.dxf"
    render_preview(
        [{"command": "INSERT", "block_name": "PUMP", "position": [0, 0], "layer": "EQUIPMENT"}],
        str(output),
    )

    _doc, msp = _read_modelspace(output)
    text_values = [entity.dxf.text for entity in msp.query("TEXT")]

    assert len(list(msp.query("CIRCLE"))) == 1
    assert "BLOCK: PUMP" in text_values


def test_dim_linear_renders_preview_geometry_and_text(tmp_path) -> None:
    output = tmp_path / "dim_linear.dxf"
    render_preview(
        [
            {
                "command": "DIM_LINEAR",
                "from": [0, 0],
                "to": [100, 0],
                "dim_line_position": [50, 20],
                "text_override": "100",
                "layer": "DIMENSION",
            }
        ],
        str(output),
    )

    _doc, msp = _read_modelspace(output)
    text_values = [entity.dxf.text for entity in msp.query("TEXT")]

    assert len(list(msp.query("LINE"))) >= 2
    assert "100" in text_values


def test_output_parent_directory_is_created_automatically(tmp_path) -> None:
    output = tmp_path / "nested" / "preview.dxf"

    result = render_preview(
        [{"command": "LINE", "from": [0, 0], "to": [100, 0]}],
        str(output),
    )

    assert result == str(output)
    assert output.is_file()


def test_render_preview_sequence_returns_output_path(tmp_path) -> None:
    output = tmp_path / "sequence.dxf"

    result = render_preview_sequence(_valid_sequence(), str(output))

    assert result == str(output)
    assert output.is_file()

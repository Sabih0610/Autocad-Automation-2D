from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.framework.pid.components.base import (
    BasePIDComponent,
    RenderedComponent,
    component_text_id,
    normalize_point,
    offset_point,
    render_component,
)


@dataclass
class FakeComponent(BasePIDComponent):
    def ports(self) -> dict[str, list[float]]:
        return {"out": [100.0, 0.0]}

    def render(self) -> list[dict]:
        return [
            {
                "command": "LINE",
                "from": [0, 0],
                "to": [100, 0],
                "layer": "PID_PIPING",
            }
        ]


def test_normalize_point_converts_2d_point() -> None:
    assert normalize_point([1, 2]) == [1.0, 2.0]


def test_normalize_point_converts_3d_point_and_ignores_z() -> None:
    assert normalize_point([1, 2, 3]) == [1.0, 2.0]


def test_normalize_point_rejects_invalid_point() -> None:
    with pytest.raises(ValueError, match="point must be"):
        normalize_point([1])


def test_offset_point_returns_shifted_point() -> None:
    assert offset_point([1, 2], dx=3, dy=4) == [4.0, 6.0]


def test_component_text_id_formats_id() -> None:
    assert component_text_id("V", 101) == "V-101"


def test_component_text_id_rejects_empty_prefix() -> None:
    with pytest.raises(ValueError, match="prefix must be"):
        component_text_id("", 1)


def test_component_text_id_rejects_index_less_than_one() -> None:
    with pytest.raises(ValueError, match="index must be"):
        component_text_id("P", 0)


def test_base_component_validates_non_empty_id() -> None:
    with pytest.raises(ValueError, match="component id must be"):
        BasePIDComponent(id="")


def test_base_component_normalizes_center() -> None:
    component = BasePIDComponent(id="BASE1", center=(1, 2, 3))

    assert component.center == [1.0, 2.0]


def test_base_component_render_raises_not_implemented() -> None:
    component = BasePIDComponent(id="BASE1")

    with pytest.raises(NotImplementedError):
        component.render()


def test_render_component_returns_rendered_component() -> None:
    component = FakeComponent(id="FC1", tag="FC-001")
    rendered = render_component(component)

    assert isinstance(rendered, RenderedComponent)
    assert rendered.component_id == "FC1"
    assert rendered.component_type == "FakeComponent"
    assert rendered.commands == component.render()
    assert rendered.ports == {"out": [100.0, 0.0]}
    assert "FC1" in rendered.summary

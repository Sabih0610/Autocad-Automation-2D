from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.framework.cad3d.components.base import (
    BaseCAD3DComponent,
    make_port3,
    normalize_point3,
    normalize_vector3,
    offset_point3,
    render_cad3d_component,
)


def test_normalize_point3_accepts_2d_point() -> None:
    assert normalize_point3([1, 2]) == [1.0, 2.0, 0.0]


def test_normalize_point3_accepts_3d_point() -> None:
    assert normalize_point3([1, 2, 3]) == [1.0, 2.0, 3.0]


def test_normalize_point3_invalid_point_raises() -> None:
    with pytest.raises(ValueError):
        normalize_point3([1])


def test_normalize_vector3_accepts_nonzero_vector() -> None:
    assert normalize_vector3([1, 0, 0]) == [1.0, 0.0, 0.0]


def test_normalize_vector3_zero_vector_raises() -> None:
    with pytest.raises(ValueError):
        normalize_vector3([0, 0, 0])


def test_offset_point3_returns_offset_point() -> None:
    assert offset_point3([1, 2, 3], dx=4, dy=5, dz=6) == [5.0, 7.0, 9.0]


def test_make_port3_returns_expected_shape() -> None:
    assert make_port3([1, 2, 3], [1, 0, 0], 100, "nozzle") == {
        "position": [1.0, 2.0, 3.0],
        "direction": [1.0, 0.0, 0.0],
        "diameter": 100.0,
        "type": "nozzle",
    }


def test_make_port3_negative_diameter_raises() -> None:
    with pytest.raises(ValueError):
        make_port3([0, 0, 0], [1, 0, 0], -1)


def test_base_component_validates_id() -> None:
    with pytest.raises(ValueError):
        BaseCAD3DComponent(id="")


def test_base_component_normalizes_center() -> None:
    component = BaseCAD3DComponent(id="B1", center=[1, 2])

    assert component.center == [1.0, 2.0, 0.0]


def test_base_component_to_scene_component_raises() -> None:
    with pytest.raises(NotImplementedError):
        BaseCAD3DComponent(id="B1").to_scene_component()


@dataclass
class FakeComponent(BaseCAD3DComponent):
    def ports(self):
        return {"out": make_port3([100, 0, 0], [1, 0, 0], 50, "test")}

    def to_scene_component(self):
        return {
            "component_type": "box_3d",
            "id": self.id,
            "center": self.center,
            "length": 100,
            "width": 50,
            "height": 25,
        }


def test_render_cad3d_component_works_with_fake_component() -> None:
    rendered = render_cad3d_component(FakeComponent(id="FC1"))

    assert rendered.component_id == "FC1"
    assert rendered.component_type == "box_3d"
    assert rendered.scene_component["component_type"] == "box_3d"
    assert "out" in rendered.ports

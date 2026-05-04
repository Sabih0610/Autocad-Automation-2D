from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.framework.cad3d.components.base import BaseCAD3DComponent, make_port3
from src.framework.cad3d.components.scene import CAD3DComponentScene, make_cad3d_component_scene
from src.framework.cad3d.scene_schema import validate_cad3d_scene


@dataclass
class Fake3DComponent(BaseCAD3DComponent):
    def ports(self):
        return {"out": make_port3([100, 0, 0], [1, 0, 0], 50, "nozzle")}

    def to_scene_component(self):
        return {
            "component_type": "box_3d",
            "id": self.id,
            "center": self.center,
            "length": 100,
            "width": 50,
            "height": 25,
        }


@dataclass
class Invalid3DComponent(BaseCAD3DComponent):
    def to_scene_component(self):
        return {"component_type": "box_3d", "id": self.id}


def test_scene_requires_title() -> None:
    with pytest.raises(ValueError):
        CAD3DComponentScene(title="")


def test_can_add_component() -> None:
    scene = CAD3DComponentScene(title="Scene")
    scene.add(Fake3DComponent(id="C1"))

    assert len(scene.components) == 1


def test_duplicate_id_raises_value_error() -> None:
    scene = CAD3DComponentScene(title="Scene")
    scene.add(Fake3DComponent(id="C1"))

    with pytest.raises(ValueError):
        scene.add(Fake3DComponent(id="C1"))


def test_get_component_works() -> None:
    component = Fake3DComponent(id="C1")
    scene = CAD3DComponentScene(title="Scene", components=[component])

    assert scene.get("C1") is component


def test_get_missing_component_raises_key_error() -> None:
    with pytest.raises(KeyError):
        CAD3DComponentScene(title="Scene").get("C1")


def test_all_ports_returns_qualified_keys() -> None:
    scene = CAD3DComponentScene(title="Scene", components=[Fake3DComponent(id="C1")])

    assert "C1.out" in scene.all_ports()


def test_to_scene_data_validates() -> None:
    scene = CAD3DComponentScene(title="Scene", components=[Fake3DComponent(id="C1")])
    scene_data = scene.to_scene_data()

    assert validate_cad3d_scene(scene_data) == []


def test_summary_includes_title_and_component_count() -> None:
    scene = CAD3DComponentScene(title="Scene", components=[Fake3DComponent(id="C1")])

    assert "Scene" in scene.summary()
    assert "1 component" in scene.summary()


def test_make_helper_creates_valid_scene() -> None:
    scene = make_cad3d_component_scene("Scene", [Fake3DComponent(id="C1")])

    assert validate_cad3d_scene(scene.to_scene_data()) == []


def test_invalid_scene_component_raises_value_error() -> None:
    scene = CAD3DComponentScene(title="Scene", components=[Invalid3DComponent(id="BAD")])

    with pytest.raises(ValueError):
        scene.to_scene_data()

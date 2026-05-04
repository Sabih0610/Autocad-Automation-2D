from __future__ import annotations

import pytest

from src.framework.cad3d.components.annotations import Label3DComponent
from src.framework.cad3d.components.scene import CAD3DComponentScene
from src.framework.cad3d.scene_schema import validate_cad3d_scene


def test_label_requires_text() -> None:
    with pytest.raises(ValueError):
        Label3DComponent(id="L1", text="")


def test_label_validates_in_scene() -> None:
    scene = CAD3DComponentScene(title="Label Test")
    scene.add(Label3DComponent(id="L1", text="T-101", center=[0, 0, 100], height=150))

    assert validate_cad3d_scene(scene.to_scene_data()) == []


def test_label_invalid_height_raises_value_error() -> None:
    with pytest.raises(ValueError):
        Label3DComponent(id="L1", text="T-101", height=0)

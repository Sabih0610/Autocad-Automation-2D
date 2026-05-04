"""Reusable 3D annotation components."""

from __future__ import annotations

from dataclasses import dataclass

from src.framework.cad3d.components.base import BaseCAD3DComponent


@dataclass
class Label3DComponent(BaseCAD3DComponent):
    text: str = ""
    height: float = 250.0

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("text must be non-empty")
        if float(self.height) <= 0:
            raise ValueError("height must be positive")
        self.text = self.text.strip()
        self.height = float(self.height)

    def to_scene_component(self) -> dict:
        return {
            "component_type": "label_3d",
            "id": self.id,
            "text": self.text,
            "position": self.center,
            "height": self.height,
            "metadata": self.metadata,
        }

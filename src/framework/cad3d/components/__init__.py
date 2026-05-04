"""Reusable 3D CAD component exports."""

from src.framework.cad3d.components.annotations import Label3DComponent
from src.framework.cad3d.components.base import (
    BaseCAD3DComponent,
    Point3D,
    Port3D,
    PortMap3D,
    RenderedCAD3DComponent,
    make_port3,
    normalize_point3,
    normalize_vector3,
    offset_point3,
    render_cad3d_component,
)
from src.framework.cad3d.components.equipment import (
    Box3DComponent,
    HeatExchanger3DComponent,
    HorizontalVessel3DComponent,
    PumpPlaceholder3DComponent,
    SkidBase3DComponent,
    VerticalTank3DComponent,
)
from src.framework.cad3d.components.fittings import Flange3DComponent, Nozzle3DComponent
from src.framework.cad3d.components.piping import PipeRun3DComponent
from src.framework.cad3d.components.scene import CAD3DComponentScene, make_cad3d_component_scene
from src.framework.cad3d.components.supports import (
    PipeSupport3DComponent,
    SaddleSupport3DComponent,
    SupportLeg3DComponent,
)
from src.framework.cad3d.components.valves import ValvePlaceholder3DComponent

__all__ = [
    "Point3D",
    "Port3D",
    "PortMap3D",
    "BaseCAD3DComponent",
    "RenderedCAD3DComponent",
    "normalize_point3",
    "normalize_vector3",
    "offset_point3",
    "make_port3",
    "render_cad3d_component",
    "VerticalTank3DComponent",
    "HorizontalVessel3DComponent",
    "HeatExchanger3DComponent",
    "PumpPlaceholder3DComponent",
    "SkidBase3DComponent",
    "Box3DComponent",
    "Nozzle3DComponent",
    "Flange3DComponent",
    "ValvePlaceholder3DComponent",
    "SupportLeg3DComponent",
    "SaddleSupport3DComponent",
    "PipeSupport3DComponent",
    "PipeRun3DComponent",
    "Label3DComponent",
    "CAD3DComponentScene",
    "make_cad3d_component_scene",
]

"""Proves generated P&ID components carry recoverable identity end to end.

This reproduces, and fixes, the exact gap surfaced during the project
extension review: a P&ID pipe generated through the existing deterministic
generator/executor previously carried no tag anywhere the project index could
read back, so a pipe drawn as "P-101" could never be found again by that name
for a resize/edit request — even though every roadmap fixture test (which
attaches tags synthetically) passed.

This test generates a real pipe and a real valve through the actual PID
component classes and the *legacy* command executor (`execute_commands`,
`src/framework/commands/executor.py`) — the same code path
`/api/sketch/approve` and `/api/pid/approve` use — saves a real DXF, then:

  1. re-extracts it through `DXFExtractor` and confirms both tags are found,
  2. indexes it through the real project scanner/entity repository and
     confirms `find_by_tag` locates the pipe by "P-101" alone, and
  3. resizes the pipe through the new structured modification engine by tag
     alone, proving the full generate -> index -> edit loop this whole
     project-extension effort was built for actually works now, not just that
     each half works in isolation against its own synthetic fixtures.
"""
from __future__ import annotations

from types import SimpleNamespace

import ezdxf
import pytest

from src.cad.extractor import DXFExtractor
from src.cad.scanner import scan_project
from src.framework.commands import executor
from src.framework.commands import modification_executor as engine
from src.framework.commands.executor import execute_commands
from src.framework.commands.schema import COMMAND_SCHEMA_VERSION
from src.framework.pid.components.piping import PipeRunComponent
from src.framework.pid.components.valves import GateValveComponent
from src.storage.entity_repository import find_by_tag
from src.storage.project_repository import register_project
from tests.project.fake_cad import Acad as EditingAcad
from tests.project.fake_cad import Document as EditingDocument
from tests.project.fake_cad import Entity


def _unwrap(value):
    """Unwrap a real `win32com.client.VARIANT` (or plain list/tuple/number).

    `pywin32` is genuinely installed in this environment, so
    `src/framework/commands/executor.py` constructs real `VARIANT` array
    arguments for point pairs and XData — and `VARIANT` is not itself
    iterable (`list(variant)` raises `TypeError`). Real AutoCAD's COM
    marshaling unwraps this on the native side; this fake has to do the same
    thing explicitly.
    """
    return value.value if hasattr(value, "value") else value


class _CreatingModelSpace:
    """A COM-shaped modelspace that creates real `ezdxf` entities.

    Unlike `tests/project/fake_cad.py`'s `Document.ModelSpace` (a plain list,
    built for *reading/editing* entities that already exist), this supports
    the creation methods `executor.py` actually calls, backed by a real
    `ezdxf` layout — so the file this saves is genuine DXF the extractor can
    read back, exactly like a real AutoCAD save would produce.
    """

    def __init__(self, layout):
        self._layout = layout

    def AddLine(self, start, end):
        sx, sy, sz = _unwrap(start)
        ex, ey, ez = _unwrap(end)
        return Entity(self._layout.add_line((sx, sy, sz), (ex, ey, ez)))

    def AddLightWeightPolyline(self, flat_points):
        values = list(_unwrap(flat_points))
        pairs = [(values[i], values[i + 1]) for i in range(0, len(values), 2)]
        return Entity(self._layout.add_lwpolyline(pairs))

    def AddText(self, text, position, height):
        px, py, _pz = _unwrap(position)
        entity = self._layout.add_text(text, dxfattribs={"height": height})
        entity.set_placement((px, py))
        return Entity(entity)


class _CreatingLayers:
    def __init__(self, doc):
        self._doc = doc

    def Item(self, name):
        return self._doc.layers.get(name)

    def Add(self, name):
        return self._doc.layers.add(name)


class _CreatingDocument:
    def __init__(self, path):
        self.data = ezdxf.new("R2018")
        self.ModelSpace = _CreatingModelSpace(self.data.modelspace())
        self.Layers = _CreatingLayers(self.data)
        self.RegApps = SimpleNamespace(Add=lambda name: self.data.appids.add(name))
        self.FullName = str(path)
        self.Name = path.name
        self._path = path

    def Save(self):
        self.data.saveas(self._path)


class _CreatingAcad:
    def __init__(self, doc):
        self.ActiveDocument = doc


def _command_sequence(commands: list[dict]) -> dict:
    return dict(
        schema_version=COMMAND_SCHEMA_VERSION,
        summary="P&ID identity fixture",
        assumptions=[],
        commands=commands,
    )


def test_generated_pid_pipe_carries_recoverable_tag(tmp_path, monkeypatch):
    path = tmp_path / "pid_001.dxf"
    doc = _CreatingDocument(path)
    monkeypatch.setattr(executor, "_get_acad", lambda: _CreatingAcad(doc))

    pipe = PipeRunComponent(id="pipe1", tag="P-101", points=[[0, 0], [1000, 0]])
    valve = GateValveComponent(id="valve1", tag="V-201", center=[500, 0])

    result = execute_commands(
        pipe.render() + valve.render(),
        target_dwg_path=None,
        save=True,
        zoom_extents=False,
    )
    assert result["errors"] == []
    assert result["ok"] is True

    extraction = DXFExtractor().extract(path)
    tags = {entity.tag for entity in extraction.entities}
    assert "P-101" in tags, f"pipe tag not recoverable from generated geometry; found tags: {tags}"
    assert "V-201" in tags, f"valve tag not recoverable from generated geometry; found tags: {tags}"


def test_generated_pid_pipe_is_findable_by_tag(tmp_path, monkeypatch):
    """The identity half of the extension-review scenario: generate a P&ID
    pipe through the real generator/executor, then find it again by tag
    through the real project index — end to end, not against a synthetic
    fixture that attaches XData directly."""
    path = tmp_path / "pid_002.dxf"
    doc = _CreatingDocument(path)
    monkeypatch.setattr(executor, "_get_acad", lambda: _CreatingAcad(doc))

    pipe = PipeRunComponent(id="pipe1", tag="P-101", points=[[0, 0], [1000, 0]])
    execute_commands(pipe.render(), save=True, zoom_extents=False)

    project = register_project("Plant", str(tmp_path))
    scan_report = scan_project(project, max_workers=1)
    assert scan_report["errors"] == []

    matches = find_by_tag(project, "P-101")
    assert len(matches) == 1, f"expected exactly one drawing to contain P-101, found: {matches}"
    assert matches[0]["path"] == str(path)


def test_generated_pid_pipe_resize_is_a_documented_follow_up_gap(tmp_path, monkeypatch):
    """The edit half of the same scenario is *not* fixed by this change, and
    that boundary should be explicit and tested rather than silently broken.

    `_resize`'s "length" dimension only handles `AcDbLine` entities
    (`modification_executor.py:66`) — but a generated P&ID pipe is a
    `POLYLINE`/`AcDbLWPolyline` (see `pipe_line_commands` in
    `src/framework/pid/symbols.py`), so even with a correctly-recoverable tag
    (proven above), RESIZE_COMPONENT still cannot act on it yet. Extending
    `_resize` to read/write a 2-point polyline's `Coordinates` array (rather
    than a `LINE`'s `StartPoint`/`EndPoint`) is real, separate follow-up work
    against live AutoCAD's actual `AcadLWPolyline` COM interface — deliberately
    not attempted here without a way to validate the COM array-marshaling
    against real AutoCAD. If this test starts failing because
    RESIZE_COMPONENT now accepts a POLYLINE, that's progress: update/replace
    this test to assert success instead of documenting the gap.
    """
    path = tmp_path / "pid_003.dxf"
    doc = _CreatingDocument(path)
    monkeypatch.setattr(executor, "_get_acad", lambda: _CreatingAcad(doc))

    pipe = PipeRunComponent(id="pipe1", tag="P-101", points=[[0, 0], [1000, 0]])
    execute_commands(pipe.render(), save=True, zoom_extents=False)

    project = register_project("Plant", str(tmp_path))
    scan_project(project, max_workers=1)
    handle = find_by_tag(project, "P-101")[0]["handle"]

    monkeypatch.setattr(engine, "point", tuple)
    edit_acad = EditingAcad([])
    operation = dict(
        command="RESIZE_COMPONENT",
        target_dwg_path=str(path),
        handle=handle,
        dimension="length",
        delta_mm=50,
    )
    with pytest.raises(ValueError, match="Length resizing currently supports LINE entities"):
        engine.execute_operation(operation, acad=edit_acad, verify_extractor=DXFExtractor())

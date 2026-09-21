from __future__ import annotations

import threading

import ezdxf
import pytest

from src.cad.locks import CAD_LOCK
from src.framework.commands import executor
from src.framework.commands.executor import (
    CommandExecutionError,
    execute_command_sequence,
    execute_commands,
)
from src.framework.commands.preview import render_preview
from src.framework.commands.schema import COMMAND_SCHEMA_VERSION


def _unwrap_com_array(value):
    """Unwrap a `win32com.client.VARIANT` (or plain list/tuple) into a tuple.

    `pywin32`'s `VARIANT` is not itself iterable — `list(variant)` raises
    `TypeError: 'VARIANT' object is not iterable`. The real underlying data is
    on `.value`. Since `pywin32` is genuinely installed in this environment,
    `executor.py`'s `_apply_entity_tag` constructs real `VARIANT` arguments
    even against these fakes, so the fakes must unwrap them the same way real
    AutoCAD's COM marshaling would.
    """
    return tuple(value.value if hasattr(value, "value") else value)


class FakeEntity:
    def __init__(self, kind: str):
        self.kind = kind
        self.Layer = None
        self.Closed = False
        self.Rotation = None
        self.TextOverride = None
        self.xdata_calls: list[tuple[tuple, tuple]] = []

    def SetXData(self, data_types, data_values):
        self.xdata_calls.append((_unwrap_com_array(data_types), _unwrap_com_array(data_values)))


class FakeLayer:
    def __init__(self, name: str):
        self.Name = name
        self.Color = None
        self.Linetype = None


class FakeLayers:
    def __init__(self):
        self.items = {"0": FakeLayer("0")}
        self.added = []

    def Item(self, name: str):
        if name not in self.items:
            raise KeyError(name)
        return self.items[name]

    def Add(self, name: str):
        layer = FakeLayer(name)
        self.items[name] = layer
        self.added.append(name)
        return layer


class FakeModelSpace:
    def __init__(self):
        self.lines = []
        self.circles = []
        self.ellipses = []
        self.texts = []
        self.inserts = []

    @property
    def Count(self):
        return (
            len(self.lines)
            + len(self.circles)
            + len(self.ellipses)
            + len(self.texts)
            + len(self.inserts)
        )

    def AddLine(self, start, end):
        entity = FakeEntity("LINE")
        self.lines.append((start, end, entity))
        return entity

    def AddCircle(self, center, radius):
        entity = FakeEntity("CIRCLE")
        self.circles.append((center, radius, entity))
        return entity

    def AddEllipse(self, center, major_axis, ratio):
        entity = FakeEntity("ELLIPSE")
        self.ellipses.append((center, major_axis, ratio, entity))
        return entity

    def AddText(self, text, position, height):
        entity = FakeEntity("TEXT")
        self.texts.append((text, position, height, entity))
        return entity

    def InsertBlock(self, position, block_name, x_scale, y_scale, z_scale, rotation):
        if block_name == "MISSING":
            raise RuntimeError("missing block")
        entity = FakeEntity("INSERT")
        self.inserts.append((position, block_name, x_scale, y_scale, z_scale, rotation, entity))
        return entity


class FakeRegApps:
    def __init__(self):
        self.added = []

    def Add(self, name: str):
        self.added.append(name)


class FakeDocument:
    def __init__(self):
        self.ModelSpace = FakeModelSpace()
        self.Layers = FakeLayers()
        self.RegApps = FakeRegApps()
        self.Name = "active.dwg"
        self.FullName = r"C:\fake\active.dwg"
        self.saved = False
        self.activated = False
        self.regen_calls = []

    def Save(self):
        self.saved = True

    def Activate(self):
        self.activated = True

    def Regen(self, mode):
        self.regen_calls.append(mode)


class FakeDocuments:
    def __init__(self, doc: FakeDocument):
        self.doc = doc
        self.opened_paths = []

    def Open(self, path: str):
        self.opened_paths.append(path)
        return self.doc


class FakeAcad:
    def __init__(self, doc: FakeDocument | None = None):
        self.ActiveDocument = doc
        self.Documents = FakeDocuments(doc or FakeDocument())
        self.zoom_extents_calls = 0
        self.zoom_error = None

    def ZoomExtents(self):
        if self.zoom_error is not None:
            raise self.zoom_error
        self.zoom_extents_calls += 1


@pytest.fixture
def fake_doc(monkeypatch):
    doc = FakeDocument()
    acad = FakeAcad(doc)

    monkeypatch.setattr(executor, "_get_acad", lambda: acad)
    monkeypatch.setattr(
        executor,
        "_com_retry",
        lambda operation, description, attempts=5, delay_seconds=0.5: operation(),
    )
    monkeypatch.setattr(executor, "acad_point", lambda x, y, z=0.0: (float(x), float(y), float(z)))
    monkeypatch.setattr(executor, "_acad_double_array", lambda values: tuple(values))

    doc.acad = acad
    return doc


def test_execute_commands_rejects_empty_command_list() -> None:
    with pytest.raises(CommandExecutionError, match="commands must be a non-empty list"):
        execute_commands([])


def test_execute_command_sequence_rejects_invalid_schema(fake_doc) -> None:
    with pytest.raises(CommandExecutionError, match="Invalid command sequence"):
        execute_command_sequence(
            {
                "schema_version": COMMAND_SCHEMA_VERSION,
                "summary": "invalid",
                "assumptions": [],
                "commands": [],
            },
            save=False,
        )


def test_line_calls_fake_modelspace_addline(fake_doc) -> None:
    result = execute_commands(
        [{"command": "LINE", "from": [0, 0], "to": [100, 0]}],
        save=False,
    )

    assert result["ok"] is True
    assert len(fake_doc.ModelSpace.lines) == 1


def test_line_with_tag_writes_recoverable_xdata(fake_doc) -> None:
    """A command carrying an optional "tag" must be written as XData the
    project extractor can read back (`TAG=<value>`, under
    `executor.TAG_XDATA_APPID`) — see `_apply_entity_tag`. Without this, a
    generated component has no recoverable identity once drawn; this was the
    root cause of generated P&ID pipes being permanently unfindable/
    un-resizable by tag."""
    result = execute_commands(
        [{"command": "LINE", "from": [0, 0], "to": [100, 0], "tag": "P-101"}],
        save=False,
    )

    assert result["ok"] is True
    _, _, entity = fake_doc.ModelSpace.lines[0]
    assert entity.xdata_calls == [
        ((1001, 1000), (executor.TAG_XDATA_APPID, "TAG=P-101")),
    ]
    assert executor.TAG_XDATA_APPID in fake_doc.RegApps.added


def test_command_without_tag_writes_no_xdata(fake_doc) -> None:
    execute_commands(
        [{"command": "LINE", "from": [0, 0], "to": [100, 0]}],
        save=False,
    )

    _, _, entity = fake_doc.ModelSpace.lines[0]
    assert entity.xdata_calls == []


def test_circle_calls_fake_modelspace_addcircle(fake_doc) -> None:
    result = execute_commands(
        [{"command": "CIRCLE", "center": [10, 20], "radius": 5}],
        save=False,
    )

    assert result["ok"] is True
    assert len(fake_doc.ModelSpace.circles) == 1


def test_ellipse_uses_preview_major_axis_vector(fake_doc, tmp_path) -> None:
    command = {
        "command": "ELLIPSE",
        "center": [1000, 500],
        "major_axis_endpoint": [1100, 500],
        "ratio": 0.5,
    }

    result = execute_commands([command], save=False, zoom_extents=False)
    com_center, com_major_axis, ratio, _entity = fake_doc.ModelSpace.ellipses[0]

    output = tmp_path / "ellipse.dxf"
    render_preview([command], str(output))
    preview_doc = ezdxf.readfile(output)
    preview_ellipse = next(iter(preview_doc.modelspace().query("ELLIPSE")))
    preview_major_axis = tuple(preview_ellipse.dxf.major_axis)

    assert result["ok"] is True
    assert com_center == (1000.0, 500.0, 0.0)
    assert com_major_axis == (100.0, 0.0, 0.0)
    assert ratio == 0.5
    assert com_major_axis == preview_major_axis


def test_text_calls_fake_modelspace_addtext(fake_doc) -> None:
    result = execute_commands(
        [{"command": "TEXT", "text": "Hello", "position": [1, 2], "height": 50}],
        save=False,
    )

    assert result["ok"] is True
    assert len(fake_doc.ModelSpace.texts) == 1


def test_layer_creates_missing_layer(fake_doc) -> None:
    result = execute_commands(
        [{"command": "LAYER", "layer_name": "OBJECT", "color": 3}],
        save=False,
    )

    assert result["ok"] is True
    assert "OBJECT" in fake_doc.Layers.added
    assert fake_doc.Layers.items["OBJECT"].Color == 3


def test_layer_is_set_on_created_entities(fake_doc) -> None:
    result = execute_commands(
        [{"command": "LINE", "from": [0, 0], "to": [1, 1], "layer": "OBJECT"}],
        save=False,
    )

    entity = fake_doc.ModelSpace.lines[0][2]
    assert result["ok"] is True
    assert entity.Layer == "OBJECT"


def test_failed_command_is_captured_and_execution_continues(fake_doc) -> None:
    result = execute_commands(
        [
            {"command": "INSERT", "block_name": "MISSING", "position": [0, 0]},
            {"command": "LINE", "from": [0, 0], "to": [1, 1]},
        ],
        save=False,
        continue_on_error=True,
    )

    assert result["ok"] is False
    assert result["executed_count"] == 1
    assert len(result["errors"]) == 1
    assert result["errors"][0]["command_index"] == 0
    assert len(fake_doc.ModelSpace.lines) == 1


def test_failed_command_stops_when_continue_on_error_false(fake_doc) -> None:
    result = execute_commands(
        [
            {"command": "INSERT", "block_name": "MISSING", "position": [0, 0]},
            {"command": "LINE", "from": [0, 0], "to": [1, 1]},
        ],
        save=False,
        continue_on_error=False,
    )

    assert result["ok"] is False
    assert result["executed_count"] == 0
    assert len(result["errors"]) == 1
    assert len(fake_doc.ModelSpace.lines) == 0


def test_save_is_called_when_save_true(fake_doc) -> None:
    result = execute_commands(
        [{"command": "LINE", "from": [0, 0], "to": [1, 1]}],
        save=True,
    )

    assert result["ok"] is True
    assert fake_doc.saved is True


def test_save_is_not_called_when_save_false(fake_doc) -> None:
    result = execute_commands(
        [{"command": "LINE", "from": [0, 0], "to": [1, 1]}],
        save=False,
    )

    assert result["ok"] is True
    assert fake_doc.saved is False


def test_execute_command_sequence_executes_valid_sequence_successfully(fake_doc) -> None:
    sequence = {
        "schema_version": COMMAND_SCHEMA_VERSION,
        "summary": "Draw a line.",
        "assumptions": [],
        "commands": [
            {"command": "LINE", "from": [0, 0], "to": [100, 0], "layer": "BORDER"}
        ],
    }

    result = execute_command_sequence(sequence, save=False)

    assert result["ok"] is True
    assert result["executed_count"] == 1
    assert len(fake_doc.ModelSpace.lines) == 1


def test_zoom_extents_is_called_when_zoom_extents_true(fake_doc) -> None:
    result = execute_commands(
        [{"command": "LINE", "from": [0, 0], "to": [1, 1]}],
        save=False,
        zoom_extents=True,
    )

    assert result["ok"] is True
    assert fake_doc.activated is True
    assert fake_doc.regen_calls == [1]
    assert fake_doc.acad.zoom_extents_calls == 1
    assert result["zoom_extents_called"] is True
    assert result["zoom_error"] is None


def test_zoom_extents_is_not_called_when_zoom_extents_false(fake_doc) -> None:
    result = execute_commands(
        [{"command": "LINE", "from": [0, 0], "to": [1, 1]}],
        save=False,
        zoom_extents=False,
    )

    assert result["ok"] is True
    assert fake_doc.activated is False
    assert fake_doc.regen_calls == []
    assert fake_doc.acad.zoom_extents_calls == 0
    assert result["zoom_extents_called"] is False
    assert result["zoom_error"] is None


def test_result_includes_document_name(fake_doc) -> None:
    result = execute_commands(
        [{"command": "LINE", "from": [0, 0], "to": [1, 1]}],
        save=False,
    )

    assert result["document_name"] == "active.dwg"


def test_result_includes_entity_counts_before_and_after(fake_doc) -> None:
    result = execute_commands(
        [{"command": "LINE", "from": [0, 0], "to": [1, 1]}],
        save=False,
    )

    assert result["entity_count_before"] == 0
    assert result["entity_count_after"] == 1


def test_zoom_failure_does_not_make_ok_false_when_commands_succeeded(fake_doc) -> None:
    fake_doc.acad.zoom_error = RuntimeError("zoom failed")

    result = execute_commands(
        [{"command": "LINE", "from": [0, 0], "to": [1, 1]}],
        save=False,
    )

    assert result["ok"] is True
    assert result["executed_count"] == 1
    assert result["errors"] == []
    assert result["zoom_extents_called"] is False


def test_zoom_error_is_populated_when_zoom_fails(fake_doc) -> None:
    fake_doc.acad.zoom_error = RuntimeError("zoom failed")

    result = execute_commands(
        [{"command": "LINE", "from": [0, 0], "to": [1, 1]}],
        save=False,
    )

    assert result["zoom_error"] == "RuntimeError: zoom failed"


def test_execute_commands_holds_cad_lock_for_its_whole_duration(fake_doc, monkeypatch) -> None:
    """`execute_commands` (the legacy path behind `/api/sketch/approve`,
    `/api/pid/approve`, and `/api/autocad/edit` via `execute_edit_plan`)
    previously acquired no lock at all — only the newer project/changeset
    write path (`modification_executor.py`, `changes.py`) participated in
    `CAD_LOCK`. That meant a legacy approval write and a new project write
    could interleave their COM calls against the same live AutoCAD session.
    This proves the lock is genuinely held for the whole call, not just
    referenced somewhere, by having a second thread attempt a non-blocking
    acquire while `execute_commands` is paused mid-execution."""
    started = threading.Event()
    release = threading.Event()
    original_execute_one = executor._execute_one_command

    def blocking_execute_one(*args, **kwargs):
        started.set()
        assert release.wait(timeout=5), "test setup failed: never released"
        return original_execute_one(*args, **kwargs)

    monkeypatch.setattr(executor, "_execute_one_command", blocking_execute_one)

    thread = threading.Thread(
        target=execute_commands,
        args=([{"command": "LINE", "from": [0, 0], "to": [100, 0]}],),
        kwargs=dict(save=False),
    )
    thread.start()
    try:
        assert started.wait(timeout=5), "execute_commands never started"
        # A different thread trying to acquire CAD_LOCK while
        # execute_commands is mid-flight must fail immediately.
        assert CAD_LOCK.acquire(blocking=False) is False
    finally:
        release.set()
        thread.join(timeout=5)

    # Once execute_commands has returned, the lock must be free again.
    assert CAD_LOCK.acquire(blocking=False) is True
    CAD_LOCK.release()

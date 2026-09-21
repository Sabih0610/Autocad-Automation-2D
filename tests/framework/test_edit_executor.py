from __future__ import annotations

import pytest

from src.framework.commands import edit_executor
from src.framework.commands.edit_executor import (
    EditExecutionError,
    execute_edit_plan,
)


def _delete_only_plan() -> dict:
    return {
        "schema_version": "1.0",
        "edit_intent": "Delete the center circle.",
        "summary": "Delete one circle.",
        "target_description": "Circle on layer CENTERLINE.",
        "assumptions": [],
        "delete_handles": ["26C"],
        "commands": [],
    }


def _add_only_plan() -> dict:
    return {
        "schema_version": "1.0",
        "edit_intent": "Add a new circle.",
        "summary": "Add a new circle.",
        "assumptions": [],
        "delete_handles": [],
        "commands": [
            {
                "command": "CIRCLE",
                "center": [800, 250],
                "radius": 100,
                "layer": "CENTERLINE",
            }
        ],
    }


def _replace_plan() -> dict:
    return {
        "schema_version": "1.0",
        "edit_intent": "Move title upward.",
        "summary": "Replace title at new position.",
        "assumptions": ["Represented move as delete plus add."],
        "delete_handles": ["26D"],
        "commands": [
            {
                "command": "TEXT",
                "text": "My Drawing",
                "position": [0, 800],
                "height": 80,
                "layer": "TEXT",
            }
        ],
    }


class FakeEntity:
    def __init__(self, handle: str, call_log: list[str]):
        self.handle = handle
        self.call_log = call_log
        self.deleted = False
        self.delete_error: Exception | None = None

    def Delete(self):
        self.call_log.append(f"delete:{self.handle}")
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted = True


class FakeModelSpace:
    def __init__(self, entities: dict[str, FakeEntity]):
        self.entities = entities

    @property
    def Count(self):
        return len(
            [
                entity
                for entity in self.entities.values()
                if not entity.deleted
            ]
        )


class FakeDocument:
    def __init__(self):
        self.call_log: list[str] = []
        self.entities = {
            "26C": FakeEntity("26C", self.call_log),
            "26D": FakeEntity("26D", self.call_log),
        }
        self.ModelSpace = FakeModelSpace(self.entities)
        self.Name = "active.dwg"
        self.FullName = r"C:\fake\active.dwg"
        self.handle_requests: list[str] = []
        self.saved = False
        self.activated = False
        self.regen_calls: list[int] = []

    def HandleToObject(self, handle: str):
        self.handle_requests.append(handle)
        if handle not in self.entities:
            raise KeyError(handle)
        return self.entities[handle]

    def Save(self):
        self.saved = True

    def Activate(self):
        self.activated = True

    def Regen(self, mode: int):
        self.regen_calls.append(mode)


class FakeDocuments:
    def __init__(self, acad, doc: FakeDocument):
        self.acad = acad
        self.doc = doc
        self.opened_paths: list[str] = []

    def Open(self, path: str):
        self.opened_paths.append(path)
        self.acad.ActiveDocument = self.doc
        return self.doc


class FakeAcad:
    def __init__(self, doc: FakeDocument):
        self.ActiveDocument = doc
        self.Documents = FakeDocuments(self, doc)
        self.zoom_extents_calls = 0
        self.zoom_error: Exception | None = None

    def ZoomExtents(self):
        if self.zoom_error is not None:
            raise self.zoom_error
        self.zoom_extents_calls += 1


@pytest.fixture
def fake_doc(monkeypatch):
    doc = FakeDocument()
    acad = FakeAcad(doc)

    monkeypatch.setattr(edit_executor, "_get_acad", lambda: acad)
    monkeypatch.setattr(
        edit_executor,
        "_com_retry",
        lambda operation, description, attempts=5, delay_seconds=0.5: operation(),
    )

    doc.acad = acad
    return doc


def _patch_execute_commands(monkeypatch, captured: dict | None = None, result: dict | None = None):
    captured = captured if captured is not None else {}
    captured.setdefault("calls", [])

    def fake_execute_commands_in_document(
        commands,
        doc,
        continue_on_error=True,
    ):
        captured["calls"].append(
            {
                "commands": commands,
                # The document is now passed explicitly instead of being
                # re-resolved from ActiveDocument, so record it: tests assert
                # the additions target the same document as the deletions.
                "doc": doc,
                "continue_on_error": continue_on_error,
            }
        )

        if result is not None:
            return result

        return {
            "ok": True,
            "executed_count": len(commands),
            "total_count": len(commands),
            "errors": [],
        }

    monkeypatch.setattr(
        edit_executor, "execute_commands_in_document", fake_execute_commands_in_document
    )
    return captured


def test_invalid_edit_plan_raises_edit_execution_error() -> None:
    with pytest.raises(EditExecutionError, match="Invalid edit plan"):
        execute_edit_plan(
            {
                "schema_version": "1.0",
                "edit_intent": "Invalid.",
                "summary": "Invalid.",
                "assumptions": [],
                "delete_handles": [],
                "commands": [],
            }
        )


def test_delete_only_edit_calls_handle_to_object_and_delete(fake_doc, monkeypatch) -> None:
    _patch_execute_commands(monkeypatch)

    result = execute_edit_plan(_delete_only_plan(), save=False, zoom_extents=False)

    assert result["ok"] is True
    assert fake_doc.handle_requests == ["26C"]
    assert fake_doc.entities["26C"].deleted is True
    assert result["deleted_count"] == 1
    assert result["delete_count"] == 1


def test_add_only_edit_targets_the_document_it_opened(fake_doc, monkeypatch) -> None:
    """Additions must go to the document `execute_edit_plan` resolved, not to
    a separately-resolved ActiveDocument.

    This assertion used to read `target_dwg_path is None`, which encoded the
    bug as correct behaviour: delegating with no target made the additions
    resolve ActiveDocument independently, so with a different drawing focused
    the deletions landed in one file and the new geometry in another, and only
    the first was saved."""
    captured = _patch_execute_commands(monkeypatch)

    result = execute_edit_plan(_add_only_plan(), save=False, zoom_extents=False)

    assert result["ok"] is True
    assert len(captured["calls"]) == 1
    assert captured["calls"][0]["commands"] == _add_only_plan()["commands"]
    assert captured["calls"][0]["doc"] is fake_doc
    assert captured["calls"][0]["continue_on_error"] is True
    assert result["added_executed_count"] == 1
    assert result["added_total_count"] == 1


def test_replace_style_edit_deletes_first_then_adds_commands(fake_doc, monkeypatch) -> None:
    def fake_execute_commands_in_document(*args, **kwargs):
        fake_doc.call_log.append("add")
        return {
            "ok": True,
            "executed_count": 1,
            "total_count": 1,
            "errors": [],
        }

    monkeypatch.setattr(
        edit_executor, "execute_commands_in_document", fake_execute_commands_in_document
    )

    result = execute_edit_plan(_replace_plan(), save=False, zoom_extents=False)

    assert result["ok"] is True
    assert fake_doc.call_log == ["delete:26D", "add"]


def test_delete_failure_is_captured_and_continues_when_continue_on_error_true(fake_doc, monkeypatch) -> None:
    fake_doc.entities["26D"].delete_error = RuntimeError("delete failed")
    captured = _patch_execute_commands(monkeypatch)

    result = execute_edit_plan(
        _replace_plan(),
        save=False,
        zoom_extents=False,
        continue_on_error=True,
    )

    assert result["ok"] is False
    assert len(result["errors"]) == 1
    assert result["errors"][0]["type"] == "delete"
    assert result["errors"][0]["handle"] == "26D"
    assert "RuntimeError: delete failed" in result["errors"][0]["error"]
    assert len(captured["calls"]) == 1


def test_delete_failure_stops_additions_when_continue_on_error_false(fake_doc, monkeypatch) -> None:
    fake_doc.entities["26D"].delete_error = RuntimeError("delete failed")
    captured = _patch_execute_commands(monkeypatch)

    result = execute_edit_plan(
        _replace_plan(),
        save=False,
        zoom_extents=False,
        continue_on_error=False,
    )

    assert result["ok"] is False
    assert len(result["errors"]) == 1
    assert captured["calls"] == []
    assert result["added_executed_count"] == 0
    assert result["added_total_count"] == 1


def test_save_is_called_when_save_true(fake_doc, monkeypatch) -> None:
    _patch_execute_commands(monkeypatch)

    result = execute_edit_plan(_delete_only_plan(), save=True, zoom_extents=False)

    assert result["ok"] is True
    assert fake_doc.saved is True


def test_save_is_not_called_when_save_false(fake_doc, monkeypatch) -> None:
    _patch_execute_commands(monkeypatch)

    result = execute_edit_plan(_delete_only_plan(), save=False, zoom_extents=False)

    assert result["ok"] is True
    assert fake_doc.saved is False


def test_zoom_extents_is_called_when_zoom_extents_true(fake_doc, monkeypatch) -> None:
    _patch_execute_commands(monkeypatch)

    result = execute_edit_plan(_delete_only_plan(), save=False, zoom_extents=True)

    assert result["ok"] is True
    assert fake_doc.activated is True
    assert fake_doc.regen_calls == [1]
    assert fake_doc.acad.zoom_extents_calls == 1
    assert result["zoom_extents_called"] is True
    assert result["zoom_error"] is None


def test_zoom_extents_is_not_called_when_zoom_extents_false(fake_doc, monkeypatch) -> None:
    _patch_execute_commands(monkeypatch)

    result = execute_edit_plan(_delete_only_plan(), save=False, zoom_extents=False)

    assert result["ok"] is True
    assert fake_doc.activated is False
    assert fake_doc.regen_calls == []
    assert fake_doc.acad.zoom_extents_calls == 0
    assert result["zoom_extents_called"] is False
    assert result["zoom_error"] is None


def test_result_includes_document_name_and_entity_counts(fake_doc, monkeypatch) -> None:
    _patch_execute_commands(monkeypatch)

    result = execute_edit_plan(_delete_only_plan(), save=False, zoom_extents=False)

    assert result["document_name"] == "active.dwg"
    assert result["dwg_path"] == r"C:\fake\active.dwg"
    assert result["entity_count_before"] == 2
    assert result["entity_count_after"] == 1


def test_add_command_errors_make_final_result_not_ok(fake_doc, monkeypatch) -> None:
    _patch_execute_commands(
        monkeypatch,
        result={
            "ok": False,
            "executed_count": 0,
            "total_count": 1,
            "errors": [
                {
                    "command_index": 0,
                    "command": _add_only_plan()["commands"][0],
                    "error": "RuntimeError: add failed",
                }
            ],
        },
    )

    result = execute_edit_plan(_add_only_plan(), save=False, zoom_extents=False)

    assert result["ok"] is False
    assert result["added_executed_count"] == 0
    assert result["added_total_count"] == 1
    assert result["errors"][0]["type"] == "add"
    assert result["errors"][0]["error"] == "RuntimeError: add failed"


def test_zoom_failure_does_not_make_ok_false_when_edits_succeeded(fake_doc, monkeypatch) -> None:
    _patch_execute_commands(monkeypatch)
    fake_doc.acad.zoom_error = RuntimeError("zoom failed")

    result = execute_edit_plan(_delete_only_plan(), save=False, zoom_extents=True)

    assert result["ok"] is True
    assert result["errors"] == []
    assert result["zoom_extents_called"] is False
    assert result["zoom_error"] == "RuntimeError: zoom failed"

from __future__ import annotations

from copy import deepcopy

from src.framework.commands import executor as command_executor
from src.framework.commands import edit_executor
from src.framework.cad3d import autocad_3d_executor as cad3d_executor
from src.framework.cad3d.scene_examples import (
    simple_3d_equipment_layout_scene,
)


class _ModelSpace:
    Count = 0


class _Document:
    def __init__(self, path: str):
        self.Name = "retry.dwg"
        self.FullName = path
        self.ModelSpace = _ModelSpace()
        self.Layers = object()
        self.closed = False

    def Close(self, save_changes=False):
        assert save_changes is False
        self.closed = True


class _Documents:
    def __init__(self):
        self.documents = []

    @property
    def Count(self):
        return len(
            [
                doc
                for doc in self.documents
                if not doc.closed
            ]
        )

    def Item(self, index):
        open_documents = [
            doc
            for doc in self.documents
            if not doc.closed
        ]
        return open_documents[index]


class _Acad:
    def __init__(self):
        self.Documents = _Documents()


def _retry_once(
    operation,
    description,
    attempts=5,
    delay_seconds=0.5,
):
    del description, attempts, delay_seconds

    try:
        return operation()
    except AttributeError:
        return operation()


def _install_retrying_open(
    monkeypatch,
    module,
    acad,
    doc,
):
    calls = {
        "count": 0,
    }

    def fake_open_document(
        _acad,
        target_dwg_path,
        bookkeeping_warnings=None,
    ):
        del bookkeeping_warnings
        assert _acad is acad
        assert target_dwg_path == doc.FullName

        calls["count"] += 1

        if calls["count"] == 1:
            # Model the real failure:
            #
            # Documents.Open succeeded, so the document is now open
            # in AutoCAD, but a later COM property access raised a
            # transient busy error before open_document() could
            # return its ownership flag.
            acad.Documents.documents.append(doc)

            raise AttributeError(
                "simulated AutoCAD busy after opening document"
            )

        # On the retry, open_document sees the document already
        # open and reports that THIS attempt did not open it.
        #
        # The outer executor must nevertheless remember that the
        # drawing was not open before the retry sequence began.
        return doc, False

    monkeypatch.setattr(
        module,
        "_get_acad",
        lambda: acad,
    )

    monkeypatch.setattr(
        module,
        "_com_retry",
        _retry_once,
    )

    monkeypatch.setattr(
        module,
        "open_document",
        fake_open_document,
    )

    monkeypatch.setattr(
        module,
        "close_document",
        lambda document, _path, bookkeeping_warnings=None:
            document.Close(False),
    )

    return calls


def test_execute_commands_closes_document_opened_by_failed_retry_attempt(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "retry-command.dwg"
    target.write_bytes(b"")

    acad = _Acad()
    doc = _Document(str(target))

    calls = _install_retrying_open(
        monkeypatch,
        command_executor,
        acad,
        doc,
    )

    def fake_run_commands(
        commands,
        doc,
        msp,
        layers,
        known_layers,
        continue_on_error,
    ):
        return len(commands), []

    monkeypatch.setattr(
        command_executor,
        "_run_commands",
        fake_run_commands,
    )

    result = command_executor.execute_commands(
        [
            {
                "command": "LINE",
                "from": [0, 0],
                "to": [1, 0],
            }
        ],
        target_dwg_path=str(target),
        save=False,
        zoom_extents=False,
    )

    assert result["ok"] is True
    assert calls["count"] == 2

    # Critical assertion:
    # although the final retry attempt returned opened_here=False,
    # the document was not open before the retry sequence started.
    assert doc.closed is True


def test_execute_edit_plan_closes_document_opened_by_failed_retry_attempt(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "retry-edit.dwg"
    target.write_bytes(b"")

    acad = _Acad()
    doc = _Document(str(target))

    calls = _install_retrying_open(
        monkeypatch,
        edit_executor,
        acad,
        doc,
    )

    monkeypatch.setattr(
        edit_executor,
        "execute_commands_in_document",
        lambda commands, doc, continue_on_error=True: {
            "ok": True,
            "executed_count": len(commands),
            "total_count": len(commands),
            "errors": [],
        },
    )

    plan = {
        "schema_version": "1.0",
        "edit_intent": "Add one line.",
        "summary": (
            "Add one line for retry ownership test."
        ),
        "assumptions": [],
        "delete_handles": [],
        "commands": [
            {
                "command": "LINE",
                "from": [0, 0],
                "to": [1, 0],
            }
        ],
    }

    result = edit_executor.execute_edit_plan(
        plan,
        target_dwg_path=str(target),
        save=False,
        zoom_extents=False,
    )

    assert result["ok"] is True
    assert calls["count"] == 2
    assert doc.closed is True


def test_execute_cad3d_scene_closes_document_opened_by_failed_retry_attempt(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "retry-cad3d.dwg"
    target.write_bytes(b"")

    acad = _Acad()
    doc = _Document(str(target))

    calls = _install_retrying_open(
        monkeypatch,
        cad3d_executor,
        acad,
        doc,
    )

    monkeypatch.setattr(
        cad3d_executor,
        "_ensure_cad3d_presentation_layers",
        lambda _doc: None,
    )

    monkeypatch.setattr(
        cad3d_executor,
        "_execute_component_3d",
        lambda _doc, _component: 1,
    )

    scene = deepcopy(
        simple_3d_equipment_layout_scene()
    )

    scene["components"] = [
        {
            "component_type": "label_3d",
            "id": "LBL_RETRY",
            "text": "Retry ownership",
            "position": [0, 0, 0],
            "height": 100,
        }
    ]

    result = cad3d_executor.execute_cad3d_scene(
        scene,
        target_dwg_path=str(target),
        save=False,
        zoom_extents=False,
    )

    assert result["ok"] is True
    assert calls["count"] == 2
    assert doc.closed is True

    

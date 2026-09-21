from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from src.framework.cad3d import scene_store
from src.framework.cad3d.scene_schema import CAD3D_SCENE_SCHEMA_VERSION
from src.framework.cad3d.scene_store import (
    CAD3DSceneStore,
    CAD3DSceneStoreError,
    extract_scene_component_summary,
)


def _scene() -> dict:
    return {
        "schema_version": CAD3D_SCENE_SCHEMA_VERSION,
        "title": "Stored CAD3D Scene",
        "units": "mm",
        "assumptions": ["Test scene."],
        "components": [
            {
                "component_type": "vertical_tank_3d",
                "id": "T101",
                "tag": "T-101",
                "center": [0, 0, 900],
                "diameter": 900,
                "height": 1800,
            },
            {
                "component_type": "pipe_run_3d",
                "id": "P1",
                "points": [[0, 0, 500], [1000, 0, 500]],
                "diameter": 100,
            },
        ],
    }


def test_put_generated_scene_stores_valid_record() -> None:
    store = CAD3DSceneStore()

    record = store.put_generated_scene("tok1", "create 3d scene", _scene(), drawing_style="clean")

    assert record.token == "tok1"
    assert record.status == "generated"
    assert record.prompt == "create 3d scene"
    assert record.drawing_style == "clean"


def test_put_generated_scene_extracts_component_ids_and_types() -> None:
    store = CAD3DSceneStore()

    record = store.put_generated_scene("tok1", "prompt", _scene())

    assert record.component_ids == ["T101", "P1"]
    assert record.component_types == ["pipe_run_3d", "vertical_tank_3d"]


def test_get_returns_stored_record() -> None:
    store = CAD3DSceneStore()
    store.put_generated_scene("tok1", "prompt", _scene())

    assert store.get("tok1").token == "tok1"


def test_get_latest_returns_latest_record() -> None:
    store = CAD3DSceneStore()
    store.put_generated_scene("tok1", "first", _scene())
    store.put_generated_scene("tok2", "second", _scene())

    assert store.get_latest().token == "tok2"


def test_list_records_returns_newest_first() -> None:
    store = CAD3DSceneStore()
    store.put_generated_scene("tok1", "first", _scene())
    store.put_generated_scene("tok2", "second", _scene())

    assert [record.token for record in store.list_records()] == ["tok2", "tok1"]


def test_ordering_is_stable_for_records_written_in_the_same_clock_tick(tmp_path, monkeypatch) -> None:
    """`datetime.now()` resolves to roughly 15.6ms on Windows, so scenes
    written back-to-back used to receive byte-identical `updated_at` strings.
    Every ordering site sorts on that string, and Python's sort is stable, so
    a tie silently returned records oldest-first and `get_latest()` picked the
    wrong scene — which `/api/cad3d/edit` then edits when given no token.

    The clock is frozen rather than merely called quickly: relying on real
    timing made this pass by luck whenever the interpreter was slow enough
    between writes, which is exactly how the original bug hid."""
    frozen = datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone.utc)

    class _FrozenClock:
        @staticmethod
        def now(tz=None):
            return frozen

    monkeypatch.setattr(scene_store, "_LAST_TIMESTAMP", None)
    monkeypatch.setattr(scene_store, "datetime", _FrozenClock)

    store = CAD3DSceneStore(persist_dir=tmp_path)
    for token in ("tok1", "tok2", "tok3"):
        store.put_generated_scene(token, token, _scene())

    stamps = [store.get(token).updated_at for token in ("tok1", "tok2", "tok3")]
    assert len(set(stamps)) == 3, f"timestamps tied under a frozen clock: {stamps}"

    assert [record.token for record in store.list_records()] == ["tok3", "tok2", "tok1"]
    assert store.get_latest().token == "tok3"

    # The same ordering must survive a reload, so the tiebreak has to live in
    # the persisted value rather than in insertion order.
    reloaded = CAD3DSceneStore(persist_dir=tmp_path)
    assert [record.token for record in reloaded.list_records()] == ["tok3", "tok2", "tok1"]
    assert reloaded.get_latest().token == "tok3"


def test_mark_approved_updates_status_approved_when_result_ok() -> None:
    store = CAD3DSceneStore()
    store.put_generated_scene("tok1", "prompt", _scene())

    record = store.mark_approved("tok1", {"ok": True, "document_name": "Drawing1.dwg"})

    assert record.status == "approved"


def test_mark_approved_updates_status_failed_when_result_not_ok() -> None:
    store = CAD3DSceneStore()
    store.put_generated_scene("tok1", "prompt", _scene())

    record = store.mark_approved("tok1", {"ok": False, "document_name": "Drawing1.dwg"})

    assert record.status == "failed"


def test_mark_approved_stores_document_name() -> None:
    store = CAD3DSceneStore()
    store.put_generated_scene("tok1", "prompt", _scene())

    record = store.mark_approved("tok1", {"ok": True, "document_name": "Drawing1.dwg"})

    assert record.document_name == "Drawing1.dwg"
    assert record.approval_result["ok"] is True


def test_mark_approved_raises_for_missing_token() -> None:
    store = CAD3DSceneStore()

    with pytest.raises(CAD3DSceneStoreError):
        store.mark_approved("missing", {"ok": True})


def test_delete_removes_record() -> None:
    store = CAD3DSceneStore()
    store.put_generated_scene("tok1", "prompt", _scene())

    assert store.delete("tok1") is True
    with pytest.raises(CAD3DSceneStoreError):
        store.get("tok1")


def test_clear_removes_in_memory_records() -> None:
    store = CAD3DSceneStore()
    store.put_generated_scene("tok1", "prompt", _scene())

    store.clear()

    with pytest.raises(CAD3DSceneStoreError):
        store.get_latest()


def test_persistence_writes_json_file_when_persist_dir_is_set(tmp_path) -> None:
    store = CAD3DSceneStore(persist_dir=tmp_path)

    store.put_generated_scene("tok1", "prompt", _scene())

    path = tmp_path / "tok1.json"
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["token"] == "tok1"


def test_get_can_load_persisted_record_from_disk(tmp_path) -> None:
    store = CAD3DSceneStore(persist_dir=tmp_path)
    store.put_generated_scene("tok1", "prompt", _scene())
    fresh_store = CAD3DSceneStore(persist_dir=tmp_path)

    record = fresh_store.get("tok1")

    assert record.token == "tok1"
    assert record.scene["title"] == "Stored CAD3D Scene"


def test_invalid_scene_raises_store_error() -> None:
    store = CAD3DSceneStore()
    invalid_scene = _scene()
    invalid_scene["components"][0].pop("height")

    with pytest.raises(CAD3DSceneStoreError):
        store.put_generated_scene("tok1", "prompt", invalid_scene)


def test_extract_scene_component_summary_returns_counts_ids_and_types() -> None:
    summary = extract_scene_component_summary(_scene())

    assert summary["component_count"] == 2
    assert summary["component_ids"] == ["T101", "P1"]
    assert summary["component_types"] == ["pipe_run_3d", "vertical_tank_3d"]
    assert summary["type_counts"] == {
        "pipe_run_3d": 1,
        "vertical_tank_3d": 1,
    }


def test_get_old_record_after_restart_does_not_hijack_latest(
    tmp_path,
) -> None:
    store = CAD3DSceneStore(
        persist_dir=tmp_path
    )

    store.put_generated_scene(
        "A",
        "first",
        _scene(),
    )

    store.put_generated_scene(
        "B",
        "second",
        _scene(),
    )

    restarted = CAD3DSceneStore(
        persist_dir=tmp_path
    )

    assert restarted.get("A").token == "A"

    latest = restarted.get_latest()
    listed_latest = (
        restarted.list_records()[0]
    )

    assert latest.token == "B"
    assert (
        latest.token
        == listed_latest.token
    )

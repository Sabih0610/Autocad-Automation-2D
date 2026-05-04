from __future__ import annotations

import pytest

from src.framework.cad3d.component_examples import routed_tank_pump_separator_scene_data
from src.framework.cad3d.scene_editor import (
    CAD3DComponentNotFoundError,
    CAD3DSceneEditError,
    add_component_to_scene,
    apply_cad3d_edit_plan,
    delete_component_from_scene,
    find_component_index,
    get_component,
    move_component,
    summarize_scene_edit,
    update_component_fields,
)
from src.framework.cad3d.scene_schema import validate_cad3d_scene


def _scene() -> dict:
    return routed_tank_pump_separator_scene_data()


def _plan(operation: dict) -> dict:
    return {
        "schema_version": "1.0",
        "edit_intent": "Edit scene.",
        "summary": "Edit scene.",
        "operations": [operation],
        "metadata": {},
    }


def test_find_component_index_finds_existing_component() -> None:
    assert find_component_index(_scene(), "P101") == 2


def test_find_component_index_raises_for_missing_component() -> None:
    with pytest.raises(CAD3DComponentNotFoundError):
        find_component_index(_scene(), "MISSING")


def test_move_component_changes_center_by_delta() -> None:
    component = get_component(_scene(), "P101")

    moved = move_component(component, delta=[1000, 0, 0])

    assert moved["center"] == [1300.0, 0.0, 250.0]


def test_move_component_sets_new_center() -> None:
    component = get_component(_scene(), "P101")

    moved = move_component(component, new_center=[1, 2, 3])

    assert moved["center"] == [1.0, 2.0, 3.0]


def test_move_component_moves_pipe_run_points_by_delta() -> None:
    component = {
        "component_type": "pipe_run_3d",
        "id": "P1",
        "points": [[0, 0, 0], [100, 0, 0]],
        "diameter": 50,
    }

    moved = move_component(component, delta=[10, 20, 30])

    assert moved["points"] == [[10.0, 20.0, 30.0], [110.0, 20.0, 30.0]]


def test_update_component_fields_updates_height_and_length() -> None:
    component = get_component(_scene(), "P101")

    updated = update_component_fields(component, {"height": 600, "length": 900})

    assert updated["height"] == 600
    assert updated["length"] == 900


def test_update_component_fields_rejects_id_and_component_type() -> None:
    component = get_component(_scene(), "P101")

    with pytest.raises(CAD3DSceneEditError):
        update_component_fields(component, {"id": "BAD"})
    with pytest.raises(CAD3DSceneEditError):
        update_component_fields(component, {"component_type": "box_3d"})


def test_add_component_to_scene_adds_valid_component() -> None:
    scene = _scene()
    component = {
        "component_type": "box_3d",
        "id": "B101",
        "center": [0, 0, 0],
        "length": 100,
        "width": 100,
        "height": 100,
    }

    edited = add_component_to_scene(scene, component)

    assert get_component(edited, "B101")["component_type"] == "box_3d"
    assert validate_cad3d_scene(edited) == []


def test_add_component_to_scene_rejects_duplicate_id() -> None:
    with pytest.raises(CAD3DSceneEditError):
        add_component_to_scene(_scene(), get_component(_scene(), "P101"))


def test_delete_component_from_scene_removes_component() -> None:
    edited = delete_component_from_scene(_scene(), "P101")

    with pytest.raises(CAD3DComponentNotFoundError):
        get_component(edited, "P101")


def test_delete_component_from_scene_removes_connected_pipe_connection() -> None:
    edited = delete_component_from_scene(_scene(), "P101")
    component_ids = {component["id"] for component in edited["components"]}

    assert "PIPE_T101_P101" not in component_ids
    assert "PIPE_P101_V201" not in component_ids


def test_apply_cad3d_edit_plan_applies_move_operation() -> None:
    edited = apply_cad3d_edit_plan(
        _scene(),
        _plan({"operation_type": "move_component", "component_id": "P101", "delta": [1000, 0, 0]}),
    )

    assert get_component(edited, "P101")["center"] == [1300.0, 0.0, 250.0]


def test_apply_cad3d_edit_plan_applies_multiple_operations() -> None:
    plan = {
        "schema_version": "1.0",
        "edit_intent": "Move pump and set tank height.",
        "summary": "Move P101 and resize T101.",
        "operations": [
            {"operation_type": "move_component", "component_id": "P101", "delta": [1000, 0, 0]},
            {"operation_type": "update_component", "component_id": "T101", "updates": {"height": 6000}},
        ],
    }

    edited = apply_cad3d_edit_plan(_scene(), plan)

    assert get_component(edited, "P101")["center"] == [1300.0, 0.0, 250.0]
    assert get_component(edited, "T101")["height"] == 6000.0


def test_apply_cad3d_edit_plan_validates_final_scene() -> None:
    edited = apply_cad3d_edit_plan(
        _scene(),
        _plan({"operation_type": "update_component", "component_id": "T101", "updates": {"height": 6000}}),
    )

    assert validate_cad3d_scene(edited) == []


def test_apply_cad3d_edit_plan_fails_if_pipe_connection_references_missing_component() -> None:
    plan = _plan(
        {
            "operation_type": "update_component",
            "component_id": "PIPE_T101_P101",
            "updates": {"to_port": "MISSING.suction"},
        }
    )

    with pytest.raises(CAD3DSceneEditError):
        apply_cad3d_edit_plan(_scene(), plan)


def test_summarize_scene_edit_returns_added_removed_unchanged_ids() -> None:
    original = _scene()
    edited = delete_component_from_scene(original, "P101")

    summary = summarize_scene_edit(original, edited)

    assert summary["original_component_count"] == 9
    assert summary["edited_component_count"] == 6
    assert "P101" in summary["removed_component_ids"]
    assert "T101" in summary["unchanged_component_ids"]

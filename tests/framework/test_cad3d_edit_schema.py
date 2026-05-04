from __future__ import annotations

import pytest

from src.framework.cad3d.edit_schema import (
    CAD3DEditValidationError,
    is_valid_coord3,
    validate_cad3d_edit_plan,
)


def _base_plan(operation: dict) -> dict:
    return {
        "schema_version": "1.0",
        "edit_intent": "Edit scene.",
        "summary": "Edit scene.",
        "operations": [operation],
        "metadata": {},
    }


def test_valid_move_component_with_delta_passes() -> None:
    plan = validate_cad3d_edit_plan(
        _base_plan({"operation_type": "move_component", "component_id": "P101", "delta": [1, 2, 3]})
    )

    assert plan["operations"][0]["delta"] == [1.0, 2.0, 3.0]


def test_valid_move_component_with_new_center_passes() -> None:
    plan = validate_cad3d_edit_plan(
        _base_plan({"operation_type": "move_component", "component_id": "P101", "new_center": [1, 2, 3]})
    )

    assert plan["operations"][0]["new_center"] == [1.0, 2.0, 3.0]


def test_move_component_without_delta_or_new_center_fails() -> None:
    with pytest.raises(CAD3DEditValidationError):
        validate_cad3d_edit_plan(_base_plan({"operation_type": "move_component", "component_id": "P101"}))


def test_valid_update_component_passes() -> None:
    plan = validate_cad3d_edit_plan(
        _base_plan({"operation_type": "update_component", "component_id": "T101", "updates": {"height": 6000}})
    )

    assert plan["operations"][0]["updates"]["height"] == 6000.0


def test_update_component_cannot_update_id() -> None:
    with pytest.raises(CAD3DEditValidationError):
        validate_cad3d_edit_plan(
            _base_plan({"operation_type": "update_component", "component_id": "T101", "updates": {"id": "BAD"}})
        )


def test_update_component_cannot_update_component_type() -> None:
    with pytest.raises(CAD3DEditValidationError):
        validate_cad3d_edit_plan(
            _base_plan(
                {
                    "operation_type": "update_component",
                    "component_id": "T101",
                    "updates": {"component_type": "box_3d"},
                }
            )
        )


def test_update_component_with_empty_updates_fails() -> None:
    with pytest.raises(CAD3DEditValidationError):
        validate_cad3d_edit_plan(
            _base_plan({"operation_type": "update_component", "component_id": "T101", "updates": {}})
        )


def test_valid_add_component_passes() -> None:
    component = {
        "component_type": "box_3d",
        "id": "B101",
        "center": [0, 0, 0],
        "length": 100,
        "width": 100,
        "height": 100,
    }

    plan = validate_cad3d_edit_plan(_base_plan({"operation_type": "add_component", "component": component}))

    assert plan["operations"][0]["component"]["id"] == "B101"


def test_valid_delete_component_passes() -> None:
    plan = validate_cad3d_edit_plan(
        _base_plan({"operation_type": "delete_component", "component_id": "P101"})
    )

    assert plan["operations"][0]["component_id"] == "P101"


def test_operations_list_required() -> None:
    with pytest.raises(CAD3DEditValidationError):
        validate_cad3d_edit_plan(
            {"schema_version": "1.0", "edit_intent": "Edit", "summary": "Edit", "operations": []}
        )


def test_unknown_operation_type_fails() -> None:
    with pytest.raises(CAD3DEditValidationError):
        validate_cad3d_edit_plan(_base_plan({"operation_type": "rotate_component", "component_id": "P101"}))


def test_coordinate_arrays_must_be_3d() -> None:
    assert is_valid_coord3([1, 2, 3]) is True
    assert is_valid_coord3([1, 2]) is False
    with pytest.raises(CAD3DEditValidationError):
        validate_cad3d_edit_plan(
            _base_plan({"operation_type": "move_component", "component_id": "P101", "delta": [1, 2]})
        )


def test_normalize_converts_numeric_strings_to_floats() -> None:
    plan = validate_cad3d_edit_plan(
        _base_plan(
            {
                "operation_type": "move_component",
                "component_id": "P101",
                "delta": ["1000", "0", "0"],
            }
        )
    )

    assert plan["operations"][0]["delta"] == [1000.0, 0.0, 0.0]

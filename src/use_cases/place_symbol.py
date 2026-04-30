"""
Phase 5 symbol placer executor.

This file takes a structured JSON-like Python dictionary and inserts
a symbol block into the active AutoCAD drawing.

Important:
- This executor does NOT call AI.
- It only executes already-planned JSON.
- The AI planner calls this executor from ai_place_symbol.py.

Run dry-run:
    python -m src.use_cases.place_symbol

Run actual insert:
    python -m src.use_cases.place_symbol --execute

AutoCAD must be open with symbol_test.dwg active.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from typing import Any, Callable, Dict, List

import pythoncom
import pywintypes
import win32com.client


RPC_E_CALL_REJECTED = -2147418111

VALID_BLOCKS = {
    "GATE_VALVE",
    "CHECK_VALVE",
    "CONTROL_VALVE",
    "PUMP",
    "VESSEL",
    "INSTRUMENT_BUBBLE",
}


TEST_SPEC = {
    "task_type": "place_symbol",
    "block_name": "GATE_VALVE",
    "insertion_point": {
        "x": 100,
        "y": 100,
        "z": 0,
    },
    "rotation_degrees": 0,
    "scale": 1,
    "layer": "P-VALVES",
    "attributes": {
        "TAG": "V-500",
        "SIZE": "6 inch",
        "SERVICE": "process water",
    },
}


def point(x: float, y: float, z: float = 0.0):
    """AutoCAD COM 3D point."""
    return win32com.client.VARIANT(
        pythoncom.VT_ARRAY | pythoncom.VT_R8,
        [float(x), float(y), float(z)],
    )


def is_autocad_busy_error(error: Exception) -> bool:
    """Detect AutoCAD RPC busy/rejected COM errors."""
    if isinstance(error, pywintypes.com_error):
        try:
            return int(error.hresult) == RPC_E_CALL_REJECTED
        except Exception:
            pass

    error_text = str(error).lower()
    return (
        "call was rejected by callee" in error_text
        or "rpc_e_call_rejected" in error_text
        or str(RPC_E_CALL_REJECTED) in error_text
    )


def com_retry(
    operation: Callable[[], Any],
    description: str,
    attempts: int = 5,
    delay_seconds: float = 0.5,
):
    """
    Retry a COM operation if AutoCAD is temporarily busy.

    This is important because AutoCAD COM is single-threaded and can reject calls
    while it is regenerating, zooming, updating attributes, or processing UI state.
    """
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as e:
            last_error = e

            if not is_autocad_busy_error(e):
                raise

            if attempt >= attempts:
                break

            print(
                f"AutoCAD busy during {description}. "
                f"Retrying {attempt}/{attempts - 1}..."
            )
            time.sleep(delay_seconds)

    raise last_error


def safe_com_get(obj, property_name: str, default=None):
    """Safely read a COM property with retry."""
    try:
        return com_retry(
            lambda: getattr(obj, property_name),
            f"reading {property_name}",
            attempts=5,
            delay_seconds=0.4,
        )
    except Exception:
        return default


def connect_to_autocad():
    """Connect to running AutoCAD and return app + active document."""
    try:
        acad = win32com.client.GetActiveObject("AutoCAD.Application")
    except Exception as e:
        print("ERROR: AutoCAD is not running.")
        print("Open AutoCAD with symbol_test.dwg active, then try again.")
        print(f"Details: {type(e).__name__}: {e}")
        sys.exit(1)

    try:
        doc = acad.ActiveDocument
        _ = doc.Name
    except Exception as e:
        print("ERROR: No active drawing found in AutoCAD.")
        print("Open symbol_test.dwg, then try again.")
        print(f"Details: {type(e).__name__}: {e}")
        sys.exit(1)

    return acad, doc


def block_exists(doc, block_name: str) -> bool:
    """Return True if a block definition exists in the drawing."""
    try:
        _ = doc.Blocks.Item(block_name)
        return True
    except Exception:
        return False


def layer_exists(doc, layer_name: str) -> bool:
    """Return True if a layer exists in the drawing."""
    try:
        _ = doc.Layers.Item(layer_name)
        return True
    except Exception:
        return False


def ensure_layer(doc, layer_name: str):
    """Create layer if missing and return layer object."""
    if layer_exists(doc, layer_name):
        return doc.Layers.Item(layer_name)

    print(f"Layer does not exist. Creating layer: {layer_name}")
    return com_retry(
        lambda: doc.Layers.Add(layer_name),
        f"creating layer {layer_name}",
        attempts=5,
        delay_seconds=0.5,
    )


def almost_equal(a: float, b: float, tolerance: float = 0.001) -> bool:
    """Compare floats with small tolerance."""
    return abs(float(a) - float(b)) <= tolerance


def normalize_point(raw_point) -> List[float]:
    """Convert AutoCAD insertion point to a plain Python list."""
    if raw_point is None:
        return []

    try:
        values = list(raw_point)
    except Exception:
        return []

    if len(values) < 3:
        return []

    try:
        return [float(values[0]), float(values[1]), float(values[2])]
    except Exception:
        return []


def get_block_name(block_ref) -> str:
    """Get effective block name safely."""
    effective_name = safe_com_get(block_ref, "EffectiveName", None)
    if effective_name:
        return str(effective_name)

    name = safe_com_get(block_ref, "Name", "")
    return str(name) if name else ""


def get_block_attributes(block_ref) -> Dict[str, str]:
    """Read attributes from a block reference."""
    values: Dict[str, str] = {}

    try:
        attributes = com_retry(
            lambda: block_ref.GetAttributes(),
            "reading block attributes",
            attempts=5,
            delay_seconds=0.4,
        )
    except Exception:
        return values

    for att in attributes:
        try:
            tag = safe_com_get(att, "TagString", "")
            value = safe_com_get(att, "TextString", "")

            tag = str(tag).strip()
            value = str(value)

            if tag:
                values[tag] = value
        except Exception:
            continue

    return values


def get_block_handle(block_ref) -> str:
    """Read block handle with retry."""
    handle = safe_com_get(block_ref, "Handle", "")

    if handle:
        return str(handle)

    return "UNAVAILABLE"


def validate_symbol_spec(doc, spec: Dict[str, Any]) -> List[str]:
    """
    Validate symbol placement spec before touching AutoCAD.

    Returns:
        list of error messages. Empty list means valid.
    """
    errors: List[str] = []

    if spec.get("task_type") != "place_symbol":
        errors.append("task_type must be 'place_symbol'")

    block_name = spec.get("block_name")
    if not block_name:
        errors.append("block_name is required")
    elif block_name not in VALID_BLOCKS:
        errors.append(f"Unsupported block_name: {block_name}")
    elif not block_exists(doc, block_name):
        errors.append(f"Block definition does not exist in drawing: {block_name}")

    insertion_point = spec.get("insertion_point")
    if not isinstance(insertion_point, dict):
        errors.append("insertion_point must be an object")
    else:
        for key in ["x", "y", "z"]:
            if key not in insertion_point:
                errors.append(f"insertion_point.{key} is required")
            else:
                try:
                    float(insertion_point[key])
                except Exception:
                    errors.append(f"insertion_point.{key} must be a number")

    try:
        float(spec.get("rotation_degrees", 0))
    except Exception:
        errors.append("rotation_degrees must be a number")

    try:
        scale = float(spec.get("scale", 1))
        if scale <= 0:
            errors.append("scale must be greater than 0")
    except Exception:
        errors.append("scale must be a number")

    layer = spec.get("layer")
    if not isinstance(layer, str) or not layer.strip():
        errors.append("layer must be a non-empty string")

    attributes = spec.get("attributes")
    if not isinstance(attributes, dict):
        errors.append("attributes must be an object")
    else:
        for tag in ["TAG", "SIZE", "SERVICE"]:
            value = attributes.get(tag)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"attributes.{tag} must be a non-empty string")

    return errors


def set_block_attributes(block_ref, values: Dict[str, str]) -> List[str]:
    """
    Set attributes on inserted block reference.

    Returns:
        warnings for missing attributes.
    """
    warnings: List[str] = []

    try:
        attributes = com_retry(
            lambda: block_ref.GetAttributes(),
            "reading block attributes for writing",
            attempts=5,
            delay_seconds=0.4,
        )
    except Exception as e:
        warnings.append(f"Could not read block attributes: {type(e).__name__}: {e}")
        return warnings

    found_tags = set()

    for att in attributes:
        tag = safe_com_get(att, "TagString", "")
        tag = str(tag).strip()
        found_tags.add(tag)

        if tag in values:
            try:
                att.TextString = values[tag]
            except Exception as e:
                if is_autocad_busy_error(e):
                    com_retry(
                        lambda: setattr(att, "TextString", values[tag]),
                        f"setting attribute {tag}",
                        attempts=5,
                        delay_seconds=0.4,
                    )
                else:
                    warnings.append(f"Could not set attribute {tag}: {type(e).__name__}: {e}")

            try:
                att.Update()
            except Exception:
                pass

    for expected_tag in values:
        if expected_tag not in found_tags:
            warnings.append(f"Expected attribute not found on block: {expected_tag}")

    try:
        block_ref.Update()
    except Exception:
        pass

    return warnings


def readback_from_block_ref(block_ref, handle: str, source: str) -> Dict[str, Any]:
    """
    Read an inserted block reference directly from the COM block object.

    This is more reliable immediately after InsertBlock than HandleToObject.
    """
    raw_insertion_point = safe_com_get(block_ref, "InsertionPoint", None)
    insertion_point = normalize_point(raw_insertion_point)

    raw_layer = safe_com_get(block_ref, "Layer", "")
    layer = str(raw_layer) if raw_layer is not None else ""

    raw_rotation = safe_com_get(block_ref, "Rotation", None)
    try:
        rotation_degrees = math.degrees(float(raw_rotation))
    except Exception:
        rotation_degrees = None

    raw_x_scale = safe_com_get(block_ref, "XScaleFactor", None)
    raw_y_scale = safe_com_get(block_ref, "YScaleFactor", None)
    raw_z_scale = safe_com_get(block_ref, "ZScaleFactor", None)

    try:
        x_scale = float(raw_x_scale)
    except Exception:
        x_scale = None

    try:
        y_scale = float(raw_y_scale)
    except Exception:
        y_scale = None

    try:
        z_scale = float(raw_z_scale)
    except Exception:
        z_scale = None

    object_name = safe_com_get(block_ref, "ObjectName", "")
    object_name = str(object_name) if object_name is not None else ""

    return {
        "source": source,
        "handle": handle,
        "object_name": object_name,
        "block_name": get_block_name(block_ref),
        "layer": layer,
        "insertion_point": insertion_point,
        "rotation_degrees": rotation_degrees,
        "scale": {
            "x": x_scale,
            "y": y_scale,
            "z": z_scale,
        },
        "attributes": get_block_attributes(block_ref),
    }


def readback_from_handle(doc, handle: str) -> Dict[str, Any]:
    """Read inserted AutoCAD object back by handle."""
    obj = com_retry(
        lambda: doc.HandleToObject(handle),
        f"HandleToObject({handle})",
        attempts=5,
        delay_seconds=0.5,
    )
    return readback_from_block_ref(obj, handle, source="handle_lookup")


def evaluate_readback(
    readback: Dict[str, Any],
    expected_spec: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Compare readback data with expected spec.
    """
    mismatches: List[str] = []

    expected_block = expected_spec["block_name"]
    actual_block = readback.get("block_name")

    if actual_block != expected_block:
        mismatches.append(f"block_name mismatch: expected {expected_block}, got {actual_block}")

    expected_layer = expected_spec["layer"].strip()
    actual_layer = readback.get("layer")

    if actual_layer != expected_layer:
        mismatches.append(f"layer mismatch: expected {expected_layer}, got {actual_layer}")

    expected_point = expected_spec["insertion_point"]
    actual_point = readback.get("insertion_point", [])

    if len(actual_point) >= 3:
        if not almost_equal(actual_point[0], expected_point["x"]):
            mismatches.append(f"x mismatch: expected {expected_point['x']}, got {actual_point[0]}")
        if not almost_equal(actual_point[1], expected_point["y"]):
            mismatches.append(f"y mismatch: expected {expected_point['y']}, got {actual_point[1]}")
        if not almost_equal(actual_point[2], expected_point["z"]):
            mismatches.append(f"z mismatch: expected {expected_point['z']}, got {actual_point[2]}")
    else:
        mismatches.append("Could not verify insertion_point")

    expected_rotation = float(expected_spec.get("rotation_degrees", 0))
    actual_rotation = readback.get("rotation_degrees")

    if actual_rotation is None:
        mismatches.append("Could not verify rotation")
    elif not almost_equal(actual_rotation, expected_rotation):
        mismatches.append(
            f"rotation mismatch: expected {expected_rotation}, got {actual_rotation}"
        )

    expected_scale = float(expected_spec.get("scale", 1))
    actual_scale = readback.get("scale", {})

    for axis in ["x", "y", "z"]:
        axis_value = actual_scale.get(axis)
        if axis_value is None:
            mismatches.append(f"Could not verify {axis} scale")
        elif not almost_equal(axis_value, expected_scale):
            mismatches.append(
                f"{axis} scale mismatch: expected {expected_scale}, got {axis_value}"
            )

    expected_attributes = expected_spec["attributes"]
    actual_attributes = readback.get("attributes", {})

    for tag, expected_value in expected_attributes.items():
        actual_value = actual_attributes.get(tag)

        if actual_value != expected_value:
            mismatches.append(
                f"attribute {tag} mismatch: expected {expected_value}, got {actual_value}"
            )

    return {
        "ok": len(mismatches) == 0,
        "readback": readback,
        "mismatches": mismatches,
    }


def verify_inserted_symbol(
    doc,
    handle: str,
    expected_spec: Dict[str, Any],
    block_ref=None,
) -> Dict[str, Any]:
    """
    Verify inserted block.

    Verification strategy:
    1. First use the fresh block reference returned by InsertBlock.
    2. If that fails and a handle exists, fall back to HandleToObject.
    """
    attempts: List[Dict[str, Any]] = []

    if block_ref is not None:
        try:
            direct_readback = readback_from_block_ref(
                block_ref=block_ref,
                handle=handle,
                source="insert_return_proxy",
            )
            direct_result = evaluate_readback(direct_readback, expected_spec)
            attempts.append(direct_result)

            if direct_result["ok"]:
                return {
                    "ok": True,
                    "readback": direct_result["readback"],
                    "mismatches": [],
                    "attempts": attempts,
                }

        except Exception as e:
            attempts.append(
                {
                    "ok": False,
                    "readback": {
                        "source": "insert_return_proxy",
                        "error": f"{type(e).__name__}: {e}",
                    },
                    "mismatches": [f"insert_return_proxy failed: {type(e).__name__}: {e}"],
                }
            )

    if handle and handle != "UNAVAILABLE":
        try:
            handle_readback = readback_from_handle(doc, handle)
            handle_result = evaluate_readback(handle_readback, expected_spec)
            attempts.append(handle_result)

            if handle_result["ok"]:
                return {
                    "ok": True,
                    "readback": handle_result["readback"],
                    "mismatches": [],
                    "attempts": attempts,
                }

        except Exception as e:
            attempts.append(
                {
                    "ok": False,
                    "readback": {
                        "source": "handle_lookup",
                        "error": f"{type(e).__name__}: {e}",
                    },
                    "mismatches": [f"handle_lookup failed: {type(e).__name__}: {e}"],
                }
            )

    combined_mismatches: List[str] = []

    for attempt in attempts:
        for mismatch in attempt.get("mismatches", []):
            if mismatch not in combined_mismatches:
                combined_mismatches.append(mismatch)

    best_readback = attempts[0].get("readback", {}) if attempts else {}

    return {
        "ok": False,
        "readback": best_readback,
        "mismatches": combined_mismatches,
        "attempts": attempts,
    }


def insert_symbol(doc, spec: Dict[str, Any], dry_run: bool = True) -> Dict[str, Any]:
    """
    Insert a symbol block into AutoCAD from a validated JSON-like spec.
    """
    validation_errors = validate_symbol_spec(doc, spec)

    if validation_errors:
        return {
            "ok": False,
            "dry_run": dry_run,
            "inserted": False,
            "verified": False,
            "errors": validation_errors,
            "warnings": [],
        }

    block_name = spec["block_name"]
    insertion_point = spec["insertion_point"]

    x = float(insertion_point["x"])
    y = float(insertion_point["y"])
    z = float(insertion_point["z"])

    rotation_degrees = float(spec.get("rotation_degrees", 0))
    rotation_radians = math.radians(rotation_degrees)

    scale = float(spec.get("scale", 1))
    layer_name = spec["layer"].strip()
    attributes = spec["attributes"]

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "inserted": False,
            "verified": False,
            "message": "Dry run passed. No AutoCAD changes made.",
            "planned_insert": {
                "block_name": block_name,
                "x": x,
                "y": y,
                "z": z,
                "rotation_degrees": rotation_degrees,
                "scale": scale,
                "layer": layer_name,
                "attributes": attributes,
            },
            "errors": [],
            "warnings": [],
        }

    layer_obj = ensure_layer(doc, layer_name)
    model = doc.ModelSpace

    try:
        old_active_layer = doc.ActiveLayer
    except Exception:
        old_active_layer = None

    com_retry(
        lambda: setattr(doc, "ActiveLayer", layer_obj),
        f"setting active layer {layer_name}",
        attempts=5,
        delay_seconds=0.5,
    )

    block_ref = com_retry(
        lambda: model.InsertBlock(
            point(x, y, z),
            block_name,
            scale,
            scale,
            scale,
            rotation_radians,
        ),
        f"inserting block {block_name}",
        attempts=5,
        delay_seconds=0.5,
    )

    # ActiveLayer is the primary method. This is only a reinforcement.
    try:
        block_ref.Layer = layer_name
    except Exception:
        pass

    warnings = set_block_attributes(block_ref, attributes)

    try:
        block_ref.Update()
    except Exception:
        pass

    try:
        doc.Regen(1)
    except Exception:
        pass

    time.sleep(0.5)

    handle = get_block_handle(block_ref)

    verification = verify_inserted_symbol(
        doc=doc,
        handle=handle,
        expected_spec=spec,
        block_ref=block_ref,
    )

    if old_active_layer is not None:
        try:
            doc.ActiveLayer = old_active_layer
        except Exception:
            pass

    result_ok = verification["ok"]

    return {
        "ok": result_ok,
        "dry_run": False,
        "inserted": True,
        "verified": verification["ok"],
        "message": (
            "Symbol inserted and verified successfully."
            if verification["ok"]
            else "Symbol inserted, but verification found mismatches."
        ),
        "handle": handle,
        "block_name": block_name,
        "layer": layer_name,
        "attributes": attributes,
        "verification": verification,
        "errors": [] if result_ok else verification["mismatches"],
        "warnings": warnings,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually insert the symbol. Without this flag, script runs dry-run only.",
    )
    args = parser.parse_args()

    dry_run = not args.execute

    acad, doc = connect_to_autocad()

    print(f"Connected to: {acad.Caption}")
    print(f"Active drawing: {doc.Name}")

    print("\nInput symbol spec:")
    print(TEST_SPEC)

    result = insert_symbol(
        doc=doc,
        spec=TEST_SPEC,
        dry_run=dry_run,
    )

    print("\nResult:")
    print(result)

    if result["ok"] and result.get("inserted"):
        acad.ZoomExtents()
        time.sleep(0.3)
        print("\nInserted symbol should now be visible in AutoCAD.")


if __name__ == "__main__":
    main()
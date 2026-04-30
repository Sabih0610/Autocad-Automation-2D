"""
Setup test symbol blocks for Phase 5.

This creates simple AutoCAD block definitions for testing the AI symbol placer.

Blocks created:
- GATE_VALVE
- CHECK_VALVE
- CONTROL_VALVE
- PUMP
- VESSEL
- INSTRUMENT_BUBBLE

Each block includes attributes:
- TAG
- SIZE
- SERVICE

Run from project root:
    python -m src.use_cases.setup_symbol_test_blocks

AutoCAD must be open with a drawing active.
"""

from __future__ import annotations

import math
import sys
import time

import pythoncom
import win32com.client


SYMBOL_BLOCKS = [
    "GATE_VALVE",
    "CHECK_VALVE",
    "CONTROL_VALVE",
    "PUMP",
    "VESSEL",
    "INSTRUMENT_BUBBLE",
]


PREVIEW_LAYER = "P-SYMBOL-TEST"


def point(x: float, y: float, z: float = 0.0):
    """AutoCAD COM 3D point."""
    return win32com.client.VARIANT(
        pythoncom.VT_ARRAY | pythoncom.VT_R8,
        [float(x), float(y), float(z)],
    )


def connect_to_autocad():
    """Connect to running AutoCAD and return active document."""
    try:
        acad = win32com.client.GetActiveObject("AutoCAD.Application")
    except Exception as e:
        print("ERROR: AutoCAD is not running.")
        print("Open AutoCAD with a drawing active, then try again.")
        print(f"Details: {type(e).__name__}: {e}")
        sys.exit(1)

    try:
        doc = acad.ActiveDocument
        _ = doc.Name
    except Exception as e:
        print("ERROR: No active drawing found in AutoCAD.")
        print("Create or open a drawing, then try again.")
        print(f"Details: {type(e).__name__}: {e}")
        sys.exit(1)

    return acad, doc


def block_exists(doc, block_name: str) -> bool:
    """Check whether a block definition exists."""
    try:
        _ = doc.Blocks.Item(block_name)
        return True
    except Exception:
        return False


def layer_exists(doc, layer_name: str) -> bool:
    """Check whether a layer exists."""
    try:
        _ = doc.Layers.Item(layer_name)
        return True
    except Exception:
        return False


def ensure_layer(doc, layer_name: str):
    """Create layer if missing and return the layer object."""
    if not layer_exists(doc, layer_name):
        return doc.Layers.Add(layer_name)

    return doc.Layers.Item(layer_name)


def add_common_attributes(block):
    """Add TAG, SIZE, SERVICE attributes to a block definition."""
    block.AddAttribute(2.5, 0, "Tag", point(-10, -10), "TAG", "TAG")
    block.AddAttribute(2.5, 0, "Size", point(-10, -14), "SIZE", "SIZE")
    block.AddAttribute(2.5, 0, "Service", point(-10, -18), "SERVICE", "SERVICE")


def create_gate_valve(doc):
    """Create simple gate valve symbol."""
    name = "GATE_VALVE"

    if block_exists(doc, name):
        print(f"Block already exists, skipping: {name}")
        return

    block = doc.Blocks.Add(point(0, 0), name)

    block.AddLine(point(-10, 5), point(0, 0))
    block.AddLine(point(-10, -5), point(0, 0))
    block.AddLine(point(-10, 5), point(-10, -5))

    block.AddLine(point(10, 5), point(0, 0))
    block.AddLine(point(10, -5), point(0, 0))
    block.AddLine(point(10, 5), point(10, -5))

    block.AddLine(point(-18, 0), point(-10, 0))
    block.AddLine(point(10, 0), point(18, 0))

    add_common_attributes(block)
    print(f"Created block: {name}")


def create_check_valve(doc):
    """Create simple check valve symbol."""
    name = "CHECK_VALVE"

    if block_exists(doc, name):
        print(f"Block already exists, skipping: {name}")
        return

    block = doc.Blocks.Add(point(0, 0), name)

    block.AddLine(point(-10, -6), point(-10, 6))
    block.AddLine(point(-10, 6), point(5, 0))
    block.AddLine(point(5, 0), point(-10, -6))
    block.AddLine(point(8, -7), point(8, 7))

    block.AddLine(point(-18, 0), point(-10, 0))
    block.AddLine(point(8, 0), point(18, 0))

    add_common_attributes(block)
    print(f"Created block: {name}")


def create_control_valve(doc):
    """Create simple control valve symbol."""
    name = "CONTROL_VALVE"

    if block_exists(doc, name):
        print(f"Block already exists, skipping: {name}")
        return

    block = doc.Blocks.Add(point(0, 0), name)

    block.AddLine(point(-10, 5), point(0, 0))
    block.AddLine(point(-10, -5), point(0, 0))
    block.AddLine(point(-10, 5), point(-10, -5))

    block.AddLine(point(10, 5), point(0, 0))
    block.AddLine(point(10, -5), point(0, 0))
    block.AddLine(point(10, 5), point(10, -5))

    block.AddLine(point(0, 0), point(0, 12))
    block.AddCircle(point(0, 18), 6)

    block.AddLine(point(-18, 0), point(-10, 0))
    block.AddLine(point(10, 0), point(18, 0))

    add_common_attributes(block)
    print(f"Created block: {name}")


def create_pump(doc):
    """Create simple pump symbol."""
    name = "PUMP"

    if block_exists(doc, name):
        print(f"Block already exists, skipping: {name}")
        return

    block = doc.Blocks.Add(point(0, 0), name)

    block.AddCircle(point(0, 0), 10)
    block.AddLine(point(-18, 0), point(-10, 0))
    block.AddLine(point(10, 0), point(18, 0))
    block.AddLine(point(-4, -4), point(5, 0))
    block.AddLine(point(5, 0), point(-4, 4))

    add_common_attributes(block)
    print(f"Created block: {name}")


def create_vessel(doc):
    """Create simple vessel symbol."""
    name = "VESSEL"

    if block_exists(doc, name):
        print(f"Block already exists, skipping: {name}")
        return

    block = doc.Blocks.Add(point(0, 0), name)

    block.AddLine(point(-8, -15), point(-8, 15))
    block.AddLine(point(8, -15), point(8, 15))
    block.AddArc(point(0, 15), 8, 0, math.pi)
    block.AddArc(point(0, -15), 8, math.pi, 2 * math.pi)

    add_common_attributes(block)
    print(f"Created block: {name}")


def create_instrument_bubble(doc):
    """Create simple instrument bubble."""
    name = "INSTRUMENT_BUBBLE"

    if block_exists(doc, name):
        print(f"Block already exists, skipping: {name}")
        return

    block = doc.Blocks.Add(point(0, 0), name)

    block.AddCircle(point(0, 0), 10)
    block.AddLine(point(-7, 0), point(7, 0))

    add_common_attributes(block)
    print(f"Created block: {name}")


def set_block_attributes(block_ref, values: dict):
    """Set attributes on an inserted block reference."""
    try:
        attributes = block_ref.GetAttributes()
    except Exception:
        return

    for att in attributes:
        tag = att.TagString.strip()
        if tag in values:
            att.TextString = values[tag]


def clear_old_preview_symbols(doc):
    """
    Delete old preview symbols from the preview layer.

    This prevents repeated runs from stacking preview rows on top of each other.
    """
    model = doc.ModelSpace
    deleted_count = 0

    for entity in list(model):
        try:
            object_name = entity.ObjectName
        except Exception:
            continue

        if object_name != "AcDbBlockReference":
            continue

        try:
            layer = entity.Layer
        except Exception:
            continue

        if layer != PREVIEW_LAYER:
            continue

        try:
            block_name = entity.EffectiveName
        except Exception:
            try:
                block_name = entity.Name
            except Exception:
                continue

        if block_name in SYMBOL_BLOCKS:
            try:
                entity.Delete()
                deleted_count += 1
            except Exception:
                pass

    if deleted_count:
        print(f"Deleted old preview symbols: {deleted_count}")


def insert_preview_symbols(doc):
    """Insert one preview instance of each symbol so the user can visually confirm."""
    model = doc.ModelSpace

    preview_layer = ensure_layer(doc, PREVIEW_LAYER)
    clear_old_preview_symbols(doc)

    try:
        old_active_layer = doc.ActiveLayer
    except Exception:
        old_active_layer = None

    # Safer than block_ref.Layer = ...
    # Some AutoCAD COM objects reject setting Layer directly after InsertBlock.
    doc.ActiveLayer = preview_layer

    start_x = 0
    y = 0
    spacing = 80

    for index, block_name in enumerate(SYMBOL_BLOCKS):
        x = start_x + (index * spacing)

        block_ref = model.InsertBlock(
            point(x, y),
            block_name,
            1.0,
            1.0,
            1.0,
            0.0,
        )

        set_block_attributes(
            block_ref,
            {
                "TAG": block_name,
                "SIZE": "TEST",
                "SERVICE": "PREVIEW",
            },
        )

    if old_active_layer is not None:
        try:
            doc.ActiveLayer = old_active_layer
        except Exception:
            pass

    print(f"Inserted {len(SYMBOL_BLOCKS)} preview symbols on layer {PREVIEW_LAYER}")


def main():
    acad, doc = connect_to_autocad()

    print(f"Connected to: {acad.Caption}")
    print(f"Active drawing: {doc.Name}")

    create_gate_valve(doc)
    create_check_valve(doc)
    create_control_valve(doc)
    create_pump(doc)
    create_vessel(doc)
    create_instrument_bubble(doc)

    insert_preview_symbols(doc)

    doc.Regen(1)
    acad.ZoomExtents()

    time.sleep(0.3)

    print("\nDone.")
    print("You should now see preview symbols in AutoCAD.")
    print("Save the drawing as E:\\RC-Projects\\symbol_test.dwg if you have not saved it yet.")


if __name__ == "__main__":
    main()
"""
Phase 2 — Task 2.2 (read phase).

Open a DWG, find the TITLE_BLOCK_TEST, print its attributes.
Uses pywin32 for COM access (better SAFEARRAY handling than comtypes
for AutoCAD's GetAttributes()).
"""

import sys
from pathlib import Path

import win32com.client


DRAWINGS_FOLDER = Path(r"E:\RC-Projects")
TITLE_BLOCK_NAME = "TITLE_BLOCK_TEST"
TARGET_FILE = "drawing_001.dwg"


def connect_autocad():
    try:
        return win32com.client.GetActiveObject("AutoCAD.Application")
    except Exception as e:
        print(f"ERROR: cannot connect to AutoCAD ({e}).")
        print("Make sure AutoCAD is running.")
        sys.exit(1)


def find_title_blocks(model_space, block_name):
    for i in range(model_space.Count):
        entity = model_space.Item(i)
        if entity.ObjectName == "AcDbBlockReference" and entity.Name == block_name:
            yield entity


def attributes_dict(block_ref):
    if not block_ref.HasAttributes:
        return {}
    return {att.TagString: att for att in block_ref.GetAttributes()}


def main():
    target = DRAWINGS_FOLDER / TARGET_FILE
    if not target.exists():
        print(f"ERROR: file not found: {target}")
        sys.exit(1)

    acad = connect_autocad()
    print(f"Connected to: {acad.Caption}")

    print(f"Opening {target} ...")
    acad.Documents.Open(str(target))
    doc = acad.ActiveDocument
    model = doc.ModelSpace

    print(f"Active drawing: {doc.Name}\n")

    blocks = list(find_title_blocks(model, TITLE_BLOCK_NAME))
    if not blocks:
        print(f"No '{TITLE_BLOCK_NAME}' blocks found.")
        return

    print(f"Found {len(blocks)} title block(s) in {doc.Name}:\n")
    for i, blk in enumerate(blocks, 1):
        print(f"  Block {i}:")
        attrs = attributes_dict(blk)
        if not attrs:
            print("    (no attributes)")
        for tag, att in attrs.items():
            print(f"    {tag:12s} = {att.TextString}")
        print()


if __name__ == "__main__":
    main()
"""
Quick read-only check: print current title block values across all test DWGs.

Run from the project root:
    python -m src.use_cases.verify_title_blocks
"""

import sys
import time
from pathlib import Path

import win32com.client


DRAWINGS_FOLDER = Path(r"E:\RC-Projects")
TITLE_BLOCK_NAME = "TITLE_BLOCK_TEST"
FILE_PATTERN = "drawing_*.dwg"


def get_acad():
    return win32com.client.GetActiveObject("AutoCAD.Application")


def read_one_file(f):
    acad = get_acad()
    doc = acad.Documents.Open(str(f))
    time.sleep(0.3)
    try:
        for i in range(doc.ModelSpace.Count):
            ent = doc.ModelSpace.Item(i)
            if ent.ObjectName == "AcDbBlockReference" and ent.Name == TITLE_BLOCK_NAME:
                vals = {a.TagString.strip(): a.TextString for a in ent.GetAttributes()}
                doc.Close(False)
                return vals
        doc.Close(False)
    except Exception:
        try:
            doc.Close(False)
        except Exception:
            pass
        raise
    return None


def main():
    try:
        caption = get_acad().Caption
    except Exception as e:
        print(f"ERROR: cannot connect to AutoCAD ({e}).")
        sys.exit(1)

    files = sorted(DRAWINGS_FOLDER.glob(FILE_PATTERN))
    if not files:
        print(f"No files match pattern '{FILE_PATTERN}' in {DRAWINGS_FOLDER}")
        return

    print(f"Reading {len(files)} file(s) from {caption}\n")
    for f in files:
        try:
            vals = read_one_file(f)
            if vals is None:
                print(f"  {f.name}: no '{TITLE_BLOCK_NAME}' block found")
            else:
                print(f"  {f.name}: "
                      f"REV={vals.get('REV')}, "
                      f"DATE={vals.get('DATE')}, "
                      f"DRAWN_BY={vals.get('DRAWN_BY')}, "
                      f"DRAWING_NO={vals.get('DRAWING_NO')}")
        except Exception as e:
            print(f"  {f.name}: ERROR — {type(e).__name__}: {e}")
        time.sleep(1.0)


if __name__ == "__main__":
    main()
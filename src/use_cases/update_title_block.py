"""
Phase 2 — Tasks 2.3 + 2.4 + 2.5 + 2.7.

Batch-update specific attributes on the TITLE_BLOCK_TEST across every
DWG file in a folder. Each file is backed up before modification.
Supports DRY_RUN mode for previewing changes without saving.

Run from the project root:
    python -m src.use_cases.update_title_block
"""

import sys
import time
from pathlib import Path

import win32com.client
import pywintypes

from src.backup import backup_file
from src.logging.decorators import log_job


# ---------- config ----------

DRAWINGS_FOLDER = Path(r"E:\RC-Projects")
TITLE_BLOCK_NAME = "TITLE_BLOCK_TEST"
FILE_PATTERN = "drawing_*.dwg"

UPDATES = {
    "REV": "F",
    "DATE": "2026-06-01",
    "DRAWN_BY": "S. AAMIR",
}

DRY_RUN = False

PAUSE_BETWEEN_FILES_SEC = 1.5
FILE_MAX_RETRIES = 3
FILE_RETRY_DELAY_SEC = 2.0

RPC_E_CALL_REJECTED = -2147418111
RPC_E_SERVERCALL_RETRYLATER = -2147417846


def is_busy_error(exc):
    if isinstance(exc, pywintypes.com_error) and exc.args:
        hresult = exc.args[0]
        if hresult in (RPC_E_CALL_REJECTED, RPC_E_SERVERCALL_RETRYLATER):
            return True
    if isinstance(exc, AttributeError):
        return True
    return False


def get_acad():
    """
    Fresh AutoCAD COM handle every time. We do NOT cache the Application
    object across files — pywin32's proxy goes stale after enough
    open/close cycles, leading to '<unknown>.Open' errors.
    """
    return win32com.client.GetActiveObject("AutoCAD.Application")


def find_title_blocks(model_space, block_name):
    for i in range(model_space.Count):
        entity = model_space.Item(i)
        if entity.ObjectName == "AcDbBlockReference" and entity.Name == block_name:
            yield entity


def update_attributes(block_ref, updates):
    if not block_ref.HasAttributes:
        return []
    changes = []
    for att in block_ref.GetAttributes():
        tag = att.TagString.strip()
        if tag in updates:
            old = att.TextString
            new = str(updates[tag])
            if old != new:
                att.TextString = new
                changes.append((tag, old, new))
    return changes


def _do_one_file(dwg_path, updates):
    """Single attempt: get fresh COM handle, open, update, save, close."""
    acad = get_acad()
    doc = acad.Documents.Open(str(dwg_path))
    time.sleep(0.3)
    try:
        model = doc.ModelSpace
        blocks = list(find_title_blocks(model, TITLE_BLOCK_NAME))

        if not blocks:
            doc.Close(False)
            return {"blocks_found": 0, "changes": 0, "status": "no_title_block"}

        total_changes = 0
        for blk in blocks:
            changes = update_attributes(blk, updates)
            total_changes += len(changes)

        if total_changes and not DRY_RUN:
            doc.Save()
        doc.Close(False)

        if DRY_RUN and total_changes:
            status = "dry_run"
        else:
            status = "ok"

        return {
            "blocks_found": len(blocks),
            "changes": total_changes,
            "status": status,
        }

    except Exception:
        try:
            doc.Close(False)
        except Exception:
            pass
        raise


def process_one_file(dwg_path, updates):
    result = {
        "file": dwg_path.name,
        "backup": None,
        "blocks_found": 0,
        "changes": 0,
        "status": "ok",
        "error": None,
    }

    if not DRY_RUN:
        try:
            result["backup"] = str(backup_file(dwg_path))
        except Exception as e:
            result["status"] = "error"
            result["error"] = f"backup failed: {type(e).__name__}: {e}"
            return result

    last_err = None
    for attempt in range(1, FILE_MAX_RETRIES + 1):
        try:
            outcome = _do_one_file(dwg_path, updates)
            result.update(outcome)
            return result
        except Exception as e:
            last_err = e
            if is_busy_error(e) and attempt < FILE_MAX_RETRIES:
                time.sleep(FILE_RETRY_DELAY_SEC * attempt)
                continue
            break

    result["status"] = "error"
    result["error"] = f"{type(last_err).__name__}: {last_err}"
    return result


def print_summary(results):
    print("\n" + "=" * 60)
    print(f"BATCH SUMMARY — {len(results)} file(s) processed")
    print("=" * 60)

    ok = [r for r in results if r["status"] == "ok"]
    dry_runs = [r for r in results if r["status"] == "dry_run"]
    no_block = [r for r in results if r["status"] == "no_title_block"]
    errors = [r for r in results if r["status"] == "error"]

    marker_for = {
        "ok": "OK ",
        "no_title_block": "—  ",
        "error": "ERR",
        "dry_run": "DRY",
    }

    for r in results:
        marker = marker_for[r["status"]]
        line = f"  [{marker}] {r['file']:25s} blocks={r['blocks_found']} changes={r['changes']}"
        if r["error"]:
            line += f"  ({r['error']})"
        print(line)

    print("-" * 60)
    print(f"  Updated:        {len(ok)}")
    print(f"  Dry-run:        {len(dry_runs)}")
    print(f"  No title block: {len(no_block)}")
    print(f"  Errors:         {len(errors)}")
    print("=" * 60)


@log_job("title_block_update")
def main():
    if not DRAWINGS_FOLDER.exists():
        print(f"ERROR: folder not found: {DRAWINGS_FOLDER}")
        sys.exit(1)

    files = sorted(DRAWINGS_FOLDER.glob(FILE_PATTERN))
    if not files:
        print(f"No files match pattern '{FILE_PATTERN}' in {DRAWINGS_FOLDER}")
        sys.exit(0)

    print(f"Found {len(files)} file(s) to process:")
    for f in files:
        print(f"  - {f.name}")
    print(f"\nApplying updates: {UPDATES}\n")

    # Sanity ping: make sure AutoCAD is reachable before we begin.
    try:
        caption = get_acad().Caption
        print(f"Connected to: {caption}\n")
    except Exception as e:
        print(f"ERROR: cannot reach AutoCAD: {e}")
        sys.exit(1)

    if DRY_RUN:
        print(">>> DRY RUN MODE — no files will be modified <<<\n")

    results = []
    for idx, f in enumerate(files):
        if idx > 0:
            time.sleep(PAUSE_BETWEEN_FILES_SEC)
        print(f"--- Processing {f.name} ---")
        result = process_one_file(f, UPDATES)
        if result["status"] == "ok":
            print(f"    OK: {result['blocks_found']} block(s), {result['changes']} change(s)")
        elif result["status"] == "dry_run":
            print(f"    DRY: would change {result['changes']} attribute(s) "
                  f"in {result['blocks_found']} block(s)")
        elif result["status"] == "no_title_block":
            print(f"    SKIPPED: no '{TITLE_BLOCK_NAME}' in this drawing")
        else:
            print(f"    ERROR: {result['error']}")
        results.append(result)

    print_summary(results)


if __name__ == "__main__":
    main()

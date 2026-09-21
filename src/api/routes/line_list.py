import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from src.api.schemas import LineListExtractRequest


router = APIRouter(prefix="/api", tags=["line-list"])

# Guards `_temporary_module_settings` below. Without this, two concurrent
# requests each overwrite the same module-level constants on `use_case` —
# one request can observe the other's overrides mid-flight, and whichever
# request's `finally` runs last "restores" its own originals over the
# other's still-in-flight state. Serializing the whole monkey-patch→call→
# restore critical section removes the race without touching the use_case
# module itself (still respecting the original Phase 7 constraint).
_SETTINGS_LOCK = threading.Lock()


@contextmanager
def _temporary_module_settings(module: Any, **overrides: Any):
    # Phase 7 must wrap the existing module-level constants without editing the
    # use case itself. Override attributes on the imported module object only,
    # then restore them in finally so one request cannot leak into the next.
    with _SETTINGS_LOCK:
        originals = {name: getattr(module, name) for name in overrides}
        try:
            for name, value in overrides.items():
                setattr(module, name, value)
            yield module
        finally:
            for name, value in originals.items():
                setattr(module, name, value)


@router.post("/line-list-extract")
def line_list_extract(request: LineListExtractRequest):
    import pythoncom
    from src.use_cases import line_list_extract as use_case

    pythoncom.CoInitialize()
    drawings_folder = Path(request.drawings_folder)
    try:
        if not drawings_folder.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Drawings folder not found: {drawings_folder}",
            )

        with _temporary_module_settings(
            use_case,
            DRAWINGS_FOLDER=drawings_folder,
            TARGET_FILE=request.target_file,
            LINE_BLOCK_NAME=request.line_block_name,
        ):
            target = use_case.DRAWINGS_FOLDER / use_case.TARGET_FILE
            if not target.exists():
                raise HTTPException(
                    status_code=404,
                    detail=f"Drawing not found: {target}",
                )

            use_case.OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

            try:
                acad = use_case.get_acad()
            except Exception as exc:
                raise HTTPException(
                    status_code=503,
                    detail=f"Cannot connect to AutoCAD: {type(exc).__name__}: {exc}",
                ) from exc

            doc = acad.Documents.Open(str(target))
            time.sleep(0.3)

            try:
                blocks = list(
                    use_case.find_blocks_by_name(doc.ModelSpace, use_case.LINE_BLOCK_NAME)
                )
                rows = [
                    use_case.normalize_row(
                        use_case.extract_attributes(block_ref),
                        use_case.LINE_LIST_COLUMNS,
                    )
                    for block_ref in blocks
                ]

                output_file = None
                download_url = None

                if rows:
                    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                    filename = f"line_list_{Path(use_case.TARGET_FILE).stem}_{timestamp}.xlsx"
                    output_path = use_case.OUTPUT_FOLDER / filename
                    use_case.write_line_list_xlsx(rows, doc.Name, output_path)
                    output_file = f"outputs/{filename}"
                    download_url = f"/api/download/{filename}"

                return {
                    "ok": True,
                    "rows_extracted": len(rows),
                    "output_file": output_file,
                    "download_url": download_url,
                    "rows": rows,
                }
            finally:
                doc.Close(False)
    finally:
        pythoncom.CoUninitialize()

import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from src.api.routes._revertible import (
    run_revertible,
)
from src.api.schemas import TitleBlockUpdateRequest


router = APIRouter(prefix="/api", tags=["title-block"])

# Guards `_temporary_module_settings` below. Without this, two concurrent
# requests each overwrite the same module-level constants on `use_case` —
# request A can observe request B's overrides mid-flight (e.g. B's title
# updates get written using A's DRAWINGS_FOLDER/UPDATES), and whichever
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


def _summarize_results(results: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(results),
        "ok": sum(1 for item in results if item.get("status") == "ok"),
        "dry_run": sum(1 for item in results if item.get("status") == "dry_run"),
        "errors": sum(1 for item in results if item.get("status") == "error"),
        "no_title_block": sum(
            1 for item in results if item.get("status") == "no_title_block"
        ),
    }


@router.post("/title-block-update")
def title_block_update(
    request: TitleBlockUpdateRequest,
):
    import pythoncom
    from src.use_cases import (
        update_title_block
        as use_case,
    )

    pythoncom.CoInitialize()

    drawings_folder = Path(
        request.drawings_folder
    )

    try:
        if not drawings_folder.exists():
            raise HTTPException(
                status_code=404,
                detail=(
                    "Drawings folder not found: "
                    f"{drawings_folder}"
                ),
            )

        with _temporary_module_settings(
            use_case,
            DRAWINGS_FOLDER=
                drawings_folder,
            FILE_PATTERN=
                request.file_pattern,
            TITLE_BLOCK_NAME=
                request.title_block_name,
            UPDATES=
                dict(request.updates),
            DRY_RUN=
                request.dry_run,
        ):
            files = sorted(
                use_case
                .DRAWINGS_FOLDER
                .glob(
                    use_case.FILE_PATTERN
                )
            )

            if not files:
                return {
                    "ok": True,
                    "files": [],
                    "summary":
                        _summarize_results(
                            []
                        ),
                }

            try:
                connected_to = (
                    use_case
                    .get_acad()
                    .Caption
                )

            except Exception as exc:
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Cannot reach AutoCAD: "
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
                ) from exc

            results = []

            for index, file_path in enumerate(
                files
            ):
                if index > 0:
                    time.sleep(
                        use_case
                        .PAUSE_BETWEEN_FILES_SEC
                    )

                def execute_one(
                    path=file_path,
                ):
                    return (
                        use_case
                        .process_one_file(
                            path,
                            use_case.UPDATES,
                            create_backup=False,
                        )
                    )

                (
                    result,
                    change_set_id,
                    change_set_skipped_reason,
                ) = run_revertible(
                    str(file_path),
                    (
                        "Update title block "
                        f"{use_case.TITLE_BLOCK_NAME} "
                        f"in {file_path.name}"
                    ),
                    execute_one,
                    save=not use_case.DRY_RUN,
                )

                result = dict(result)

                result[
                    "change_set_id"
                ] = change_set_id

                result[
                    "change_set_skipped_reason"
                ] = (
                    change_set_skipped_reason
                )

                results.append(result)

            return {
                "ok": True,
                "connected_to":
                    connected_to,
                "files": results,
                "summary":
                    _summarize_results(
                        results
                    ),
            }

    finally:
        pythoncom.CoUninitialize()

"""Read-only AutoCAD drawing inspection API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from src.framework.autocad.inspector import (
    inspect_active_drawing,
    summarize_drawing_state,
)
from src.parametric.vessel.dwg_export import AutoCADNotRunningError


router = APIRouter(prefix="/api/autocad", tags=["autocad"])


@router.get("/inspect")
def inspect_autocad_drawing(
    max_entities: int = Query(default=200, ge=1, le=2000),
    target_dwg_path: str | None = Query(default=None),
):
    """Return a read-only snapshot of the active AutoCAD drawing."""
    import pythoncom

    pythoncom.CoInitialize()
    try:
        # `is not None`, not truthiness: an explicitly-sent empty string must
        # still be forwarded (and rejected downstream with a clear error by
        # `canonical_path`) rather than being silently treated the same as
        # "no target given" and falling back to `ActiveDocument`.
        options = {"target_dwg_path": target_dwg_path} if target_dwg_path is not None else {}
        inspection = inspect_active_drawing(max_entities=max_entities, **options)
        summary = summarize_drawing_state(inspection)
    except AutoCADNotRunningError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "AutoCAD is not running. Open AutoCAD with a drawing active "
                "and try again."
            ),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"AutoCAD drawing inspection failed: {type(exc).__name__}: {exc}",
        ) from exc
    finally:
        pythoncom.CoUninitialize()

    return {
        "ok": True,
        "summary": summary,
        "inspection": inspection,
    }

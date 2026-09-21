"""Live AutoCAD edit API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.ai.edit_generator import generate_edit_plan
from src.api.routes._revertible import require_explicit_target, run_revertible
from src.framework.autocad.inspector import (
    inspect_active_drawing,
    summarize_drawing_state,
)
from src.framework.commands.edit_executor import execute_edit_plan
from src.parametric.vessel.dwg_export import AutoCADNotRunningError


router = APIRouter(prefix="/api/autocad", tags=["autocad"])

AUTOCAD_NOT_RUNNING_DETAIL = (
    "AutoCAD is not running. Open AutoCAD with a drawing active and try again."
)


class AutoCADEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(..., min_length=1)
    max_entities: int = Field(default=200, ge=1, le=2000)
    auto_execute: bool = True
    save: bool = False
    use_active_document: bool = False
    target_dwg_path: str | None = None


def _inspect_with_com(max_entities: int, target_dwg_path: str | None = None) -> tuple[dict, str]:
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
    finally:
        pythoncom.CoUninitialize()

    return inspection, summary


def _execute_with_com(
    edit_plan: dict,
    target_dwg_path: str | None,
    save: bool,
) -> dict:
    import pythoncom

    pythoncom.CoInitialize()
    try:
        return run_revertible(
            target_dwg_path,
            f"AutoCAD edit: {edit_plan.get('summary') or edit_plan.get('edit_intent') or 'live edit'}",
            lambda: execute_edit_plan(
                edit_plan,
                target_dwg_path=target_dwg_path,
                save=save,
                zoom_extents=True,
            ),
            save=save,
        )
    finally:
        pythoncom.CoUninitialize()


@router.post("/edit")
def edit_autocad_drawing(request: AutoCADEditRequest):
    prompt = request.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")

    if request.auto_execute:
        require_explicit_target(request.target_dwg_path, request.use_active_document)

    try:
        inspection, inspection_summary = _inspect_with_com(request.max_entities, request.target_dwg_path)
    except AutoCADNotRunningError as exc:
        raise HTTPException(
            status_code=503,
            detail=AUTOCAD_NOT_RUNNING_DETAIL,
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"AutoCAD drawing inspection failed: {type(exc).__name__}: {exc}",
        ) from exc

    try:
        edit_plan = generate_edit_plan(prompt, inspection)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Edit generation failed: {type(exc).__name__}: {exc}",
        ) from exc

    if not request.auto_execute:
        return {
            "ok": True,
            "executed": False,
            "prompt": prompt,
            "inspection_summary": inspection_summary,
            "document_name": inspection.get("document_name"),
            "entity_count_returned": inspection.get("entity_count_returned"),
            "edit_plan": edit_plan,
            "execution_result": None,
        }

    try:
        execution_result, change_set_id, change_set_skipped_reason = _execute_with_com(
            edit_plan,
            target_dwg_path=request.target_dwg_path,
            save=request.save,
        )
    except AutoCADNotRunningError as exc:
        raise HTTPException(
            status_code=503,
            detail=AUTOCAD_NOT_RUNNING_DETAIL,
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"AutoCAD edit execution failed: {type(exc).__name__}: {exc}",
        ) from exc

    return {
        "ok": bool(execution_result.get("ok")),
        "executed": True,
        "prompt": prompt,
        "inspection_summary": inspection_summary,
        "document_name": inspection.get("document_name"),
        "entity_count_returned": inspection.get("entity_count_returned"),
        "edit_plan": edit_plan,
        "execution_result": execution_result,
        "change_set_id": change_set_id,
        "change_set_skipped_reason": change_set_skipped_reason,
    }

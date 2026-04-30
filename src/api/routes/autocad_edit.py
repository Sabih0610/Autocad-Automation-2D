"""Live AutoCAD edit API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.ai.edit_generator import generate_edit_plan
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
    target_dwg_path: str | None = None


def _inspect_with_com(max_entities: int) -> tuple[dict, str]:
    import pythoncom

    pythoncom.CoInitialize()
    try:
        inspection = inspect_active_drawing(max_entities=max_entities)
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
        return execute_edit_plan(
            edit_plan,
            target_dwg_path=target_dwg_path,
            save=save,
            zoom_extents=True,
        )
    finally:
        pythoncom.CoUninitialize()


@router.post("/edit")
def edit_autocad_drawing(request: AutoCADEditRequest):
    prompt = request.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")

    try:
        inspection, inspection_summary = _inspect_with_com(request.max_entities)
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
        execution_result = _execute_with_com(
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
    }

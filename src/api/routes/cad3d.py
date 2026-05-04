"""FastAPI routes for deterministic 3D CAD scene generation and approval."""

from __future__ import annotations

import time
from typing import Any
import uuid

from fastapi import APIRouter, HTTPException
import pythoncom

from src.ai.cad3d_edit_planner import (
    deterministic_edit_plan_from_request,
    plan_cad3d_edit_resilient,
)
from src.ai.cad3d_scene_planner import plan_cad3d_scene_resilient
from src.api.schemas import CAD3DApproveRequest, CAD3DEditRequest, CAD3DGenerateRequest
from src.framework.cad3d.autocad_3d_executor import (
    AutoCAD3DExecutionError,
    execute_cad3d_scene,
)
from src.framework.cad3d.component_examples import (
    available_cad3d_component_examples,
    get_cad3d_component_example,
)
from src.framework.cad3d.routing import expand_pipe_connections
from src.framework.cad3d.scene_store import (
    CAD3DSceneStoreError,
    extract_scene_component_summary,
    get_default_cad3d_scene_store,
)
from src.framework.cad3d.scene_editor import (
    CAD3DSceneEditError,
    apply_cad3d_edit_plan,
    summarize_scene_edit,
)
from src.parametric.vessel.dwg_export import AutoCADNotRunningError


router = APIRouter(prefix="/api/cad3d", tags=["cad3d"])

_CAD3D_CACHE: dict[str, dict[str, Any]] = {}


def _short_error(exc: Exception, max_length: int = 2000) -> str:
    message = str(exc)
    if len(message) <= max_length:
        return message
    return message[:max_length] + "... [truncated]"


def _component_types(scene_data: dict) -> list[str]:
    return sorted(
        {
            component.get("component_type")
            for component in scene_data.get("components", [])
            if component.get("component_type")
        }
    )


def _approval_result_summary(approval_result: dict | None) -> dict | None:
    if not isinstance(approval_result, dict):
        return None

    keys = [
        "ok",
        "executed_count",
        "total_count",
        "pipe_connections_expanded",
        "document_name",
        "entity_count_before",
        "entity_count_after",
    ]
    return {
        key: approval_result.get(key)
        for key in keys
        if key in approval_result
    }


def _scene_record_summary(record) -> dict:
    return {
        "token": record.token,
        "prompt": record.prompt,
        "drawing_style": record.drawing_style,
        "status": record.status,
        "document_name": record.document_name,
        "component_count": len(record.component_ids),
        "component_ids": record.component_ids,
        "component_types": record.component_types,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "generation_metadata": record.generation_metadata,
        "approval_result": _approval_result_summary(record.approval_result),
    }


def _scene_record_detail(record) -> dict:
    detail = _scene_record_summary(record)
    detail["scene"] = record.scene
    detail["expanded_scene"] = record.expanded_scene
    return detail


@router.post("/generate")
def cad3d_generate(request: CAD3DGenerateRequest):
    prompt = request.prompt.strip() if request.prompt else None
    drawing_style = request.drawing_style.strip() if request.drawing_style else "simple clean 3D equipment layout"
    example_name = request.example_name.strip() or "simple_component_layout"
    if not example_name:
        raise HTTPException(status_code=400, detail="example_name cannot be empty.")

    if prompt:
        try:
            scene_data = plan_cad3d_scene_resilient(
                prompt,
                drawing_style=drawing_style,
                allow_example_fallback=True,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"3D CAD scene planning failed: {type(exc).__name__}: {_short_error(exc)}",
            ) from exc

        metadata = scene_data.get("metadata", {})
        generation_strategy = metadata.get("planner_strategy") or "ai_cad3d_scene_planner"
    else:
        try:
            component_scene = get_cad3d_component_example(example_name)
        except ValueError as exc:
            available = ", ".join(sorted(available_cad3d_component_examples()))
            raise HTTPException(
                status_code=400,
                detail=f"{_short_error(exc)}. Available examples: {available}",
            ) from exc

        try:
            scene_data = component_scene.to_scene_data()
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"3D CAD scene generation failed: {type(exc).__name__}: {_short_error(exc)}",
            ) from exc

        generation_strategy = "component_example"
        metadata = scene_data.get("metadata", {})

    token = uuid.uuid4().hex

    fallback_template_name = metadata.get("fallback_template_name") or metadata.get("fallback_example_name")
    fallback_example_name = metadata.get("fallback_example_name") or metadata.get("fallback_template_name")

    _CAD3D_CACHE[token] = {
        "prompt": prompt,
        "drawing_style": drawing_style,
        "example_name": example_name,
        "scene_data": scene_data,
        "created_at": time.time(),
        "generation_strategy": generation_strategy,
        "fallback_used": metadata.get("fallback_used", False),
        "fallback_reason": metadata.get("fallback_reason"),
        "fallback_example_name": fallback_example_name,
        "fallback_template_name": fallback_template_name,
    }

    component_summary = extract_scene_component_summary(scene_data)
    generation_metadata = {
        "generation_strategy": generation_strategy,
        "fallback_used": metadata.get("fallback_used", False),
        "fallback_reason": metadata.get("fallback_reason"),
        "fallback_example_name": fallback_example_name,
        "fallback_template_name": fallback_template_name,
        "ai_planner_attempted": metadata.get("ai_planner_attempted"),
        "ai_planner_error_type": metadata.get("ai_planner_error_type"),
        "ai_planner_error": metadata.get("ai_planner_error"),
    }
    scene_state_saved = True
    scene_state_error = None
    try:
        get_default_cad3d_scene_store().put_generated_scene(
            token=token,
            prompt=prompt or "",
            drawing_style=drawing_style,
            scene=scene_data,
            generation_metadata=generation_metadata,
        )
    except CAD3DSceneStoreError as exc:
        if "Invalid CAD3D scene" in str(exc):
            raise HTTPException(
                status_code=500,
                detail=f"3D CAD scene state validation failed: {_short_error(exc)}",
            ) from exc
        scene_state_saved = False
        scene_state_error = _short_error(exc)

    response = {
        "ok": True,
        "token": token,
        "scene_token": token,
        "scene_state_saved": scene_state_saved,
        "component_ids": component_summary["component_ids"],
        "component_count": component_summary["component_count"],
        "generation_strategy": generation_strategy,
        "fallback_used": metadata.get("fallback_used", False),
        "fallback_reason": metadata.get("fallback_reason"),
        "fallback_example_name": fallback_example_name,
        "fallback_template_name": fallback_template_name,
        "ai_planner_attempted": metadata.get("ai_planner_attempted"),
        "ai_planner_error_type": metadata.get("ai_planner_error_type"),
        "ai_planner_error": metadata.get("ai_planner_error"),
        "example_name": example_name,
        "title": scene_data["title"],
        "units": scene_data["units"],
        "component_types": component_summary["component_types"],
        "assumptions": scene_data.get("assumptions", []),
        "metadata": metadata,
    }
    if scene_state_error is not None:
        response["scene_state_error"] = scene_state_error

    return response


@router.get("/state")
def cad3d_state_list(limit: int = 20):
    try:
        records = get_default_cad3d_scene_store().list_records(limit=limit)
    except CAD3DSceneStoreError as exc:
        raise HTTPException(status_code=400, detail=_short_error(exc)) from exc

    return {
        "ok": True,
        "records": [_scene_record_summary(record) for record in records],
    }


@router.get("/state/latest")
def cad3d_state_latest():
    try:
        record = get_default_cad3d_scene_store().get_latest()
    except CAD3DSceneStoreError as exc:
        raise HTTPException(status_code=404, detail=_short_error(exc)) from exc

    return {
        "ok": True,
        "record": _scene_record_summary(record),
    }


@router.get("/state/{token}")
def cad3d_state_token(token: str):
    try:
        record = get_default_cad3d_scene_store().get(token)
    except CAD3DSceneStoreError as exc:
        raise HTTPException(status_code=404, detail=_short_error(exc)) from exc

    return {
        "ok": True,
        "record": _scene_record_detail(record),
    }


@router.post("/edit")
def cad3d_edit(request: CAD3DEditRequest):
    prompt = request.prompt.strip() if request.prompt else ""
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt cannot be empty.")

    store = get_default_cad3d_scene_store()
    try:
        source_record = store.get(request.token) if request.token else store.get_latest()
    except CAD3DSceneStoreError as exc:
        raise HTTPException(status_code=404, detail=_short_error(exc)) from exc

    source_token = source_record.token
    source_scene = source_record.scene

    try:
        edit_plan = plan_cad3d_edit_resilient(prompt, source_scene)
        try:
            edited_scene = apply_cad3d_edit_plan(source_scene, edit_plan)
        except CAD3DSceneEditError as apply_exc:
            fallback_plan = deterministic_edit_plan_from_request(prompt, source_scene)
            fallback_metadata = fallback_plan.setdefault("metadata", {})
            fallback_metadata["planner_strategy"] = "deterministic_edit_fallback"
            fallback_metadata["fallback_used"] = True
            fallback_metadata["ai_plan_apply_error"] = str(apply_exc)
            edit_plan = fallback_plan
            edited_scene = apply_cad3d_edit_plan(source_scene, edit_plan)
    except CAD3DSceneEditError as exc:
        raise HTTPException(status_code=400, detail=_short_error(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"CAD3D edit planning failed: {type(exc).__name__}: {_short_error(exc)}",
        ) from exc

    edited_token = uuid.uuid4().hex if request.create_new_token else source_token
    edit_summary = summarize_scene_edit(source_scene, edited_scene)
    component_summary = extract_scene_component_summary(edited_scene)
    generation_metadata = {
        "generation_strategy": "cad3d_scene_edit",
        "source_token": source_token,
        "edit_prompt": prompt,
        "edit_plan_metadata": edit_plan.get("metadata", {}),
        "edit_summary": edit_summary,
    }

    scene_state_saved = True
    scene_state_error = None
    try:
        store.put_generated_scene(
            token=edited_token,
            prompt=prompt,
            drawing_style=source_record.drawing_style,
            scene=edited_scene,
            generation_metadata=generation_metadata,
        )
    except CAD3DSceneStoreError as exc:
        scene_state_saved = False
        scene_state_error = _short_error(exc)

    _CAD3D_CACHE[edited_token] = {
        "prompt": prompt,
        "drawing_style": source_record.drawing_style,
        "example_name": "cad3d_scene_edit",
        "scene_data": edited_scene,
        "created_at": time.time(),
        "generation_strategy": "cad3d_scene_edit",
        "fallback_used": edit_plan.get("metadata", {}).get("fallback_used", False),
        "fallback_reason": edit_plan.get("metadata", {}).get("ai_planner_error"),
        "fallback_example_name": None,
        "fallback_template_name": None,
    }

    executed = False
    execution_result = None
    scene_state_updated = False
    scene_status = "generated"
    expanded_scene = None

    if request.execute:
        try:
            expanded_scene = expand_pipe_connections(edited_scene)
        except Exception:
            expanded_scene = None

        try:
            pythoncom.CoInitialize()
            try:
                execution_result = execute_cad3d_scene(
                    edited_scene,
                    target_dwg_path=request.target_dwg_path,
                    save=request.save,
                    zoom_extents=True,
                )
            finally:
                pythoncom.CoUninitialize()
        except AutoCADNotRunningError as exc:
            raise HTTPException(
                status_code=503,
                detail=(
                    "AutoCAD is not running. Start AutoCAD with a drawing open, "
                    "then execute this edited 3D CAD scene again."
                ),
            ) from exc
        except AutoCAD3DExecutionError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"3D CAD edit execution failed: {_short_error(exc)}",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"3D CAD edit execution failed: {type(exc).__name__}: {_short_error(exc)}",
            ) from exc

        executed = True
        scene_status = "approved" if execution_result.get("ok") else "failed"
        try:
            record = store.mark_approved(
                edited_token,
                approval_result=execution_result,
                expanded_scene=expanded_scene,
            )
            scene_state_updated = True
            scene_status = record.status
        except CAD3DSceneStoreError as exc:
            scene_state_error = _short_error(exc)

    response = {
        "ok": scene_state_saved and (not executed or bool(execution_result and execution_result.get("ok"))),
        "source_token": source_token,
        "edited_token": edited_token,
        "edit_plan": edit_plan,
        "edit_summary": edit_summary,
        "component_count": component_summary["component_count"],
        "component_ids": component_summary["component_ids"],
        "component_types": component_summary["component_types"],
        "scene_state_saved": scene_state_saved,
        "scene_state_updated": scene_state_updated,
        "scene_status": scene_status,
        "executed": executed,
        "execution_result": execution_result,
    }
    if scene_state_error is not None:
        response["scene_state_error"] = scene_state_error
    return response


@router.post("/approve")
def cad3d_approve(request: CAD3DApproveRequest):
    cached = _CAD3D_CACHE.get(request.token)
    if cached is None:
        raise HTTPException(
            status_code=404,
            detail="3D CAD token was not found or has expired. Generate again.",
        )

    scene_data = cached["scene_data"]
    expanded_scene = None
    try:
        expanded_scene = expand_pipe_connections(scene_data)
    except Exception:
        expanded_scene = None

    try:
        pythoncom.CoInitialize()
        try:
            result = execute_cad3d_scene(
                scene_data,
                target_dwg_path=request.target_dwg_path,
                save=request.save,
                zoom_extents=True,
            )
        finally:
            pythoncom.CoUninitialize()
    except AutoCADNotRunningError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "AutoCAD is not running. Start AutoCAD with a drawing open, "
                "then approve this 3D CAD model again."
            ),
        ) from exc
    except AutoCAD3DExecutionError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"3D CAD execution failed: {_short_error(exc)}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"3D CAD execution failed: {type(exc).__name__}: {_short_error(exc)}",
        ) from exc

    scene_state_updated = True
    scene_state_error = None
    scene_status = "approved" if result.get("ok") else "failed"
    try:
        record = get_default_cad3d_scene_store().mark_approved(
            token=request.token,
            approval_result=result,
            expanded_scene=expanded_scene,
        )
        scene_status = record.status
    except CAD3DSceneStoreError as exc:
        scene_state_updated = False
        scene_state_error = _short_error(exc)

    response = {
        "ok": bool(result.get("ok")),
        "executed": True,
        "token": request.token,
        "scene_token": request.token,
        "scene_state_updated": scene_state_updated,
        "scene_status": scene_status,
        "document_name": result.get("document_name"),
        "execution_result": result,
        "generation_strategy": cached["generation_strategy"],
        "example_name": cached["example_name"],
        "title": scene_data.get("title"),
        "component_count": len(scene_data["components"]),
    }
    if scene_state_error is not None:
        response["scene_state_error"] = scene_state_error

    return {
        **response,
    }

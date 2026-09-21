"""FastAPI routes for component-based P&ID generation and approval."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException

from src.ai.pid_component_planner import plan_and_render_pid_component_scene_resilient
from src.api.schemas import PIDApproveRequest, PIDGenerateRequest
from src.framework.commands.executor import execute_command_sequence
from src.parametric.vessel.dwg_export import AutoCADNotRunningError


router = APIRouter(prefix="/api/pid", tags=["pid"])

TOKEN_TTL = timedelta(minutes=10)
_PID_CACHE: dict[str, dict[str, Any]] = {}


def _now() -> datetime:
    return datetime.now()


def _purge_expired_tokens() -> None:
    current_time = _now()
    expired_tokens = [
        token
        for token, entry in _PID_CACHE.items()
        if current_time - entry["created_at"] > TOKEN_TTL
    ]

    for token in expired_tokens:
        _PID_CACHE.pop(token, None)


def _short_error(exc: Exception, max_length: int = 2000) -> str:
    message = str(exc)
    if len(message) <= max_length:
        return message
    return message[:max_length] + "... [truncated]"


@router.post("/generate")
def pid_generate(request: PIDGenerateRequest):
    _purge_expired_tokens()

    prompt = request.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")

    try:
        planned = plan_and_render_pid_component_scene_resilient(
            prompt,
            drawing_style=request.drawing_style,
            allow_template_fallback=True,
            template_first=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_short_error(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"P&ID component planning failed: {type(exc).__name__}: {_short_error(exc)}",
        ) from exc

    component_scene = planned["component_scene"]
    command_sequence = planned["command_sequence"]
    token = uuid.uuid4().hex

    _PID_CACHE[token] = {
        "prompt": prompt,
        "drawing_style": request.drawing_style,
        "component_scene": component_scene,
        "command_sequence": command_sequence,
        "component_count": planned["component_count"],
        "planner_strategy": planned.get("planner_strategy"),
        "fallback_used": planned.get("fallback_used", False),
        "fallback_reason": planned.get("fallback_reason"),
        "template_name": planned.get("template_name"),
        "created_at": _now(),
    }

    return {
        "ok": True,
        "token": token,
        "prompt": prompt,
        "drawing_style": request.drawing_style,
        "title": component_scene.get("title"),
        "drawing_type": component_scene.get("drawing_type"),
        "component_count": planned["component_count"],
        "command_count": len(command_sequence.get("commands", [])),
        "component_scene": component_scene,
        "summary": command_sequence.get("summary"),
        "assumptions": component_scene.get("assumptions", []),
        "planner_strategy": planned.get("planner_strategy"),
        "fallback_used": planned.get("fallback_used", False),
        "fallback_reason": planned.get("fallback_reason"),
        "template_name": planned.get("template_name"),
    }


@router.post("/approve")
def pid_approve(request: PIDApproveRequest):
    _purge_expired_tokens()

    cached = _PID_CACHE.get(request.token)
    if cached is None:
        raise HTTPException(
            status_code=404,
            detail="P&ID token was not found or has expired. Generate again.",
        )

    command_sequence = cached["command_sequence"]

    try:
        import pythoncom

        pythoncom.CoInitialize()
        try:
            execution_result = execute_command_sequence(
                command_sequence,
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
                "then approve this P&ID again."
            ),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"P&ID execution failed: {type(exc).__name__}: {_short_error(exc)}",
        ) from exc

    ok = bool(execution_result.get("ok"))
    if ok:
        # A successful approve must consume its token — without this, the
        # exact same P&ID could be re-executed into AutoCAD an unlimited
        # number of times with one token before its TTL. A failed attempt
        # (ok=False, e.g. a partial
        # per-command failure) deliberately keeps the token so the caller
        # can retry, matching `/api/autocad/edit`'s and `/api/sketch/
        # approve`'s existing retry-on-failure convention.
        _PID_CACHE.pop(request.token, None)

    return {
        "ok": ok,
        "executed": True,
        "token": request.token,
        "execution_result": execution_result,
        "component_count": cached["component_count"],
        "command_count": len(command_sequence.get("commands", [])),
        "title": cached["component_scene"].get("title"),
    }

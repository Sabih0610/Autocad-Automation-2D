"""
FastAPI routes for Mode 2 sketch generation and approval.

The generated command cache is an in-memory dictionary with a 10-minute TTL.
This assumes a single-process uvicorn deployment; tokens are not shared across
multiple worker processes and are intentionally not persisted.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.ai.command_generator import generate_commands
from src.ai.command_orchestrator import (
    CommandOrchestrationError,
    generate_verified_command_sequence,
)
from src.ai.chunked_command_orchestrator import (
    ChunkedCommandOrchestrationError,
    generate_chunked_verified_command_sequence,
)
from src.api.routes._revertible import require_explicit_target, run_revertible
from src.framework.commands.executor import execute_command_sequence
from src.framework.commands.preview import render_preview_sequence
from src.parametric.vessel.dwg_export import AutoCADNotRunningError


router = APIRouter(prefix="/api/sketch", tags=["sketch"])

TOKEN_TTL = timedelta(minutes=10)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
PREVIEW_OUTPUT_DIR = OUTPUTS_DIR / "previews"

_token_cache: dict[str, dict[str, Any]] = {}


class SketchGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(..., min_length=1)
    run_verifier: bool = True
    create_preview: bool = True


class SketchApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(..., min_length=1)
    save: bool = True
    target_dwg_path: str | None = None
    use_active_document: bool = False


def _now() -> datetime:
    return datetime.now()


def _cleanup_expired_tokens() -> None:
    current_time = _now()
    expired_tokens = [
        token
        for token, entry in _token_cache.items()
        if current_time - entry["created_at"] > TOKEN_TTL
    ]

    for token in expired_tokens:
        _token_cache.pop(token, None)


def _store_sketch_job(
    token: str,
    prompt: str,
    command_sequence: dict,
    verifier_result: dict | None,
    preview_path: Path | None,
    repair_attempts_used: int = 0,
    repair_history: list[dict[str, Any]] | None = None,
    generation_strategy: str = "normal",
    task_plan: dict | None = None,
    chunk_count: int | None = None,
    chunk_results: list[dict[str, Any]] | None = None,
    chunk_repair_attempts_used: int | None = None,
) -> None:
    _token_cache[token] = {
        "prompt": prompt,
        "command_sequence": command_sequence,
        "verifier_result": verifier_result,
        "preview_path": preview_path,
        "repair_attempts_used": repair_attempts_used,
        "repair_history": repair_history or [],
        "generation_strategy": generation_strategy,
        "task_plan": task_plan,
        "chunk_count": chunk_count,
        "chunk_results": chunk_results or [],
        "chunk_repair_attempts_used": chunk_repair_attempts_used,
        "created_at": _now(),
    }


def _get_sketch_job(token: str) -> dict[str, Any] | None:
    _cleanup_expired_tokens()
    return _token_cache.get(token)


def _preview_path_for(token: str) -> Path:
    timestamp = _now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"sketch_preview_{timestamp}_{token[:8]}.dxf"
    return PREVIEW_OUTPUT_DIR / filename


def _preview_download_url(path: Path | None) -> str | None:
    if path is None:
        return None

    try:
        relative = path.resolve().relative_to(OUTPUTS_DIR.resolve())
    except ValueError:
        return None

    return f"/api/download/{relative.as_posix()}"


def _preview_reference(path: Path | None) -> str | None:
    if path is None:
        return None

    try:
        relative = path.resolve().relative_to(OUTPUTS_DIR.resolve())
    except ValueError:
        return str(path)

    return f"outputs/{relative.as_posix()}"


def _short_error(exc: Exception, max_length: int = 2000) -> str:
    message = str(exc)
    if len(message) <= max_length:
        return message
    return message[:max_length] + "... [truncated]"


def _looks_complex_prompt(prompt: str) -> bool:
    normalized = prompt.lower()
    words = normalized.replace("/", " ").replace("&", " ").split()

    if len(words) > 35:
        return True

    if "p&id" in normalized or "pid" in words:
        return True

    component_terms = [
        "vessel",
        "header",
        "branch",
        "valve",
        "valves",
        "instrument",
        "bubble",
        "pump",
        "tank",
        "pipe",
        "piping",
        "outlet",
        "inlet",
        "nozzle",
        "control valve",
        "heat exchanger",
    ]
    component_matches = [
        term
        for term in component_terms
        if term in normalized
    ]
    if len(component_matches) >= 3:
        return True

    quantity_words = [
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
    ]
    quantity_targets = [
        "valve",
        "valves",
        "branch",
        "branches",
        "instrument",
        "instruments",
        "bubble",
        "bubbles",
        "pump",
        "pumps",
        "tank",
        "tanks",
        "pipe",
        "pipes",
        "nozzle",
        "nozzles",
    ]
    for target in quantity_targets:
        if any(f"{number} {target}" in normalized for number in quantity_words):
            return True
        if any(f"{digit} {target}" in normalized for digit in "23456789"):
            return True

    complex_phrases = [
        "clean schematic layout",
        "layout with",
        "connect",
        "branches",
    ]
    return any(phrase in normalized for phrase in complex_phrases)


@router.post("/generate")
def sketch_generate(request: SketchGenerateRequest):
    _cleanup_expired_tokens()

    prompt = request.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")

    if request.run_verifier:
        task_plan = None
        chunk_count = None
        chunk_results = []
        chunk_repair_attempts_used = None

        if _looks_complex_prompt(prompt):
            generation_strategy = "chunked"
            try:
                orchestrated = generate_chunked_verified_command_sequence(
                    prompt,
                    max_chunks=6,
                    max_repair_attempts_per_chunk=1,
                    final_repair_attempts=1,
                    repair_on_approve_with_notes=False,
                )
                command_sequence = orchestrated["command_sequence"]
                verifier_result = orchestrated["verifier_result"]
                verifier_verdict = orchestrated["verifier_verdict"]
                repair_attempts_used = orchestrated["final_repair_attempts_used"]
                repair_history = orchestrated["repair_history"]
                task_plan = orchestrated.get("task_plan")
                chunk_count = orchestrated.get("chunk_count")
                chunk_results = orchestrated.get("chunk_results", [])
                chunk_repair_attempts_used = orchestrated.get("chunk_repair_attempts_used")
            except ChunkedCommandOrchestrationError as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Chunked command orchestration failed: {_short_error(exc)}",
                ) from exc
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Chunked command orchestration request failed: {_short_error(exc)}",
                ) from exc
            except Exception as exc:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Chunked command orchestration failed: "
                        f"{type(exc).__name__}: {_short_error(exc)}"
                    ),
                ) from exc
        else:
            generation_strategy = "normal"
            try:
                orchestrated = generate_verified_command_sequence(
                    prompt,
                    max_repair_attempts=2,
                    repair_on_approve_with_notes=False,
                )
                command_sequence = orchestrated["command_sequence"]
                verifier_result = orchestrated["verifier_result"]
                verifier_verdict = orchestrated["verifier_verdict"]
                repair_attempts_used = orchestrated["repair_attempts_used"]
                repair_history = orchestrated["repair_history"]
            except CommandOrchestrationError as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Command orchestration failed: {_short_error(exc)}",
                ) from exc
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Command orchestration request failed: {_short_error(exc)}",
                ) from exc
            except Exception as exc:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Command orchestration failed: "
                        f"{type(exc).__name__}: {_short_error(exc)}"
                    ),
                ) from exc
    else:
        generation_strategy = "direct"
        try:
            command_sequence = generate_commands(prompt)
        except ValueError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Command generation failed validation: {_short_error(exc)}",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Command generation failed: {type(exc).__name__}: {_short_error(exc)}",
            ) from exc

        verifier_result = None
        verifier_verdict = None
        repair_attempts_used = 0
        repair_history = []
        task_plan = None
        chunk_count = None
        chunk_results = []
        chunk_repair_attempts_used = None

    token = uuid.uuid4().hex
    preview_path = None

    if request.create_preview:
        preview_path = _preview_path_for(token)
        try:
            rendered_path = render_preview_sequence(command_sequence, str(preview_path))
            preview_path = Path(rendered_path)
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Preview generation failed: {type(exc).__name__}: {exc}",
            ) from exc

    _store_sketch_job(
        token=token,
        prompt=prompt,
        command_sequence=command_sequence,
        verifier_result=verifier_result,
        preview_path=preview_path,
        repair_attempts_used=repair_attempts_used,
        repair_history=repair_history,
        generation_strategy=generation_strategy,
        task_plan=task_plan,
        chunk_count=chunk_count,
        chunk_results=chunk_results,
        chunk_repair_attempts_used=chunk_repair_attempts_used,
    )

    return {
        "ok": True,
        "token": token,
        "summary": command_sequence.get("summary"),
        "estimated_drawing_type": command_sequence.get("estimated_drawing_type"),
        "assumptions": command_sequence.get("assumptions", []),
        "command_count": len(command_sequence.get("commands", [])),
        "verifier_result": verifier_result,
        "verifier_verdict": verifier_verdict,
        "repair_attempts_used": repair_attempts_used,
        "repair_history": repair_history,
        "generation_strategy": generation_strategy,
        "chunk_count": chunk_count,
        "chunk_repair_attempts_used": chunk_repair_attempts_used,
        "task_plan": task_plan,
        "preview_path": _preview_reference(preview_path),
        "preview_download_url": _preview_download_url(preview_path),
    }


@router.post("/approve")
def sketch_approve(request: SketchApproveRequest):
    entry = _get_sketch_job(request.token)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail="Sketch token was not found or has expired. Generate again.",
        )

    command_sequence = entry["command_sequence"]
    require_explicit_target(request.target_dwg_path, request.use_active_document)
    verifier_result = entry.get("verifier_result")
    preview_path = entry.get("preview_path")

    try:
        import pythoncom

        pythoncom.CoInitialize()
        try:
            execution_result, change_set_id, change_set_skipped_reason = run_revertible(
                request.target_dwg_path,
                f"Sketch: {command_sequence.get('summary') or 'generated drawing'}",
                lambda: execute_command_sequence(
                    command_sequence,
                    target_dwg_path=request.target_dwg_path,
                    save=request.save,
                ),
                save=request.save,
            )
        finally:
            pythoncom.CoUninitialize()
    except AutoCADNotRunningError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "AutoCAD is not running. Start AutoCAD with a drawing open, "
                "then approve this sketch again."
            ),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Sketch execution failed: {type(exc).__name__}: {exc}",
        ) from exc

    if execution_result.get("ok"):
        _token_cache.pop(request.token, None)

    return {
        "ok": bool(execution_result.get("ok")),
        "executed": bool(execution_result.get("ok")),
        "token": request.token,
        "execution_result": execution_result,
        "verifier_result": verifier_result,
        "verifier_verdict": (
            verifier_result.get("verdict")
            if isinstance(verifier_result, dict)
            else None
        ),
        "preview_download_url": _preview_download_url(preview_path),
        "change_set_id": change_set_id,
        "change_set_skipped_reason": change_set_skipped_reason,
    }

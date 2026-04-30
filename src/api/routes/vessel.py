"""
FastAPI routes for the Phase 21 vessel web workflow.

The extraction review cache is an in-memory Python dictionary with a 10-minute
TTL. This assumes a single-process uvicorn deployment; tokens are not shared
across multiple worker processes and are intentionally not persisted.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.ai.vessel_planner import (
    extracted_to_vessel_parameters,
    format_for_review,
    plan_vessel,
)
from src.parametric.vessel.dwg_export import AutoCADNotRunningError
from src.parametric.vessel.parameters import validate_parameters
from src.parametric.vessel.render import render_vessel


router = APIRouter(prefix="/api", tags=["vessel"])

TOKEN_TTL = timedelta(minutes=10)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
VESSEL_OUTPUT_DIR = OUTPUTS_DIR / "vessels"

_token_cache: dict[str, dict[str, Any]] = {}


class VesselExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(..., min_length=1)


class VesselConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(..., min_length=1)
    output_format: str = Field(default="dwg", pattern="^(dwg|dxf)$")


def _now() -> datetime:
    return datetime.now()


def _purge_expired_tokens() -> None:
    current_time = _now()
    expired_tokens = [
        token
        for token, entry in _token_cache.items()
        if current_time - entry["created_at"] > TOKEN_TTL
    ]

    for token in expired_tokens:
        _token_cache.pop(token, None)


def _safe_filename(value: str) -> str:
    return (
        str(value)
        .replace(" ", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
    )


def _output_path_for(vessel_tag: str, output_format: str) -> Path:
    timestamp = _now().strftime("%Y-%m-%d_%H-%M-%S")
    extension = output_format.lower().strip()
    filename = f"{_safe_filename(vessel_tag)}_web_{timestamp}.{extension}"
    return VESSEL_OUTPUT_DIR / filename


def _output_reference(path_value: str | None) -> str | None:
    if not path_value:
        return None

    path = Path(path_value).resolve()
    try:
        relative = path.relative_to(OUTPUTS_DIR.resolve())
    except ValueError:
        return str(path)

    return f"outputs/{relative.as_posix()}"


def _download_reference(path_value: str | None) -> str | None:
    if not path_value:
        return None

    path = Path(path_value).resolve()
    try:
        relative = path.relative_to(OUTPUTS_DIR.resolve())
    except ValueError:
        return None

    return f"/api/download/{relative.as_posix()}"


@contextmanager
def _dwg_com_context(enabled: bool):
    if not enabled:
        yield
        return

    import pythoncom

    pythoncom.CoInitialize()
    try:
        yield
    finally:
        pythoncom.CoUninitialize()


@router.post("/generate-vessel/extract")
def generate_vessel_extract(request: VesselExtractRequest):
    _purge_expired_tokens()

    prompt = request.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")

    try:
        extracted = plan_vessel(prompt)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Vessel parameter extraction failed: {type(exc).__name__}: {exc}",
        ) from exc

    token = uuid.uuid4().hex
    _token_cache[token] = {
        "extracted": extracted,
        "created_at": _now(),
        "prompt": prompt,
    }

    return {
        "ok": True,
        "token": token,
        "expires_in_seconds": int(TOKEN_TTL.total_seconds()),
        "prompt": prompt,
        "extracted": extracted,
        "formatted_review": format_for_review(extracted),
    }


@router.post("/generate-vessel/confirm")
def generate_vessel_confirm(request: VesselConfirmRequest):
    _purge_expired_tokens()

    entry = _token_cache.get(request.token)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail="Review token was not found or has expired. Extract parameters again.",
        )

    extracted = entry["extracted"]
    output_format = request.output_format.lower().strip()

    try:
        params = extracted_to_vessel_parameters(extracted)
        validation_errors = validate_parameters(params)

        if validation_errors:
            _token_cache.pop(request.token, None)
            return {
                "ok": False,
                "error_type": "validation_failed",
                "message": "Validation failed. Extract parameters again after correcting the prompt.",
                "errors": validation_errors,
                "extracted": extracted,
            }

        output_path = _output_path_for(params.tag, output_format)
        with _dwg_com_context(output_format == "dwg"):
            result = render_vessel(
                params=params,
                output_path=str(output_path),
                output_format=output_format,
            )

        if not result.get("ok"):
            _token_cache.pop(request.token, None)
            return {
                "ok": False,
                "error_type": "render_failed",
                "message": result.get("message") or "Vessel rendering failed.",
                "vessel_tag": params.tag,
                "format": output_format,
                "result": result,
                "extracted": extracted,
            }

        _token_cache.pop(request.token, None)

        output_file = _output_reference(result.get("path"))
        download_url = _download_reference(result.get("path"))
        dxf_intermediate = _output_reference(result.get("dxf_intermediate"))

        return {
            "ok": True,
            "message": result.get("message") or "Vessel drawing generated successfully.",
            "vessel_tag": params.tag,
            "format": result.get("format") or output_format,
            "path": result.get("path"),
            "output_file": output_file,
            "download_url": download_url,
            "dxf_intermediate_file": dxf_intermediate,
            "dxf_intermediate_download_url": _download_reference(
                result.get("dxf_intermediate")
            ),
            "scale": result.get("scale"),
            "sheet": result.get("sheet"),
            "extracted": extracted,
        }
    except AutoCADNotRunningError as exc:
        return {
            "ok": False,
            "error_type": "autocad_not_running",
            "message": (
                "AutoCAD is not running. Start AutoCAD with any drawing open, "
                "then click Generate Drawing again."
            ),
            "detail": str(exc),
            "token": request.token,
            "extracted": extracted,
        }
    except Exception as exc:
        _token_cache.pop(request.token, None)
        return {
            "ok": False,
            "error_type": "generation_failed",
            "message": f"Vessel generation failed: {type(exc).__name__}: {exc}",
            "extracted": extracted,
        }

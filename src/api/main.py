from contextvars import ContextVar
from functools import wraps
import inspect
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.routing import APIRoute, request_response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.api.routes.autocad_edit import router as autocad_edit_router
from src.api.routes.autocad_inspect import router as autocad_inspect_router
from src.api.routes.consistency import router as consistency_router
from src.api.routes.line_list import router as line_list_router
from src.api.routes.pid import router as pid_router
from src.api.routes.place_symbol import router as place_symbol_router
from src.api.routes.sketch import router as sketch_router
from src.api.routes.title_block import router as title_block_router
from src.api.routes.vessel import router as vessel_router
from src.logging.jobs import get_job, list_recent_jobs, log_job_end, log_job_start


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_AUDIT_BYTES = 100 * 1024
AUDIT_ROUTE_MAP = {
    "/api/title-block-update": "title_block_update",
    "/api/line-list-extract": "line_list_extract",
    "/api/place-symbol": "place_symbol",
    "/api/consistency-check": "consistency_check",
    "/api/generate-vessel/extract": "generate_vessel_extract",
    "/api/generate-vessel/confirm": "generate_vessel_confirm",
    "/api/sketch/generate": "sketch_generate",
    "/api/sketch/approve": "sketch_approve",
    "/api/autocad/inspect": "autocad_inspect",
    "/api/autocad/edit": "autocad_edit",
    "/api/pid/generate": "pid_generate",
    "/api/pid/approve": "pid_approve",
}
CURRENT_AUDIT_JOB_ID: ContextVar[str | None] = ContextVar("current_audit_job_id", default=None)
CURRENT_AUDIT_COMPLETED: ContextVar[bool] = ContextVar("current_audit_completed", default=False)


app = FastAPI(
    title="AutoCAD AI Automation",
    description="Thin FastAPI wrapper over the existing AutoCAD AI use case modules.",
)

app.include_router(title_block_router)
app.include_router(line_list_router)
app.include_router(place_symbol_router)
app.include_router(consistency_router)
app.include_router(vessel_router)
app.include_router(sketch_router)
app.include_router(autocad_inspect_router)
app.include_router(autocad_edit_router)
app.include_router(pid_router)


def _truncate_payload(payload: Any) -> Any:
    try:
        raw = json.dumps(payload, default=str).encode("utf-8")
    except Exception:
        raw = str(payload).encode("utf-8", errors="replace")

    if len(raw) > MAX_AUDIT_BYTES:
        return {
            "_truncated": True,
            "size_bytes": len(raw),
        }

    return payload


def _extract_ai_output(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    output = {}

    if payload.get("planned_spec") is not None:
        output["planned_spec"] = payload["planned_spec"]

    if payload.get("ai_explanation") is not None:
        output["ai_explanation"] = payload["ai_explanation"]

    if payload.get("extracted") is not None:
        output["extracted"] = payload["extracted"]

    return output or None


def _status_from_result(payload: Any) -> str:
    if isinstance(payload, dict) and payload.get("ok") is False:
        return "error"
    return "ok"


def _decode_request_payload(body: bytes, content_type: str) -> Any:
    if not body:
        return {}

    if len(body) > MAX_AUDIT_BYTES:
        return {
            "_truncated": True,
            "size_bytes": len(body),
        }

    if "application/json" not in content_type.lower():
        return {
            "_unsupported": True,
            "content_type": content_type,
            "size_bytes": len(body),
        }

    try:
        return json.loads(body.decode("utf-8"))
    except Exception:
        return {
            "_invalid_json": True,
            "size_bytes": len(body),
        }
def _log_wrapped_route_success(result: Any) -> None:
    job_id = CURRENT_AUDIT_JOB_ID.get()
    if not job_id:
        return

    payload = _truncate_payload(result)
    result_data = payload if isinstance(payload, dict) else {"value": payload}
    log_job_end(
        job_id,
        status=_status_from_result(payload),
        result_data=result_data,
        ai_output=_extract_ai_output(payload),
        error_message=(
            payload.get("detail")
            if isinstance(payload, dict)
            else None
        ),
    )
    CURRENT_AUDIT_COMPLETED.set(True)


def _log_wrapped_route_error(exc: Exception) -> None:
    job_id = CURRENT_AUDIT_JOB_ID.get()
    if not job_id:
        return
    log_job_end(
        job_id,
        status="error",
        error_message=str(exc),
    )
    CURRENT_AUDIT_COMPLETED.set(True)


def _install_audit_wrappers() -> None:
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path not in AUDIT_ROUTE_MAP:
            continue

        original_endpoint = route.endpoint

        if inspect.iscoroutinefunction(original_endpoint):
            @wraps(original_endpoint)
            async def async_wrapper(*args, __original=original_endpoint, **kwargs):
                try:
                    result = await __original(*args, **kwargs)
                except Exception as exc:
                    _log_wrapped_route_error(exc)
                    raise
                _log_wrapped_route_success(result)
                return result

            wrapped_endpoint = async_wrapper
        else:
            @wraps(original_endpoint)
            def sync_wrapper(*args, __original=original_endpoint, **kwargs):
                try:
                    result = __original(*args, **kwargs)
                except Exception as exc:
                    _log_wrapped_route_error(exc)
                    raise
                _log_wrapped_route_success(result)
                return result

            wrapped_endpoint = sync_wrapper

        route.endpoint = wrapped_endpoint
        route.dependant.call = wrapped_endpoint
        route.app = request_response(route.get_route_handler())


class AuditJobMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        use_case = AUDIT_ROUTE_MAP.get(path)
        if use_case is None:
            await self.app(scope, receive, send)
            return

        request_body = b""
        more_body = True

        while more_body:
            message = await receive()
            if message["type"] != "http.request":
                continue
            request_body += message.get("body", b"")
            more_body = message.get("more_body", False)

        body_sent = False

        async def replay_receive():
            nonlocal body_sent
            if body_sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            body_sent = True
            return {"type": "http.request", "body": request_body, "more_body": False}

        request_headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        request_payload = _truncate_payload(
            _decode_request_payload(
                request_body,
                request_headers.get("content-type", ""),
            )
        )
        job_id = log_job_start(
            use_case=use_case,
            source="api",
            request_data=request_payload if isinstance(request_payload, dict) else {"value": request_payload},
            user_agent=request_headers.get("user-agent", ""),
        )
        job_id_token = CURRENT_AUDIT_JOB_ID.set(job_id)
        completed_token = CURRENT_AUDIT_COMPLETED.set(False)

        async def send_wrapper(message):
            await send(message)

        try:
            await self.app(scope, replay_receive, send_wrapper)
        except Exception as exc:
            if not CURRENT_AUDIT_COMPLETED.get():
                log_job_end(
                    job_id,
                    status="error",
                    error_message=str(exc),
                )
            raise
        finally:
            CURRENT_AUDIT_JOB_ID.reset(job_id_token)
            CURRENT_AUDIT_COMPLETED.reset(completed_token)


app.add_middleware(AuditJobMiddleware)
_install_audit_wrappers()


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok"}


@app.get("/api/autocad-status", tags=["system"])
def autocad_status():
    import pythoncom

    pythoncom.CoInitialize()
    try:
        import win32com.client

        acad = win32com.client.GetActiveObject("AutoCAD.Application")
        status = {
            "reachable": True,
            "caption": getattr(acad, "Caption", None),
            "active_drawing": None,
        }

        try:
            doc = acad.ActiveDocument
            status["active_drawing"] = getattr(doc, "Name", None)
        except Exception:
            status["active_drawing"] = None

        return status
    except Exception as exc:
        return {
            "reachable": False,
            "caption": None,
            "active_drawing": None,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        pythoncom.CoUninitialize()


@app.get("/api/download/{filename:path}", tags=["system"])
def download_output(filename: str):
    if (
        not filename
        or ".." in filename
        or Path(filename).is_absolute()
    ):
        raise HTTPException(status_code=400, detail="Invalid filename.")

    output_path = (OUTPUTS_DIR / filename).resolve()
    try:
        output_path.relative_to(OUTPUTS_DIR.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid filename.") from exc

    if not output_path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")

    return FileResponse(
        path=output_path,
        filename=output_path.name,
        media_type="application/octet-stream",
    )


@app.get("/api/jobs", tags=["jobs"])
def jobs_history(
    limit: int = Query(default=50, ge=1, le=200),
    use_case: str | None = Query(default=None),
    status: str | None = Query(default=None),
):
    return list_recent_jobs(limit=limit, use_case=use_case, status=status)


@app.get("/api/jobs/{job_id}", tags=["jobs"])
def jobs_detail(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


app.mount("/outputs", StaticFiles(directory=str(OUTPUTS_DIR), check_dir=False), name="outputs")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR), html=True), name="static-files")
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

import sqlite3
from fastapi import APIRouter, HTTPException, Query
from jsonschema import ValidationError
from pydantic import BaseModel, ConfigDict, Field
from src.cad.changes import list_change_sets
from src.cad.orchestrator import ProjectOrchestrator, get_multi_file_job
from src.cad.scanner import scan_project, list_drawings
from src.storage.entity_repository import find_by_tag
from src.storage.project_repository import register_project, list_projects, get_project
from src.storage.spatial import SpatialIndex

router = APIRouter(prefix="/api/projects", tags=["projects"])
SPATIAL = SpatialIndex()


def orchestrator():
    return ProjectOrchestrator()


def respond(call):
    try:
        return call()
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValueError, OSError, sqlite3.IntegrityError, sqlite3.OperationalError, ValidationError) as exc:
        raise HTTPException(409, str(exc)) from exc


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    root_path: str = Field(min_length=1)


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=4000)
    tag: str | None = Field(default=None, max_length=200)
    drawing_id: str | None = None


@router.get("")
def projects():
    return {"projects": list_projects()}


@router.post("")
def register(request: RegisterRequest):
    return respond(lambda: get_project(register_project(request.name, request.root_path)))


@router.post("/{project_id}/scan")
def scan(project_id: str):
    return respond(lambda: scan_project(project_id))


@router.get("/{project_id}/drawings")
def drawings(project_id: str):
    return respond(lambda: {"drawings": list_drawings(project_id)})


@router.get("/{project_id}/entities")
def entities(project_id: str, tag: str = Query(min_length=1)):
    return respond(lambda: {"entities": find_by_tag(project_id, tag)})


@router.get("/{project_id}/nearby")
def nearby(project_id: str, tag: str, radius_mm: float = Query(default=100, ge=0)):
    return respond(lambda: {"results": [{"entity": entity, "nearby": SPATIAL.nearby(entity["entity_id"], radius_mm)}
                                       for entity in find_by_tag(project_id, tag)]})


@router.get("/{project_id}/change-sets")
def changes(project_id: str):
    return {"change_sets": list_change_sets(project_id)}


@router.post("/{project_id}/plan")
def plan(project_id: str, request: PlanRequest):
    return respond(lambda: orchestrator().plan(project_id, request.prompt, tag=request.tag, drawing_id=request.drawing_id))


@router.get("/jobs/{job_id}")
def job(job_id: str):
    return respond(lambda: get_multi_file_job(job_id))


@router.post("/jobs/{job_id}/execute")
def execute(job_id: str):
    return respond(lambda: orchestrator().execute(job_id))

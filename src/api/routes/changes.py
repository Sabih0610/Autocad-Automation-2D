import sqlite3
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from src.cad.changes import ChangeManager, get_change_set
from src.cad.write_queue import WRITE_QUEUE
from jsonschema import ValidationError

router = APIRouter(prefix="/api/change-sets", tags=["changesets"])


def manager():
    return ChangeManager()


class ApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str
    summary: str = Field(min_length=1)
    operations: list[dict] = Field(min_length=1, max_length=1000)


def respond(call):
    try:
        return call()
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValueError, OSError, sqlite3.IntegrityError, sqlite3.OperationalError, ValidationError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("")
def apply(request: ApplyRequest):
    return respond(lambda: WRITE_QUEUE.run(manager().apply, request.project_id, request.operations, request.summary))


@router.get("/{change_id}")
def detail(change_id: str):
    return respond(lambda: get_change_set(change_id))


@router.post("/{change_id}/keep")
def keep(change_id: str):
    return respond(lambda: WRITE_QUEUE.run(manager().keep, change_id))


@router.post("/{change_id}/revert")
def revert(change_id: str):
    return respond(lambda: WRITE_QUEUE.run(manager().revert, change_id))

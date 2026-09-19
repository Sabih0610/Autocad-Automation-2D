from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .database import connection


def now():
    return datetime.now(timezone.utc).isoformat()


def register_project(name: str, root_path: str) -> dict:
    root = Path(root_path).expanduser().resolve(strict=True)
    if not root.is_dir() or not name.strip():
        raise ValueError("A project requires a non-empty name and an existing folder")
    project = dict(project_id=uuid4().hex, name=name.strip(), root_path=str(root),
                   status="active", created_at=now(), updated_at=now())
    with connection() as conn:
        conn.execute("INSERT INTO projects VALUES (:project_id,:name,:root_path,:status,:created_at,:updated_at)", project)
    return project


def list_projects() -> list[dict]:
    with connection() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM projects ORDER BY created_at, project_id")]


def get_project(project_id: str) -> dict:
    with connection() as conn:
        row = conn.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
    if row is None:
        raise KeyError(f"Unknown project: {project_id}")
    return dict(row)

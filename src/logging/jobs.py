from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime
from typing import Any

from src.logging.db import get_connection


def _warn(message: str) -> None:
    print(f"WARNING: audit logging failed: {message}", file=sys.stderr)


def _json_dumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, default=str)


def _json_loads(value: str | None) -> Any:
    if value is None:
        return None
    return json.loads(value)


def _timestamp_now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def _parse_job_row(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "job_id": row["job_id"],
        "timestamp_start": row["timestamp_start"],
        "timestamp_end": row["timestamp_end"],
        "duration_seconds": row["duration_seconds"],
        "source": row["source"],
        "use_case": row["use_case"],
        "request_data": _json_loads(row["request_data"]),
        "ai_output": _json_loads(row["ai_output"]),
        "result_data": _json_loads(row["result_data"]),
        "status": row["status"],
        "error_message": row["error_message"],
        "user_agent": row["user_agent"],
    }


def log_job_start(
    use_case: str,
    source: str,
    request_data: dict,
    user_agent: str = "",
) -> str:
    job_id = uuid.uuid4().hex
    timestamp_start = _timestamp_now()

    try:
        connection = get_connection()
        try:
            connection.execute(
                """
                INSERT INTO jobs (
                    job_id,
                    timestamp_start,
                    source,
                    use_case,
                    request_data,
                    status,
                    user_agent
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    timestamp_start,
                    source,
                    use_case,
                    _json_dumps(request_data or {}),
                    "started",
                    user_agent or "",
                ),
            )
            connection.commit()
        finally:
            connection.close()
    except Exception as exc:
        _warn(f"log_job_start for {use_case}: {type(exc).__name__}: {exc}")

    return job_id


def log_job_end(
    job_id: str,
    status: str,
    result_data: dict | None = None,
    ai_output: dict | None = None,
    error_message: str | None = None,
) -> None:
    timestamp_end = _timestamp_now()

    try:
        connection = get_connection()
        try:
            row = connection.execute(
                "SELECT timestamp_start FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()

            duration_seconds = None
            if row is not None:
                started_at = datetime.fromisoformat(row["timestamp_start"])
                ended_at = datetime.fromisoformat(timestamp_end)
                duration_seconds = round((ended_at - started_at).total_seconds(), 3)

            connection.execute(
                """
                UPDATE jobs
                SET
                    timestamp_end = ?,
                    duration_seconds = ?,
                    ai_output = ?,
                    result_data = ?,
                    status = ?,
                    error_message = ?
                WHERE job_id = ?
                """,
                (
                    timestamp_end,
                    duration_seconds,
                    _json_dumps(ai_output),
                    _json_dumps(result_data),
                    status,
                    error_message,
                    job_id,
                ),
            )
            connection.commit()
        finally:
            connection.close()
    except Exception as exc:
        _warn(f"log_job_end for {job_id}: {type(exc).__name__}: {exc}")


def list_recent_jobs(
    limit: int = 50,
    use_case: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    try:
        connection = get_connection()
        try:
            clauses = []
            params: list[Any] = []

            if use_case:
                clauses.append("use_case = ?")
                params.append(use_case)

            if status:
                clauses.append("status = ?")
                params.append(status)

            where_clause = ""
            if clauses:
                where_clause = "WHERE " + " AND ".join(clauses)

            params.append(limit)

            rows = connection.execute(
                f"""
                SELECT *
                FROM jobs
                {where_clause}
                ORDER BY timestamp_start DESC
                LIMIT ?
                """,
                params,
            ).fetchall()

            return [_parse_job_row(row) for row in rows]
        finally:
            connection.close()
    except Exception as exc:
        _warn(f"list_recent_jobs: {type(exc).__name__}: {exc}")
        return []


def get_job(job_id: str) -> dict[str, Any] | None:
    try:
        connection = get_connection()
        try:
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()

            if row is None:
                return None

            return _parse_job_row(row)
        finally:
            connection.close()
    except Exception as exc:
        _warn(f"get_job for {job_id}: {type(exc).__name__}: {exc}")
        return None

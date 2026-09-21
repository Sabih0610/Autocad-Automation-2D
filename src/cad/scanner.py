"""On-demand, incremental offline scans. Workers never touch SQLite or COM."""
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
import hashlib
import os
from pathlib import Path
from uuid import uuid4

from src.cad.extractor import DXFExtractor
from src.cad.extractor.oda import ODAConverter
from src.storage.database import connection
from src.storage.project_repository import get_project, now
from src.storage.entity_repository import store_snapshot
from src.cad.locks import serialized


def file_hash(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stamp(path):
    stat = Path(path).stat()
    return stat.st_size, str(stat.st_mtime_ns)


def configured_extractor():
    executable = os.getenv("ODA_FILE_CONVERTER")
    return DXFExtractor(ODAConverter(executable) if executable else None)


def _extract_file(factory, path, expected_stamp):
    snapshot = factory().extract(path)
    if stamp(path) != expected_stamp:
        raise RuntimeError("File changed during extraction; rescan required")
    return snapshot


def list_drawings(project_id):
    get_project(project_id)
    with connection() as conn:
        return [dict(row) for row in conn.execute(
            """SELECT d.*,m.drawing_id IS NOT NULL AS indexed FROM drawings d
            LEFT JOIN drawing_metadata m ON m.drawing_id=d.drawing_id
            WHERE project_id=? ORDER BY path""", (project_id,))]


def _store_snapshot(conn, drawing_id, snapshot):
    store_snapshot(conn, drawing_id, snapshot)


@serialized
def scan_project(project_id, *, extractor_factory=configured_extractor, max_workers=None,
                  pool_factory=ProcessPoolExecutor):
    project = get_project(project_id)
    if project["status"] != "active":
        raise ValueError("Cannot scan an archived project")
    root = Path(project["root_path"]).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Project root is no longer a directory")
    workers = max_workers if max_workers is not None else min(4, os.cpu_count() or 1)
    if workers < 1:
        raise ValueError("max_workers must be positive")
    existing = {row["path"]: row for row in list_drawings(project_id)}
    # Exclude any "backups" subfolder found *within* the scanned project tree
    # (e.g. this repo's own `backups/` and `src/backups/` both matched this
    # when the project root was the repo itself) — checked relative to `root`
    # only, so a project whose own root path happens to sit under a
    # "backups"-named ancestor directory (outside the scan) isn't wrongly
    # excluded wholesale.
    paths = sorted({p.resolve() for p in root.rglob("*") if p.is_file()
                    and p.suffix.lower() in {".dwg", ".dxf"}
                    and p.resolve().is_relative_to(root)
                    and "backups" not in {part.lower() for part in p.resolve().relative_to(root).parts}})
    report = dict(discovered=len(paths), extracted=0, skipped=0, errors=[])
    pending = []
    for path in paths:
        row = existing.get(str(path))
        drawing_id = row["drawing_id"] if row else uuid4().hex
        if not row:
            with connection() as conn:
                conn.execute("INSERT INTO drawings (drawing_id,project_id,path,filename) VALUES (?,?,?,?)",
                             (drawing_id, project_id, str(path), path.name))
        try:
            signature = stamp(path)
            if row and row["indexed"] and row["scan_status"] == "scanned" and signature == (row["file_size"], row["file_modified_at"]):
                report["skipped"] += 1
                continue
            digest = file_hash(path)
            if stamp(path) != signature:
                raise RuntimeError("File changed while hashing; rescan required")
            if row and row["indexed"] and row["scan_status"] == "scanned" and digest == row["file_hash"]:
                with connection() as conn:
                    conn.execute("UPDATE drawings SET file_size=?,file_modified_at=? WHERE drawing_id=?",
                                 (*signature, drawing_id))
                report["skipped"] += 1
                continue
            with connection() as conn:
                conn.execute("UPDATE drawings SET scan_status='pending',scan_error=NULL WHERE drawing_id=?", (drawing_id,))
            pending.append((drawing_id, path, signature, digest))
        except Exception as exc:
            _record_error(drawing_id, path, exc, report)

    def complete(item, snapshot=None, error=None):
        drawing_id, path, signature, digest = item
        try:
            if error:
                raise error
            with connection() as conn:
                _store_snapshot(conn, drawing_id, snapshot)
                conn.execute("""UPDATE drawings SET file_size=?,file_modified_at=?,file_hash=?,
                    last_scanned_at=?,scan_status='scanned',scan_error=NULL WHERE drawing_id=?""",
                             (*signature, digest, now(), drawing_id))
            report["extracted"] += 1
        except Exception as exc:
            _record_error(drawing_id, path, exc, report)

    if workers == 1:
        for item in pending:
            try:
                snapshot = _extract_file(extractor_factory, item[1], item[2])
            except Exception as exc:
                complete(item, error=exc)
            else:
                complete(item, snapshot=snapshot)
    elif pending:
        # If a worker process crashes outright (not a normal exception raised
        # *inside* `_extract_file`, but the worker dying — e.g. a native
        # crash), every other still-pending future in that same pool also
        # raises BrokenProcessPool when `.result()` is called, even though
        # only the one file being processed when the crash happened is
        # actually implicated. Left unhandled, that previously marked every
        # *other* pending file as errored too — collateral damage for files
        # that were never even attempted. Retry only the files that never
        # got a result, in a fresh pool, instead of blaming the whole batch.
        remaining = list(pending)
        restarts = 0
        max_restarts = len(pending)
        while remaining:
            finished_this_round = set()
            try:
                with pool_factory(max_workers=workers) as pool:
                    futures = {pool.submit(_extract_file, extractor_factory, item[1], item[2]): item
                               for item in remaining}
                    for future in as_completed(futures):
                        item = futures[future]
                        try:
                            snapshot = future.result()
                        except BrokenProcessPool:
                            raise
                        except Exception as exc:
                            complete(item, error=exc)
                            finished_this_round.add(item)
                        else:
                            complete(item, snapshot=snapshot)
                            finished_this_round.add(item)
            except BrokenProcessPool as exc:
                remaining = [item for item in remaining if item not in finished_this_round]
                restarts += 1
                if restarts > max_restarts:
                    # Safety valve: something is crashing every fresh pool
                    # (not just one bad file) — stop restarting forever.
                    for item in remaining:
                        complete(item, error=RuntimeError(f"Worker process crashed repeatedly: {exc}"))
                    remaining = []
                continue
            remaining = []
    discovered = {str(path) for path in paths}
    for path, row in existing.items():
        if path not in discovered:
            _record_error(row["drawing_id"], path, FileNotFoundError("Drawing no longer exists under the project root"), report)
    return report


def _record_error(drawing_id, path, error, report):
    message = f"{type(error).__name__}: {error}"
    with connection() as conn:
        conn.execute("UPDATE drawings SET scan_status='error',scan_error=? WHERE drawing_id=?", (message, drawing_id))
    report["errors"].append(dict(path=str(path), error=message))

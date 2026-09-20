"""Additive schema; the audit jobs table and its connection API stay unchanged."""
from contextlib import contextmanager
from pathlib import Path

from src.logging import db
from .spatial import ensure_spatial
from .relationship_schema import ensure_relationship_targets

SCHEMA = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8-sig")


@contextmanager
def connection():
    conn = db.get_connection()
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA)
        ensure_relationship_targets(conn)
        ensure_spatial(conn)
        conn.executescript("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_project_root ON projects(root_path);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_drawing_path ON drawings(project_id, path);
            CREATE INDEX IF NOT EXISTS idx_entity_tag ON entities(tag, drawing_id);
            CREATE INDEX IF NOT EXISTS idx_entity_drawing ON entities(drawing_id);
            CREATE INDEX IF NOT EXISTS idx_relationship_target ON relationships(target_entity_id);
        """)
        with conn:
            yield conn
    finally:
        conn.close()

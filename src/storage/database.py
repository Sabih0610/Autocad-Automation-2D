"""Additive schema; the audit jobs table and its connection API stay unchanged."""
from contextlib import contextmanager
from pathlib import Path

from src.logging import db
from .spatial import ensure_spatial
from .changeset_schema import ensure_changeset_file_targets
from .drawing_metadata_schema import ensure_drawing_metadata_tables
from .index_surface_schema import (
    ensure_index_surface,
)
from .relationship_schema import ensure_relationship_targets

SCHEMA = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8-sig")


def _is_initialized(conn) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='drawings'"
    ).fetchone() is not None


@contextmanager
def connection():
    conn = db.get_connection()
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        # `SCHEMA` and the index script below are pure static DDL (CREATE
        # ... IF NOT EXISTS, no migration logic of their own) — replaying
        # ~20 such statements on every single connection() call is wasted
        # work once they already exist, so skip them once `drawings`
        # (created by SCHEMA itself) is present. A DB whose file was
        # deleted or never initialized still gets them, since this check
        # re-reads actual DB state, not a cached flag.
        if not _is_initialized(conn):
            conn.executescript(SCHEMA)
            conn.executescript("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_project_root ON projects(root_path);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_drawing_path ON drawings(project_id, path);
                CREATE INDEX IF NOT EXISTS idx_entity_drawing ON entities(drawing_id);
                CREATE INDEX IF NOT EXISTS idx_relationship_target ON relationships(target_entity_id);
            """)
        # Unlike the block above, these two are self-checking migrations,
        # not plain DDL — `ensure_relationship_targets` detects and repairs
        # a `relationships` table left in the pre-migration shape, and
        # `ensure_spatial` re-derives `spatial_index` if it's ever missing.
        # Each already guards its own work behind a single cheap query, so
        # unlike SCHEMA there's no expensive replay to skip, and skipping
        # the call entirely would stop them from ever self-healing.
        ensure_relationship_targets(
            conn
        )

        ensure_changeset_file_targets(
            conn
        )

        ensure_drawing_metadata_tables(
            conn
        )

        ensure_index_surface(
            conn
        )

        ensure_spatial(
            conn
        )
        # Cleanup for objects an older version of this code could have left
        # behind on disk: a case-sensitive tag index made redundant by
        # schema.sql's idx_entity_tag_nocase (entities.tag is only ever
        # queried COLLATE NOCASE), and two AFTER UPDATE triggers on
        # entity_geometry that can never fire (that table is always written
        # via delete-then-insert, never UPDATE — see
        # entity_repository.store_snapshot). Kept outside the block above,
        # and run every call, so they clean up a database that was already
        # initialized before this fix existed, not just a fresh one.
        conn.execute("DROP INDEX IF EXISTS idx_entity_tag")
        conn.execute("DROP TRIGGER IF EXISTS geometry_version_update")
        conn.execute("DROP TRIGGER IF EXISTS spatial_update")
        # Hand the caller a connection with no transaction already open.
        # Initialising a brand-new database runs `ensure_spatial`'s backfill
        # INSERT, which implicitly opens one; a caller that then issues its
        # own `BEGIN IMMEDIATE` — as ChangeManager.apply and apply_file_edit
        # both do to claim their targets — failed with "cannot start a
        # transaction within a transaction". It only ever bit whichever call
        # happened to be the first to touch a fresh database, which is why it
        # stayed hidden.
        if conn.in_transaction:
            conn.commit()
        with conn:
            yield conn
    finally:
        conn.close()

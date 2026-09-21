from src.storage import database


def _trigger_names(conn):
    return {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger'")}


def _index_names(conn):
    return {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'")}


def test_dead_update_triggers_on_entity_geometry_are_not_created():
    """entity_geometry rows are always written via delete-then-insert (see
    entity_repository.store_snapshot), never UPDATE, so an AFTER UPDATE
    trigger on that table can never fire. Both `geometry_version_update`
    (schema.sql) and `spatial_update` (spatial.py) were exactly that."""
    with database.connection() as conn:
        triggers = _trigger_names(conn)
    assert "geometry_version_update" not in triggers
    assert "spatial_update" not in triggers
    # The INSERT/DELETE siblings of each dead trigger are real and stay.
    with database.connection() as conn:
        triggers = _trigger_names(conn)
    assert {"geometry_version_insert", "geometry_version_delete", "spatial_insert", "spatial_delete"} <= triggers


def test_dead_update_triggers_are_dropped_from_a_database_created_before_the_fix():
    """A database created by an older version of this code still has the
    dead triggers physically present on disk. `connection()` must clean
    them up, not just stop creating new ones."""
    with database.connection() as conn:
        conn.executescript("""
            CREATE TRIGGER geometry_version_update AFTER UPDATE ON entity_geometry BEGIN
                UPDATE spatial_version SET version=version+1 WHERE id=1;
            END;
            CREATE TRIGGER spatial_update AFTER UPDATE ON entity_geometry BEGIN
                UPDATE spatial_version SET version=version+1 WHERE id=1;
            END;
        """)
        assert {"geometry_version_update", "spatial_update"} <= _trigger_names(conn)

    with database.connection() as conn:
        triggers = _trigger_names(conn)
    assert "geometry_version_update" not in triggers
    assert "spatial_update" not in triggers


def test_case_sensitive_tag_index_is_not_created_and_is_dropped_if_present():
    """entities.tag is only ever queried COLLATE NOCASE (entity_repository.py),
    so idx_entity_tag (case-sensitive) never accelerates a real lookup —
    only idx_entity_tag_nocase does. The redundant one should not exist,
    on a fresh database or one left over from before this fix."""
    with database.connection() as conn:
        assert "idx_entity_tag" not in _index_names(conn)
        assert "idx_entity_tag_nocase" in _index_names(conn)

    with database.connection() as conn:
        conn.execute("CREATE INDEX idx_entity_tag ON entities(tag, drawing_id)")
        assert "idx_entity_tag" in _index_names(conn)

    with database.connection() as conn:
        assert "idx_entity_tag" not in _index_names(conn)


def test_connection_skips_redundant_schema_reexecution_once_initialized(monkeypatch):
    """`SCHEMA` (schema.sql) is pure static DDL with no migration logic of
    its own — replaying it on every single `connection()` call is wasted
    work once it already exists on disk. It should only run the first
    time a given database is touched. Proven by appending a statement
    with no `IF NOT EXISTS` guard: replaying it a second time would raise
    "table already exists"."""
    monkeypatch.setattr(database, "SCHEMA", database.SCHEMA + "\nCREATE TABLE reexecution_marker (x);\n")

    with database.connection():
        pass  # first call: creates `drawings` (and `reexecution_marker`)

    with database.connection():
        pass  # would raise sqlite3.OperationalError if SCHEMA replayed here
    with database.connection():
        pass


def test_connection_still_self_heals_relationship_schema_on_every_call(tmp_path):
    """Unlike SCHEMA itself, `ensure_relationship_targets` is a
    self-checking migration, not plain idempotent DDL — it must run on
    every `connection()` call (not just the first, pre-`drawings`-table
    one) so it can detect and repair a `relationships` table left in the
    legacy pre-migration shape, however that happened. This is a targeted
    regression test for the item-17 "skip redundant DDL" fix above:
    an earlier version of it gated this call behind the same
    `drawings`-table check as SCHEMA and broke exactly this self-healing."""
    from src.logging import db as jobs_db

    with database.connection() as conn:
        conn.execute("INSERT INTO projects VALUES ('p1','Plant','/x','active','t','t')")
        conn.execute("INSERT INTO drawings VALUES ('d1','p1','/x/a.dxf','a.dxf',NULL,NULL,NULL,NULL,'pending',NULL)")
        conn.execute("INSERT INTO entities VALUES ('e1','d1','H1','P-1','LINE','0')")

    with jobs_db.get_connection() as conn:
        conn.execute("DROP TABLE relationships")
        conn.execute("""CREATE TABLE relationships (
            source_entity_id TEXT NOT NULL REFERENCES entities(entity_id),
            relationship_type TEXT NOT NULL,
            target_entity_id TEXT NOT NULL REFERENCES entities(entity_id),
            PRIMARY KEY (source_entity_id,relationship_type,target_entity_id))""")

    with database.connection() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(relationships)")}
        assert "target_drawing_id" in columns
        appears_in = conn.execute(
            "SELECT count(*) FROM relationships WHERE source_entity_id='e1' AND relationship_type='appears_in'"
        ).fetchone()[0]
    assert appears_in == 1

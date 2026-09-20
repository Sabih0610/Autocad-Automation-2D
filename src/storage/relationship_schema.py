"""Upgrade entity-only relationship edges to also target drawings."""


def ensure_relationship_targets(conn):
    columns = {row[1] for row in conn.execute("PRAGMA table_info(relationships)")}
    if "target_drawing_id" not in columns:
        # A legacy appears_in edge linked equal tags across drawings. Keep that
        # information as represented_in and add actual entity-to-drawing edges.
        conn.execute("BEGIN IMMEDIATE")
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(relationships)")}
            if "target_drawing_id" not in columns:
                conn.execute("ALTER TABLE relationships RENAME TO relationships_legacy")
                conn.execute("""CREATE TABLE relationships (
                    source_entity_id TEXT NOT NULL REFERENCES entities(entity_id),
                    relationship_type TEXT NOT NULL,
                    target_entity_id TEXT REFERENCES entities(entity_id),
                    target_drawing_id TEXT REFERENCES drawings(drawing_id),
                    CHECK ((target_entity_id IS NULL) != (target_drawing_id IS NULL))
                )""")
                conn.execute("""INSERT INTO relationships
                    (source_entity_id,relationship_type,target_entity_id,target_drawing_id)
                    SELECT source_entity_id,
                        CASE WHEN relationship_type='appears_in' THEN 'represented_in'
                             ELSE relationship_type END,
                        target_entity_id,NULL FROM relationships_legacy""")
                conn.execute("DROP TABLE relationships_legacy")
                conn.execute("""INSERT INTO relationships
                    (source_entity_id,relationship_type,target_entity_id,target_drawing_id)
                    SELECT entity_id,'appears_in',NULL,drawing_id FROM entities""")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_relationship_entity_edge
        ON relationships(source_entity_id,relationship_type,target_entity_id)
        WHERE target_entity_id IS NOT NULL""")
    conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_relationship_drawing_edge
        ON relationships(source_entity_id,relationship_type,target_drawing_id)
        WHERE target_drawing_id IS NOT NULL""")

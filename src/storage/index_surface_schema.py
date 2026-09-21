"""Additive migrations for the query/index surface and tag provenance."""


def ensure_index_surface(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS entity_tag_provenance (
            entity_id TEXT PRIMARY KEY
                REFERENCES entities(entity_id)
                ON DELETE CASCADE,
            source TEXT NOT NULL
                CHECK(
                    source IN (
                        'explicit',
                        'proximity',
                        'none'
                    )
                )
        );

        CREATE TABLE IF NOT EXISTS entity_block_refs (
            entity_id TEXT PRIMARY KEY
                REFERENCES entities(entity_id)
                ON DELETE CASCADE,
            block_name TEXT NOT NULL,
            attributes TEXT NOT NULL DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS
            idx_drawings_project_status
        ON drawings(
            project_id,
            scan_status,
            drawing_id
        );

        CREATE INDEX IF NOT EXISTS
            idx_entities_drawing_type
        ON entities(
            drawing_id,
            entity_type,
            handle
        );

        CREATE INDEX IF NOT EXISTS
            idx_entities_drawing_layer
        ON entities(
            drawing_id,
            layer COLLATE NOCASE,
            handle
        );

        CREATE INDEX IF NOT EXISTS
            idx_entity_block_name
        ON entity_block_refs(
            block_name COLLATE NOCASE,
            entity_id
        );

        CREATE INDEX IF NOT EXISTS
            idx_entity_properties_key_value
        ON entity_properties(
            key,
            value,
            entity_id
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS entity_search
        USING fts5(
            entity_id UNINDEXED,
            project_id UNINDEXED,
            drawing_id UNINDEXED,
            text,
            tokenize='unicode61'
        );
        """
    )

    # Existing tagged rows pre-date provenance tracking.
    # They are explicit because proximity tagging did not exist yet.
    conn.execute(
        """
        INSERT OR IGNORE INTO entity_tag_provenance(
            entity_id,
            source
        )
        SELECT
            entity_id,
            CASE
                WHEN tag IS NOT NULL
                 AND trim(tag) <> ''
                THEN 'explicit'
                ELSE 'none'
            END
        FROM entities
        """
    )

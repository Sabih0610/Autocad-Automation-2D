"""Additive migration for queryable layer and DWGPROPS metadata."""


def ensure_drawing_metadata_tables(
    conn,
):
    existing = {
        row[0]
        for row
        in conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
              AND name IN (
                  'drawing_layers',
                  'drawing_summary_properties'
              )
            """
        )
    }

    if (
        existing
        == {
            "drawing_layers",
            "drawing_summary_properties",
        }
    ):
        return

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS drawing_layers (
            drawing_id TEXT NOT NULL
                REFERENCES drawings(drawing_id),
            name TEXT NOT NULL,
            color INTEGER NOT NULL,
            true_color TEXT,
            linetype TEXT,
            is_off INTEGER NOT NULL DEFAULT 0,
            is_frozen INTEGER NOT NULL DEFAULT 0,
            is_locked INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (
                drawing_id,
                name
            )
        );

        CREATE INDEX IF NOT EXISTS idx_drawing_layers_name
            ON drawing_layers(
                name COLLATE NOCASE,
                drawing_id
            );

        CREATE TABLE IF NOT EXISTS drawing_summary_properties (
            drawing_id TEXT NOT NULL
                REFERENCES drawings(drawing_id),
            key TEXT NOT NULL,
            value TEXT,
            PRIMARY KEY (
                drawing_id,
                key
            )
        );
        """
    )

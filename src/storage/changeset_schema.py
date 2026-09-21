"""Allow a changeset to cover a file that is not a registered drawing.

`change_set_files.drawing_id` was `NOT NULL` and half of the table's primary
key, which tied every changeset to a drawing indexed inside a project. The
older write workflows (sketch, P&ID, CAD3D, vessel, place-symbol,
autocad/edit) write to whatever drawing the user points them at, which
usually is not in any project — so they could not produce a changeset at all,
and were therefore the seven of eight mutating workflows with no revert.

Making `drawing_id` nullable, and keying on the file path instead, lets one
mechanism cover both cases: project operations still carry a drawing_id,
file-level edits carry NULL and are identified by `original_path`.
"""


def ensure_changeset_file_targets(conn):
    columns = {row[1]: row for row in conn.execute("PRAGMA table_info(change_set_files)")}
    if not columns:
        return
    drawing_id = columns.get("drawing_id")
    # `row[3]` is PRAGMA table_info's notnull flag.
    if drawing_id is None or not drawing_id[3]:
        return

    conn.execute("BEGIN IMMEDIATE")
    try:
        columns = {row[1]: row for row in conn.execute("PRAGMA table_info(change_set_files)")}
        drawing_id = columns.get("drawing_id")
        if drawing_id is not None and drawing_id[3]:
            conn.execute("ALTER TABLE change_set_files RENAME TO change_set_files_legacy")
            conn.execute("""CREATE TABLE change_set_files (
                change_set_id TEXT NOT NULL REFERENCES change_sets(change_set_id),
                drawing_id TEXT REFERENCES drawings(drawing_id),
                original_path TEXT NOT NULL,
                current_path TEXT NOT NULL,
                backup_path TEXT NOT NULL,
                before_hash TEXT NOT NULL,
                after_hash TEXT,
                uses_cad INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY(change_set_id,original_path)
            )""")
            conn.execute("""INSERT INTO change_set_files
                (change_set_id,drawing_id,original_path,current_path,backup_path,before_hash,after_hash,uses_cad)
                SELECT change_set_id,drawing_id,original_path,current_path,backup_path,before_hash,after_hash,uses_cad
                FROM change_set_files_legacy""")
            conn.execute("DROP TABLE change_set_files_legacy")
        conn.commit()
    except Exception:
        conn.rollback()
        raise

-- A registered root folder. Nothing is scanned until a project is registered.
CREATE TABLE IF NOT EXISTS projects (
    project_id   TEXT PRIMARY KEY,   -- e.g. uuid4 hex, or a human slug like "water_plant_01"
    name         TEXT NOT NULL,
    root_path    TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'active',  -- active | archived
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

-- One row per DWG file discovered under a project's root_path.
CREATE TABLE IF NOT EXISTS drawings (
    drawing_id     TEXT PRIMARY KEY,
    project_id     TEXT NOT NULL REFERENCES projects(project_id),
    path           TEXT NOT NULL,          -- absolute path
    filename       TEXT NOT NULL,
    file_hash      TEXT,                   -- sha256 of file contents, for incremental rescan
    file_size      INTEGER,
    file_modified_at TEXT,                 -- OS mtime, for cheap pre-check before hashing
    last_scanned_at   TEXT,
    scan_status    TEXT NOT NULL DEFAULT 'pending',  -- pending | scanned | error
    scan_error     TEXT
);

-- One row per extracted entity/component (a line, a block reference, a pipe, whatever).
CREATE TABLE IF NOT EXISTS entities (
    entity_id      TEXT PRIMARY KEY,
    drawing_id     TEXT NOT NULL REFERENCES drawings(drawing_id),
    handle         TEXT,                   -- AutoCAD handle, if known (only meaningful via COM)
    tag            TEXT,                   -- engineering tag, e.g. "P-101", if present
    entity_type    TEXT NOT NULL,          -- LINE | CIRCLE | BLOCK_REF | PIPE | VALVE | ...
    layer          TEXT
);

-- Arbitrary key/value properties per entity (color, linetype, custom XData, block attributes...).
CREATE TABLE IF NOT EXISTS entity_properties (
    entity_id      TEXT NOT NULL REFERENCES entities(entity_id),
    key            TEXT NOT NULL,
    value          TEXT,
    PRIMARY KEY (entity_id, key)
);

-- Geometry, kept separate from generic properties because it's queried differently (spatial index).
CREATE TABLE IF NOT EXISTS entity_geometry (
    entity_id      TEXT PRIMARY KEY REFERENCES entities(entity_id),
    start_x REAL, start_y REAL, start_z REAL,
    end_x   REAL, end_y   REAL, end_z   REAL,
    min_x REAL, max_x REAL,
    min_y REAL, max_y REAL,
    min_z REAL, max_z REAL
);

-- Connectivity/dependency graph. Not a separate graph database — just a table.
CREATE TABLE IF NOT EXISTS relationships (
    source_entity_id TEXT NOT NULL REFERENCES entities(entity_id),
    relationship_type TEXT NOT NULL,   -- connected_to | appears_in | represented_in | depends_on
    target_entity_id  TEXT NOT NULL REFERENCES entities(entity_id),
    PRIMARY KEY (source_entity_id, relationship_type, target_entity_id)
);

-- Multi-file job fan-out: one AI plan, many job_items, consumed by the write queue.
CREATE TABLE IF NOT EXISTS jobs_multi_file (
    job_id       TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL REFERENCES projects(project_id),
    request_text TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending | running | done | error
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_items (
    job_item_id  TEXT PRIMARY KEY,
    job_id       TEXT NOT NULL REFERENCES jobs_multi_file(job_id),
    drawing_id   TEXT NOT NULL REFERENCES drawings(drawing_id),
    operation    TEXT NOT NULL,   -- JSON-encoded structured operation, see 05_structured_operations_and_editing.md
    status       TEXT NOT NULL DEFAULT 'pending',
    error        TEXT
);

-- Generalized changeset, replacing four inconsistent per-workflow token caches.
CREATE TABLE IF NOT EXISTS change_sets (
    change_set_id  TEXT PRIMARY KEY,
    project_id     TEXT REFERENCES projects(project_id),
    summary        TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending',  -- pending | kept | reverted
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS change_set_items (
    change_set_item_id TEXT PRIMARY KEY,
    change_set_id      TEXT NOT NULL REFERENCES change_sets(change_set_id),
    drawing_id         TEXT NOT NULL REFERENCES drawings(drawing_id),
    backup_path        TEXT,          -- where the pre-edit copy of this file was saved
    entity_id          TEXT REFERENCES entities(entity_id),
    field              TEXT,          -- e.g. "length_mm", "color"
    before_value       TEXT,
    after_value        TEXT
);

CREATE TABLE IF NOT EXISTS validation_results (
    validation_id  TEXT PRIMARY KEY,
    change_set_id  TEXT NOT NULL REFERENCES change_sets(change_set_id),
    check_name     TEXT NOT NULL,
    passed         INTEGER NOT NULL,  -- 0/1
    message        TEXT
);

-- Extractor document metadata is not represented by the original roadmap tables.
CREATE TABLE IF NOT EXISTS drawing_metadata (
    drawing_id TEXT PRIMARY KEY REFERENCES drawings(drawing_id),
    units INTEGER NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entity_tag_nocase ON entities(tag COLLATE NOCASE, drawing_id);

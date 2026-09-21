"""Atomic index replacement with stable drawing/handle IDs and indexed lookup."""
from dataclasses import asdict
import json
import math
import re
from uuid import NAMESPACE_URL, uuid5

from .database import connection


def entity_id(drawing_id, handle):
    return uuid5(NAMESPACE_URL, f"{drawing_id}:{handle}").hex


def store_snapshot(conn, drawing_id, snapshot):
    handles = [e.handle for e in snapshot.entities]
    if len(set(handles)) != len(handles) or any(not h for h in handles):
        raise ValueError("Entity handles must be non-empty and unique within a drawing")
    ids = {h: entity_id(drawing_id, h) for h in handles}
    old_ids = {row[0] for row in conn.execute("SELECT entity_id FROM entities WHERE drawing_id=?", (drawing_id,))}
    # Preserve IDs referenced by history; remove stale property/geometry values atomically.
    for old_id in old_ids:
        conn.execute("DELETE FROM entity_properties WHERE entity_id=?", (old_id,))
        conn.execute("DELETE FROM entity_geometry WHERE entity_id=?", (old_id,))
        conn.execute("DELETE FROM entity_tag_provenance WHERE entity_id=?", (old_id,))
        conn.execute("DELETE FROM entity_block_refs WHERE entity_id=?", (old_id,))
        conn.execute("DELETE FROM entity_search WHERE entity_id=?", (old_id,))
        conn.execute("DELETE FROM relationships WHERE source_entity_id=? OR target_entity_id=?", (old_id, old_id))
        if old_id not in ids.values():
            conn.execute("UPDATE change_set_items SET entity_id=NULL WHERE entity_id=?", (old_id,))
            conn.execute("DELETE FROM entities WHERE entity_id=?", (old_id,))

    drawing_row = conn.execute(
        """
        SELECT
            project_id,
            filename
        FROM drawings
        WHERE drawing_id=?
        """,
        (
            drawing_id,
        ),
    ).fetchone()

    if drawing_row is None:
        raise ValueError(
            "Drawing must exist before "
            "storing a snapshot"
        )

    project_id, filename = (
        drawing_row
    )

    block_refs = {
        block.handle:
            block
        for block
        in snapshot.blocks
        if (
            block.is_reference
            and block.handle
            in ids
        )
    }

    for entity in snapshot.entities:
        eid = ids[entity.handle]
        conn.execute("""INSERT INTO entities VALUES (?,?,?,?,?,?) ON CONFLICT(entity_id)
            DO UPDATE SET tag=excluded.tag,entity_type=excluded.entity_type,layer=excluded.layer""",
                     (eid, drawing_id, entity.handle, entity.tag, entity.entity_type, entity.layer))
        conn.execute(
            """
            INSERT INTO entity_tag_provenance(
                entity_id,
                source
            )
            VALUES (?, ?)
            """,
            (
                eid,
                getattr(
                    entity,
                    "tag_source",
                    "none",
                ),
            ),
        )
        values = snapshot.properties.get(entity.handle, {})
        conn.executemany("INSERT INTO entity_properties VALUES (?,?,?)",
                         [(eid, key, json.dumps(value, allow_nan=False)) for key, value in values.items()])

        block = block_refs.get(
            entity.handle
        )

        if block is not None:
            conn.execute(
                """
                INSERT INTO entity_block_refs(
                    entity_id,
                    block_name,
                    attributes
                )
                VALUES (?, ?, ?)
                """,
                (
                    eid,
                    block.name,
                    json.dumps(
                        block.attributes,
                        allow_nan=False,
                    ),
                ),
            )

        search_parts = [
            entity.tag or "",
            entity.entity_type or "",
            entity.layer or "",
            filename or "",
            block.name if block is not None else "",
            str(values.get("text") or ""),
            " ".join(
                str(value)
                for value in (
                    block.attributes.values()
                    if block is not None
                    else []
                )
            ),
        ]

        conn.execute(
            """
            INSERT INTO entity_search(
                entity_id,
                project_id,
                drawing_id,
                text
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                eid,
                project_id,
                drawing_id,
                " ".join(
                    part
                    for part in search_parts
                    if part
                ),
            ),
        )
    for box in snapshot.spatial_data:
        if box.handle not in ids:
            raise ValueError("Geometry references an unknown entity")
        bounds = tuple(value for pair in zip(box.minimum, box.maximum) for value in pair)
        if any(not math.isfinite(v) for v in bounds) or any(a > b for a, b in zip(box.minimum, box.maximum)):
            raise ValueError("Invalid bounding box")
        start, end = box.start or (None,) * 3, box.end or (None,) * 3
        conn.execute("INSERT INTO entity_geometry VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (ids[box.handle], *start, *end, *bounds))
    conn.execute("INSERT INTO drawing_metadata VALUES (?,?,?) ON CONFLICT(drawing_id) DO UPDATE SET units=excluded.units,payload=excluded.payload",
                 (drawing_id, snapshot.document.units, json.dumps(asdict(snapshot.document), allow_nan=False)))
    # Replace layer and DWGPROPS metadata atomically with the entity index.
    document_properties = snapshot.document.properties or {}
    layers = document_properties.get("_layers", {})
    summary = document_properties.get("_summary_info", {})
    conn.execute("DELETE FROM drawing_layers WHERE drawing_id=?", (drawing_id,))
    conn.execute("DELETE FROM drawing_summary_properties WHERE drawing_id=?", (drawing_id,))
    for name, values in layers.items():
        conn.execute(
            """
            INSERT INTO drawing_layers (
                drawing_id,
                name,
                color,
                true_color,
                linetype,
                is_off,
                is_frozen,
                is_locked
            )
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                drawing_id,
                name,
                int(values.get("color", 7)),
                (
                    json.dumps(values.get("true_color"), allow_nan=False)
                    if values.get("true_color") is not None
                    else None
                ),
                values.get("linetype"),
                int(bool(values.get("is_off"))),
                int(bool(values.get("is_frozen"))),
                int(bool(values.get("is_locked"))),
            ),
        )
    for key, value in summary.items():
        if key == "custom":
            for custom_key, custom_value in value.items():
                conn.execute(
                    "INSERT INTO drawing_summary_properties VALUES (?,?,?)",
                    (
                        drawing_id,
                        f"custom:{custom_key}",
                        str(custom_value),
                    ),
                )
        else:
            conn.execute(
                "INSERT INTO drawing_summary_properties VALUES (?,?,?)",
                (
                    drawing_id,
                    key,
                    str(value),
                ),
            )
    for relation in snapshot.relationships:
        if relation.source_handle not in ids or relation.target_handle not in ids:
            raise ValueError("Relationship references an unknown entity")
        conn.execute("""INSERT OR IGNORE INTO relationships
            (source_entity_id,relationship_type,target_entity_id) VALUES (?,?,?)""",
                     (ids[relation.source_handle], relation.relationship_type, ids[relation.target_handle]))
    for eid in ids.values():
        conn.execute("""INSERT OR IGNORE INTO relationships
            (source_entity_id,relationship_type,target_drawing_id)
            VALUES (?,'appears_in',?)""", (eid, drawing_id))
    # Same tag in another drawing is a representation, never spatial connectivity.
    for entity in snapshot.entities:
        if not entity.tag or not entity.tag.strip():
            continue
        others = conn.execute("""SELECT e.entity_id FROM entities e JOIN drawings d ON d.drawing_id=e.drawing_id
            WHERE e.tag=? COLLATE NOCASE AND e.drawing_id<>? AND d.scan_status='scanned'
            AND d.project_id=(SELECT project_id FROM drawings WHERE drawing_id=?)""",
                              (entity.tag, drawing_id, drawing_id)).fetchall()
        for other in others:
            for source, target in ((ids[entity.handle], other[0]), (other[0], ids[entity.handle])):
                conn.execute("""INSERT OR IGNORE INTO relationships
                    (source_entity_id,relationship_type,target_entity_id)
                    VALUES (?,'represented_in',?)""", (source, target))


TAG_QUERY = """
    SELECT
        e.*,
        COALESCE(
            tp.source,
            'none'
        ) AS tag_source,
        d.path,
        d.filename,
        d.project_id,
        d.file_hash,
        m.units,
        g.start_x,
        g.start_y,
        g.start_z,
        g.end_x,
        g.end_y,
        g.end_z,
        g.min_x,
        g.max_x,
        g.min_y,
        g.max_y,
        g.min_z,
        g.max_z
    FROM entities e
    JOIN drawings d
      ON d.drawing_id=
         e.drawing_id
    JOIN drawing_metadata m
      ON m.drawing_id=
         d.drawing_id
    LEFT JOIN entity_tag_provenance tp
      ON tp.entity_id=
         e.entity_id
    LEFT JOIN entity_geometry g
      ON g.entity_id=
         e.entity_id
    WHERE
        e.tag=?
            COLLATE NOCASE
        AND d.project_id=?
        AND d.scan_status=
            'scanned'
    ORDER BY
        d.path,
        e.handle
"""


def find_by_tag(project_id, tag):
    with connection() as conn:
        return [dict(row) for row in conn.execute(TAG_QUERY, (tag, project_id))]


def get_entity(
    eid,
):
    with connection() as conn:
        row = conn.execute(
            """
            SELECT
                e.*,
                COALESCE(
                    tp.source,
                    'none'
                ) AS tag_source,
                d.path,
                d.project_id,
                d.scan_status,
                m.units
            FROM entities e
            JOIN drawings d
              ON d.drawing_id=
                 e.drawing_id
            JOIN drawing_metadata m
              ON m.drawing_id=
                 d.drawing_id
            LEFT JOIN entity_tag_provenance tp
              ON tp.entity_id=
                 e.entity_id
            WHERE e.entity_id=?
            """,
            (
                eid,
            ),
        ).fetchone()

        if row is None:
            raise KeyError(
                f"Unknown entity: {eid}"
            )

        record = dict(
            row
        )

        record[
            "properties"
        ] = {
            property_row[0]:
                json.loads(
                    property_row[1]
                )
            for property_row
            in conn.execute(
                """
                SELECT
                    key,
                    value
                FROM entity_properties
                WHERE entity_id=?
                """,
                (
                    eid,
                ),
            )
        }

        geometry = conn.execute(
            """
            SELECT *
            FROM entity_geometry
            WHERE entity_id=?
            """,
            (
                eid,
            ),
        ).fetchone()

        record[
            "geometry"
        ] = (
            dict(
                geometry
            )
            if geometry
            else None
        )

    return record


def get_drawing_layers(
    project_id,
    drawing_id,
):
    with connection() as conn:
        owner = conn.execute(
            """
            SELECT 1
            FROM drawings
            WHERE drawing_id=?
              AND project_id=?
              AND scan_status='scanned'
            """,
            (
                drawing_id,
                project_id,
            ),
        ).fetchone()

        if owner is None:
            raise KeyError(
                "Unknown scanned drawing: "
                f"{drawing_id}"
            )

        rows = conn.execute(
            """
            SELECT
                name,
                color,
                true_color,
                linetype,
                is_off,
                is_frozen,
                is_locked
            FROM drawing_layers
            WHERE drawing_id=?
            ORDER BY name COLLATE NOCASE
            """,
            (
                drawing_id,
            ),
        ).fetchall()

    result = []

    for row in rows:
        item = dict(
            row
        )

        item[
            "true_color"
        ] = (
            json.loads(
                item[
                    "true_color"
                ]
            )
            if item[
                "true_color"
            ]
            else None
        )

        item[
            "is_off"
        ] = bool(
            item[
                "is_off"
            ]
        )

        item[
            "is_frozen"
        ] = bool(
            item[
                "is_frozen"
            ]
        )

        item[
            "is_locked"
        ] = bool(
            item[
                "is_locked"
            ]
        )

        result.append(
            item
        )

    return result


def get_drawing_summary(
    project_id,
    drawing_id,
):
    with connection() as conn:
        owner = conn.execute(
            """
            SELECT 1
            FROM drawings
            WHERE drawing_id=?
              AND project_id=?
              AND scan_status='scanned'
            """,
            (
                drawing_id,
                project_id,
            ),
        ).fetchone()

        if owner is None:
            raise KeyError(
                "Unknown scanned drawing: "
                f"{drawing_id}"
            )

        rows = conn.execute(
            """
            SELECT
                key,
                value
            FROM drawing_summary_properties
            WHERE drawing_id=?
            ORDER BY key
            """,
            (
                drawing_id,
            ),
        ).fetchall()

    result = {
        "custom": {}
    }

    for (
        key,
        value,
    ) in rows:
        if key.startswith(
            "custom:"
        ):
            result[
                "custom"
            ][
                key[7:]
            ] = value
        else:
            result[
                key
            ] = value

    return result


ENTITY_LIST_SELECT = """
    SELECT
        e.entity_id,
        e.drawing_id,
        e.handle,
        e.tag,
        COALESCE(
            tp.source,
            'none'
        ) AS tag_source,
        e.entity_type,
        e.layer,
        d.path,
        d.filename,
        d.project_id,
        d.file_hash,
        m.units,
        b.block_name,
        g.start_x,
        g.start_y,
        g.start_z,
        g.end_x,
        g.end_y,
        g.end_z,
        g.min_x,
        g.max_x,
        g.min_y,
        g.max_y,
        g.min_z,
        g.max_z
    FROM drawings d
        INDEXED BY
        idx_drawings_project_status
    JOIN entities e
        {entity_index}
      ON e.drawing_id=
         d.drawing_id
    JOIN drawing_metadata m
      ON m.drawing_id=
         d.drawing_id
    LEFT JOIN entity_geometry g
      ON g.entity_id=
         e.entity_id
    LEFT JOIN entity_tag_provenance tp
      ON tp.entity_id=
         e.entity_id
    LEFT JOIN entity_block_refs b
      ON b.entity_id=
         e.entity_id
    {search_join}
    WHERE
        d.project_id=?
        AND d.scan_status=
            'scanned'
    {filters}
    ORDER BY
        d.path,
        e.handle
    LIMIT ? OFFSET ?
"""


def _fts_query(
    value,
):
    tokens = re.findall(
        r"[A-Za-z0-9_]+",
        value or "",
    )

    if not tokens:
        raise ValueError(
            "Search text must contain "
            "a letter or number"
        )

    return " AND ".join(
        f'"{token}"*'
        for token
        in tokens
    )


def build_entity_list_query(
    project_id,
    *,
    drawing_id=None,
    tag=None,
    entity_type=None,
    layer=None,
    block=None,
    q=None,
    limit=200,
    offset=0,
):
    if (
        limit < 1
        or limit > 1000
    ):
        raise ValueError(
            "limit must be between "
            "1 and 1000"
        )

    if offset < 0:
        raise ValueError(
            "offset must be non-negative"
        )

    if entity_type:
        entity_index = (
            "INDEXED BY "
            "idx_entities_drawing_type"
        )

    elif layer:
        entity_index = (
            "INDEXED BY "
            "idx_entities_drawing_layer"
        )

    else:
        entity_index = (
            "INDEXED BY "
            "idx_entity_drawing"
        )

    search_join = ""

    filters = []

    params = [
        project_id
    ]

    if drawing_id:
        filters.append(
            "AND d.drawing_id=?"
        )

        params.append(
            drawing_id
        )

    if tag:
        filters.append(
            "AND e.tag=? COLLATE NOCASE"
        )

        params.append(
            tag
        )

    if entity_type:
        filters.append(
            "AND e.entity_type=?"
        )

        params.append(
            entity_type.upper()
        )

    if layer:
        filters.append(
            "AND e.layer=? COLLATE NOCASE"
        )

        params.append(
            layer
        )

    if block:
        filters.append(
            "AND b.block_name=? "
            "COLLATE NOCASE"
        )

        params.append(
            block
        )

    if q:
        search_join = (
            "JOIN entity_search s "
            "ON s.entity_id="
            "e.entity_id"
        )

        filters.append(
            "AND s.text MATCH ?"
        )

        params.append(
            _fts_query(
                q
            )
        )

    sql = (
        ENTITY_LIST_SELECT
        .format(
            entity_index=
                entity_index,
            search_join=
                search_join,
            filters=
                "\n    ".join(
                    filters
                ),
        )
    )

    params.extend(
        (
            limit,
            offset,
        )
    )

    return (
        sql,
        tuple(
            params
        ),
    )


def list_entities(
    project_id,
    *,
    drawing_id=None,
    tag=None,
    entity_type=None,
    layer=None,
    block=None,
    q=None,
    limit=200,
    offset=0,
):
    (
        sql,
        params,
    ) = build_entity_list_query(
        project_id,
        drawing_id=
            drawing_id,
        tag=
            tag,
        entity_type=
            entity_type,
        layer=
            layer,
        block=
            block,
        q=
            q,
        limit=
            limit,
        offset=
            offset,
    )

    with connection() as conn:
        return [
            dict(
                row
            )
            for row
            in conn.execute(
                sql,
                params,
            )
        ]


def get_project_entity(
    project_id,
    eid,
):
    record = get_entity(
        eid
    )

    if (
        record[
            "project_id"
        ]
        != project_id
        or record[
            "scan_status"
        ]
        != "scanned"
    ):
        raise KeyError(
            "Unknown scanned entity: "
            f"{eid}"
        )

    with connection() as conn:
        block = conn.execute(
            """
            SELECT
                block_name,
                attributes
            FROM entity_block_refs
            WHERE entity_id=?
            """,
            (
                eid,
            ),
        ).fetchone()

    record[
        "block"
    ] = (
        {
            "name":
                block[0],
            "attributes":
                json.loads(
                    block[1]
                ),
        }
        if block
        else None
    )

    return record


def get_drawing_metadata(
    project_id,
    drawing_id,
):
    with connection() as conn:
        row = conn.execute(
            """
            SELECT m.payload
            FROM drawing_metadata m
            JOIN drawings d
              ON d.drawing_id=
                 m.drawing_id
            WHERE
                m.drawing_id=?
                AND d.project_id=?
                AND d.scan_status=
                    'scanned'
            """,
            (
                drawing_id,
                project_id,
            ),
        ).fetchone()

    if row is None:
        raise KeyError(
            "Unknown scanned drawing: "
            f"{drawing_id}"
        )

    return json.loads(
        row[0]
    )

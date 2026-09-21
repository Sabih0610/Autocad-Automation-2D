"""SQLite selects scope; one planner call; persisted jobs feed a single writer."""
import json
import math
import re
from uuid import uuid4

from src.ai.project_planner import plan_operation
from src.cad.changes import ChangeManager, get_change_set
from src.cad.scanner import file_hash
from src.cad.units import from_mm
from src.cad.write_queue import WRITE_QUEUE
from src.framework.commands.operation_schema import validate_operation
from src.storage.database import connection
from src.storage.entity_repository import (
    find_by_tag,
    get_entity,
)
from src.storage.project_repository import get_project, now


def reconcile_interrupted_jobs():
    """Recover multi-file jobs stranded by a process crash."""
    with connection() as conn:
        stale_job_ids = [
            row[0]
            for row
            in conn.execute(
                "SELECT job_id FROM jobs_multi_file WHERE status='running'"
            ).fetchall()
        ]

        for job_id in stale_job_ids:
            conn.execute(
                "UPDATE jobs_multi_file SET status='error' WHERE job_id=?",
                (job_id,),
            )
            conn.execute(
                """
                UPDATE job_items
                SET status='error',
                    error=?
                WHERE job_id=?
                  AND status IN ('pending','running')
                """,
                (
                    "Interrupted by a process restart; create a new plan and retry",
                    job_id,
                ),
            )

    return stale_job_ids


def get_multi_file_job(job_id):
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM jobs_multi_file WHERE job_id=?",
            (job_id,),
        ).fetchone()

        if row is None:
            raise KeyError(
                f"Unknown project job: {job_id}"
            )

        job = dict(row)
        job["items"] = [
            dict(row)
            for row
            in conn.execute(
                """
                SELECT i.*,
                       d.path
                FROM job_items i
                JOIN drawings d
                  ON d.drawing_id=i.drawing_id
                WHERE i.job_id=?
                ORDER BY i.rowid
                """,
                (job_id,),
            )
        ]
        link = conn.execute(
            "SELECT change_set_id FROM job_change_sets WHERE job_id=?",
            (job_id,),
        ).fetchone()

    for item in job["items"]:
        item["operation"] = json.loads(
            item["operation"]
        )

    job["change_set"] = (
        get_change_set(link[0])
        if link
        else None
    )

    return job


class ProjectOrchestrator:
    def __init__(
        self,
        *,
        planner=plan_operation,
        manager=None,
        queue=WRITE_QUEUE,
    ):
        self.planner = planner
        self.manager = manager or ChangeManager()
        self.queue = queue

    def plan(
        self,
        project_id,
        prompt,
        *,
        tag=None,
        drawing_id=None,
    ):
        project = get_project(
            project_id
        )

        if (
            project["status"]
            != "active"
        ):
            raise ValueError(
                "Project is archived"
            )

        if not tag:
            tags = set(
                re.findall(
                    (
                        r"\b[A-Za-z]"
                        r"[A-Za-z0-9]*-"
                        r"\d+[A-Za-z0-9-]*\b"
                    ),
                    prompt,
                )
            )

            if len(tags) > 1:
                raise ValueError(
                    "Specify one component tag "
                    "per request"
                )

            tag = next(
                iter(tags),
                None,
            )

        if tag:
            records = find_by_tag(
                project_id,
                tag,
            )

            if drawing_id:
                records = [
                    record
                    for record
                    in records
                    if (
                        record[
                            "drawing_id"
                        ]
                        == drawing_id
                    )
                ]

            if not records:
                raise ValueError(
                    "No current indexed component "
                    f"tagged {tag} in the "
                    "selected scope"
                )

            if (
                len(
                    {
                        record[
                            "drawing_id"
                        ]
                        for record
                        in records
                    }
                )
                != len(records)
            ):
                raise ValueError(
                    "Tag identifies multiple "
                    "entities in one drawing; "
                    "select a unique component"
                )

            if (
                len(
                    {
                        record[
                            "entity_type"
                        ]
                        for record
                        in records
                    }
                )
                != 1
            ):
                raise ValueError(
                    "Occurrences have different "
                    "entity types; select a "
                    "drawing to disambiguate"
                )

            enriched = []

            for record in records:
                full = get_entity(
                    record[
                        "entity_id"
                    ]
                )

                item = dict(
                    record
                )

                item[
                    "properties"
                ] = full[
                    "properties"
                ]

                item[
                    "geometry"
                ] = full[
                    "geometry"
                ]

                enriched.append(
                    item
                )

            records = enriched

            context = dict(
                records[0],
                occurrence_count=
                    len(records),
            )

            with connection() as conn:
                context[
                    "connection_count"
                ] = conn.execute(
                    """
                    SELECT count(*)
                    FROM relationships
                    WHERE source_entity_id=?
                      AND relationship_type='connected_to'
                    """,
                    (
                        records[0][
                            "entity_id"
                        ],
                    ),
                ).fetchone()[0]

        elif drawing_id:
            with connection() as conn:
                row = conn.execute(
                    """
                    SELECT
                        d.*,
                        m.units
                    FROM drawings d
                    JOIN drawing_metadata m
                      ON m.drawing_id=d.drawing_id
                    WHERE d.drawing_id=?
                      AND d.project_id=?
                      AND d.scan_status='scanned'
                    """,
                    (
                        drawing_id,
                        project_id,
                    ),
                ).fetchone()

            if row is None:
                raise ValueError(
                    "Select a scanned drawing "
                    "from this project"
                )

            records = [
                dict(row)
            ]

            context = dict(
                records[0],
                occurrence_count=1,
            )

        else:
            raise ValueError(
                "Include one component tag "
                "(for example P-101), "
                "or select a drawing for "
                "document/layer edits"
            )

        draft = self.planner(
            prompt,
            context,
        )

        if (
            draft["command"]
            == "CLARIFY"
        ):
            return {
                "status":
                    "clarify",
                "project_id":
                    project_id,
                "request_text":
                    prompt,
                "message":
                    draft[
                        "message"
                    ],
                "tag":
                    tag,
                "drawing_id":
                    drawing_id,
            }

        entity_command = (
            draft["command"]
            in {
                "RESIZE_COMPONENT",
                "SCALE_ENTITY",
                "SET_ENTITY_PROPERTY",
            }
        )

        if (
            entity_command
            and not tag
        ):
            raise ValueError(
                "Select a component tag "
                "for entity edits"
            )

        if (
            not entity_command
            and not drawing_id
        ):
            raise ValueError(
                "Select one explicit drawing "
                "for file, layer or "
                "document properties"
            )

        if not entity_command:
            records = records[:1]

        operations = []

        for record in records:
            op = dict(
                draft,
                target_dwg_path=
                    record[
                        "path"
                    ],
            )

            if entity_command:
                op[
                    "handle"
                ] = record[
                    "handle"
                ]

            validate_operation(
                op
            )

            preview = None

            if (
                op["command"]
                == "RESIZE_COMPONENT"
            ):
                dimension = op[
                    "dimension"
                ]

                units = record[
                    "units"
                ]

                mm_unit = from_mm(
                    1,
                    units,
                )

                props = record.get(
                    "properties",
                    {},
                )

                if (
                    dimension
                    == "length"
                ):
                    if (
                        record[
                            "entity_type"
                        ]
                        != "LINE"
                    ):
                        raise ValueError(
                            "Length resize requires "
                            "a LINE; choose a "
                            "supported entity"
                        )

                    before = (
                        math.dist(
                            [
                                record[
                                    f"start_{axis}"
                                ]
                                for axis
                                in "xyz"
                            ],
                            [
                                record[
                                    f"end_{axis}"
                                ]
                                for axis
                                in "xyz"
                            ],
                        )
                        / mm_unit
                    )

                    after = op.get(
                        "value_mm",
                        before
                        + op.get(
                            "delta_mm",
                            0,
                        ),
                    )

                    if (
                        not math.isfinite(
                            after
                        )
                        or after <= 0
                    ):
                        raise ValueError(
                            "Planned length must "
                            "be positive and finite"
                        )

                    preview = {
                        "field":
                            "length_mm",
                        "before":
                            before,
                        "after":
                            after,
                    }

                elif (
                    dimension
                    == "radius"
                ):
                    if (
                        record[
                            "entity_type"
                        ]
                        not in {
                            "CIRCLE",
                            "ARC",
                        }
                    ):
                        raise ValueError(
                            "Radius resize requires "
                            "a CIRCLE or ARC; "
                            "choose a supported entity"
                        )

                    radius = props.get(
                        "radius"
                    )

                    if radius is None:
                        raise ValueError(
                            "Indexed circle/arc "
                            "radius is unavailable; "
                            "rescan before editing"
                        )

                    before = (
                        float(radius)
                        / mm_unit
                    )

                    after = op.get(
                        "value_mm",
                        before
                        + op.get(
                            "delta_mm",
                            0,
                        ),
                    )

                    if (
                        not math.isfinite(
                            after
                        )
                        or after <= 0
                    ):
                        raise ValueError(
                            "Planned radius must "
                            "be positive and finite"
                        )

                    preview = {
                        "field":
                            "radius_mm",
                        "before":
                            before,
                        "after":
                            after,
                    }

                elif (
                    dimension
                    in {
                        "major_axis",
                        "minor_axis",
                    }
                ):
                    if (
                        record[
                            "entity_type"
                        ]
                        != "ELLIPSE"
                    ):
                        raise ValueError(
                            "Ellipse axis resize "
                            "requires an ELLIPSE; "
                            "choose a supported entity"
                        )

                    major = props.get(
                        "major_radius"
                    )

                    minor = props.get(
                        "minor_radius"
                    )

                    if (
                        major is None
                        or minor is None
                    ):
                        raise ValueError(
                            "Indexed ellipse axes "
                            "are unavailable; "
                            "rescan before editing"
                        )

                    major_mm = (
                        float(major)
                        / mm_unit
                    )

                    minor_mm = (
                        float(minor)
                        / mm_unit
                    )

                    before = (
                        major_mm
                        if dimension
                        == "major_axis"
                        else minor_mm
                    )

                    after = op.get(
                        "value_mm",
                        before
                        + op.get(
                            "delta_mm",
                            0,
                        ),
                    )

                    if (
                        not math.isfinite(
                            after
                        )
                        or after <= 0
                    ):
                        raise ValueError(
                            "Planned ellipse axis "
                            "must be positive "
                            "and finite"
                        )

                    if (
                        dimension
                        == "major_axis"
                        and after
                        < minor_mm
                    ):
                        raise ValueError(
                            "Planned major axis "
                            "cannot be smaller than "
                            "the current minor axis"
                        )

                    if (
                        dimension
                        == "minor_axis"
                        and after
                        > major_mm
                    ):
                        raise ValueError(
                            "Planned minor axis "
                            "cannot exceed the "
                            "current major axis"
                        )

                    preview = {
                        "field":
                            f"{dimension}_mm",
                        "before":
                            before,
                        "after":
                            after,
                    }

            elif (
                op["command"]
                == "SCALE_ENTITY"
            ):
                supported = {
                    "LINE",
                    "CIRCLE",
                    "ARC",
                    "ELLIPSE",
                    "LWPOLYLINE",
                    "POLYLINE",
                    "BLOCK_REF",
                }

                if (
                    record[
                        "entity_type"
                    ]
                    not in supported
                ):
                    raise ValueError(
                        "Scaling is not supported "
                        f"for {record['entity_type']}"
                    )

                factor = float(
                    op[
                        "factor"
                    ]
                )

                if (
                    not math.isfinite(
                        factor
                    )
                    or factor <= 0
                ):
                    raise ValueError(
                        "Scale factor must be "
                        "positive and finite"
                    )

                basepoint = op[
                    "basepoint"
                ]

                if (
                    basepoint
                    == "start"
                    and record[
                        "entity_type"
                    ]
                    != "LINE"
                ):
                    raise ValueError(
                        "start basepoint "
                        "requires a LINE"
                    )

                if (
                    basepoint
                    == "insertion_point"
                    and record[
                        "entity_type"
                    ]
                    != "BLOCK_REF"
                ):
                    raise ValueError(
                        "insertion_point basepoint "
                        "requires a block reference"
                    )

                if (
                    basepoint
                    == "center"
                    and not record.get(
                        "geometry"
                    )
                ):
                    raise ValueError(
                        "center basepoint requires "
                        "indexed bounds"
                    )

                with connection() as conn:
                    blocked = conn.execute(
                        """
                        SELECT 1
                        FROM relationships
                        WHERE relationship_type
                              IN (
                                  'depends_on',
                                  'connected_to'
                              )
                          AND (
                              source_entity_id=?
                              OR target_entity_id=?
                          )
                        LIMIT 1
                        """,
                        (
                            record[
                                "entity_id"
                            ],
                            record[
                                "entity_id"
                            ],
                        ),
                    ).fetchone()

                if blocked:
                    raise ValueError(
                        "Scaling a connected/"
                        "dependent entity requires "
                        "a supported dependency rule"
                    )

                preview = {
                    "field":
                        "scale_factor",
                    "before":
                        1.0,
                    "after":
                        factor,
                }

            elif (
                op["command"]
                == "SET_ENTITY_PROPERTY"
            ):
                property_name = op[
                    "property"
                ]

                if (
                    property_name
                    in {
                        "scale_x",
                        "scale_y",
                        "scale_z",
                    }
                    and record[
                        "entity_type"
                    ]
                    != "BLOCK_REF"
                ):
                    raise ValueError(
                        "Block scale-factor edits "
                        "require a block reference"
                    )

                if (
                    property_name
                    == "attribute"
                    and record[
                        "entity_type"
                    ]
                    != "BLOCK_REF"
                ):
                    raise ValueError(
                        "Attribute edits require "
                        "a block reference"
                    )

            operations.append(
                (
                    record[
                        "drawing_id"
                    ],
                    {
                        "operation":
                            op,
                        "expected_hash":
                            record[
                                "file_hash"
                            ],
                        "preview":
                            preview,
                    },
                )
            )

        job_id = uuid4().hex

        with connection() as conn:
            conn.execute(
                """
                INSERT INTO jobs_multi_file
                VALUES (
                    ?,
                    ?,
                    ?,
                    'pending',
                    ?
                )
                """,
                (
                    job_id,
                    project_id,
                    prompt,
                    now(),
                ),
            )

            for (
                target_id,
                payload,
            ) in operations:
                conn.execute(
                    """
                    INSERT INTO job_items
                    VALUES (
                        ?,
                        ?,
                        ?,
                        ?,
                        'pending',
                        NULL
                    )
                    """,
                    (
                        uuid4().hex,
                        job_id,
                        target_id,
                        json.dumps(
                            payload
                        ),
                    ),
                )

        return get_multi_file_job(
            job_id
        )

    def execute(self, job_id):
        return self.queue.run(
            self._execute,
            job_id,
        )

    def _execute(self, job_id):
        with connection() as conn:
            claimed = conn.execute(
                """
                UPDATE jobs_multi_file
                SET status='running'
                WHERE job_id=?
                  AND status='pending'
                """,
                (job_id,),
            ).rowcount

            if claimed != 1:
                raise ValueError(
                    "Job is absent, already executing, or already consumed"
                )

        job = get_multi_file_job(
            job_id
        )

        def on_item(index, status, error):
            with connection() as conn:
                conn.execute(
                    """
                    UPDATE job_items
                    SET status=?,
                        error=?
                    WHERE job_item_id=?
                    """,
                    (
                        status,
                        error,
                        job["items"][index]["job_item_id"],
                    ),
                )

        try:
            for item in job["items"]:
                payload = item["operation"]
                path = payload[
                    "operation"
                ][
                    "target_dwg_path"
                ]

                if (
                    file_hash(path)
                    != payload["expected_hash"]
                ):
                    raise ValueError(
                        "Drawing changed since planning; scan and create a new plan"
                    )

            change = self.manager.apply(
                job["project_id"],
                [
                    item["operation"]["operation"]
                    for item
                    in job["items"]
                ],
                job["request_text"],
                on_item=on_item,
            )

            with connection() as conn:
                conn.execute(
                    "INSERT INTO job_change_sets VALUES (?,?)",
                    (
                        job_id,
                        change["change_set_id"],
                    ),
                )
                conn.execute(
                    """
                    UPDATE jobs_multi_file
                    SET status=?
                    WHERE job_id=?
                    """,
                    (
                        (
                            "done"
                            if change["status"] == "pending"
                            else "error"
                        ),
                        job_id,
                    ),
                )
                conn.execute(
                    """
                    UPDATE job_items
                    SET status='cancelled',
                        error='Earlier item failed'
                    WHERE job_id=?
                      AND status='pending'
                    """,
                    (job_id,),
                )
        except Exception as exc:
            with connection() as conn:
                conn.execute(
                    "UPDATE jobs_multi_file SET status='error' WHERE job_id=?",
                    (job_id,),
                )
                conn.execute(
                    """
                    UPDATE job_items
                    SET status='error',
                        error=?
                    WHERE job_id=?
                      AND status IN ('pending','running')
                    """,
                    (
                        str(exc),
                        job_id,
                    ),
                )
            raise

        return get_multi_file_job(
            job_id
        )

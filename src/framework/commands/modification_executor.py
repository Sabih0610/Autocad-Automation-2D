"""Deterministic in-place edits. All coordinates are computed here, not by AI."""
from dataclasses import dataclass
import math
from pathlib import Path

from src.cad.geometry import (
    resize_endpoint,
    box_for_points,
)
from src.cad.session import (
    CAD_LOCK,
    cad_session,
    canonical_path,
    get_document,
    point,
)
from src.cad.units import from_mm
from src.cad.scanner import file_hash
from src.cad.relationships import (
    related_entities,
)
from src.parametric.vessel.dwg_export import (
    _com_retry,
)
from src.storage.database import connection
from src.storage.entity_repository import (
    get_entity,
)
from src.storage.spatial import (
    SpatialIndex,
    bounds_distance,
)
from .operation_schema import (
    validate_operation,
)


@dataclass
class Assignment:
    obj: object
    property: str
    before: object
    after: object
    handle: str | None = None
    is_point: bool = False
    field: str | None = None

    def summary(self):
        return {
            "handle":
                self.handle,
            "field":
                self.field
                or self.property,
            "before":
                self.before,
            "after":
                self.after,
        }


@dataclass
class ScaleAction:
    obj: object
    basepoint: tuple[
        float,
        float,
        float,
    ]
    factor: float
    handle: str
    after_box: dict

    def summary(self):
        return {
            "handle":
                self.handle,
            "field":
                "scale_factor",
            "before":
                1.0,
            "after":
                self.factor,
        }


def _rgb_tuple(
    color,
):
    return (
        int(color.Red),
        int(color.Green),
        int(color.Blue),
    )


def _assign(
    change,
    value,
):
    # AutoCAD TrueColor is an
    # AcCmColor COM object.
    if (
        change.property
        == "TrueColor"
    ):
        rgb = tuple(
            int(component)
            for component
            in value
        )

        def apply_rgb():
            color = (
                change.obj
                .TrueColor
            )

            color.SetRGB(
                *rgb
            )

            change.obj.TrueColor = (
                color
            )

        _com_retry(
            apply_rgb,
            "assigning TrueColor",
        )

        return

    actual_value = (
        point(value)
        if change.is_point
        else value
    )

    _com_retry(
        lambda: setattr(
            change.obj,
            change.property,
            actual_value,
        ),
        (
            "assigning "
            f"{change.property}"
        ),
    )


def _apply_change(
    change,
):
    if isinstance(
        change,
        ScaleAction,
    ):
        _com_retry(
            lambda:
                change.obj.ScaleEntity(
                    point(
                        change.basepoint
                    ),
                    change.factor,
                ),
            (
                "scaling entity "
                f"{change.handle}"
            ),
        )
    else:
        _assign(
            change,
            change.after,
        )


def _rollback_change(
    change,
):
    if isinstance(
        change,
        ScaleAction,
    ):
        _com_retry(
            lambda:
                change.obj.ScaleEntity(
                    point(
                        change.basepoint
                    ),
                    1.0
                    / change.factor,
                ),
            (
                "rolling back scale on "
                f"{change.handle}"
            ),
        )
    else:
        _assign(
            change,
            change.before,
        )


def _verify_live_assignment(
    change,
):
    if isinstance(
        change,
        ScaleAction,
    ):
        # Saved-file extraction proves
        # the final geometric state.
        return

    if (
        change.property
        == "TrueColor"
    ):
        actual = _rgb_tuple(
            change.obj.TrueColor
        )

        if (
            actual
            != tuple(
                change.after
            )
        ):
            raise ValueError(
                "AutoCAD did not retain "
                "the assigned TrueColor"
            )

        return

    actual = getattr(
        change.obj,
        change.property,
    )

    if change.is_point:
        if (
            math.dist(
                tuple(actual),
                change.after,
            )
            > 1e-6
        ):
            raise ValueError(
                "AutoCAD did not retain "
                "the assigned coordinate"
            )

    elif (
        change.property
        in {
            "Layer",
            "Linetype",
        }
    ):
        if (
            str(actual).casefold()
            != str(
                change.after
            ).casefold()
        ):
            raise ValueError(
                "AutoCAD did not retain "
                "the assigned property"
            )

    elif isinstance(
        change.after,
        float,
    ):
        if not math.isclose(
            float(actual),
            change.after,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            raise ValueError(
                "AutoCAD did not retain "
                "the assigned property"
            )

    elif (
        actual
        != change.after
    ):
        raise ValueError(
            "AutoCAD did not retain "
            "the assigned property"
        )


def _indexed_record(
    path,
    handle,
    eid=None,
    project_id=None,
):
    if eid:
        record = get_entity(
            eid
        )

        if (
            record["path"]
            != path
            or record["handle"]
            != handle
        ):
            raise ValueError(
                "Operation does not match "
                "the indexed entity"
            )

        return record

    with connection() as conn:
        if project_id is None:
            rows = conn.execute(
                """
                SELECT e.entity_id
                FROM entities e
                JOIN drawings d
                  ON d.drawing_id=e.drawing_id
                WHERE d.path=?
                  AND e.handle=?
                """,
                (
                    path,
                    handle,
                ),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT e.entity_id
                FROM entities e
                JOIN drawings d
                  ON d.drawing_id=e.drawing_id
                WHERE d.path=?
                  AND e.handle=?
                  AND d.project_id=?
                """,
                (
                    path,
                    handle,
                    project_id,
                ),
            ).fetchall()

    if len(rows) != 1:
        raise ValueError(
            "Entity must be uniquely "
            "indexed before editing; "
            "scan and select a project"
        )

    return get_entity(
        rows[0][0]
    )


def _verify_index(
    record,
    path,
):
    if (
        record[
            "scan_status"
        ]
        != "scanned"
    ):
        raise ValueError(
            "Drawing index is stale; "
            "rescan before editing"
        )

    with connection() as conn:
        expected = conn.execute(
            """
            SELECT file_hash
            FROM drawings
            WHERE drawing_id=?
            """,
            (
                record[
                    "drawing_id"
                ],
            ),
        ).fetchone()[0]

    if (
        file_hash(path)
        != expected
    ):
        raise ValueError(
            "Drawing changed since "
            "scanning; rescan before editing"
        )


def _validate_proposed_bounds(
    proposed,
    units,
    *,
    verb="Edit",
):
    index = SpatialIndex()

    for (
        eid,
        new_box,
    ) in proposed.items():
        old_box = get_entity(
            eid
        )[
            "geometry"
        ]

        if old_box is None:
            raise ValueError(
                "Indexed entity has no "
                "geometry; rescan before editing"
            )

        reach = (
            max(
                abs(
                    new_box[key]
                    - old_box[key]
                )
                for key
                in new_box
            )
            / from_mm(
                1,
                units,
            )
            + 0.01
        )

        for other in index.nearby(
            eid,
            reach,
        ):
            if (
                other[
                    "entity_id"
                ]
                in proposed
            ):
                continue

            if (
                bounds_distance(
                    old_box,
                    other,
                )
                > 1e-8
                and bounds_distance(
                    new_box,
                    other,
                )
                <= 1e-8
            ):
                raise ValueError(
                    f"{verb} introduces "
                    "an overlap with handle "
                    f"{other['handle']}"
                )


def _ellipse_box(
    center,
    major_axis,
    normal,
    major_radius,
    minor_radius,
):
    def normalize(
        vector,
    ):
        length = math.sqrt(
            sum(
                float(value)
                ** 2
                for value
                in vector
            )
        )

        if (
            not math.isfinite(
                length
            )
            or length <= 1e-12
        ):
            raise ValueError(
                "Ellipse axis/normal "
                "is invalid"
            )

        return tuple(
            float(value)
            / length
            for value
            in vector
        )

    u = normalize(
        major_axis
    )

    n = normalize(
        normal
    )

    v = (
        n[1] * u[2]
        - n[2] * u[1],
        n[2] * u[0]
        - n[0] * u[2],
        n[0] * u[1]
        - n[1] * u[0],
    )

    v = normalize(
        v
    )

    extents = tuple(
        math.sqrt(
            (
                major_radius
                * u[i]
            )
            ** 2
            + (
                minor_radius
                * v[i]
            )
            ** 2
        )
        for i in range(3)
    )

    return {
        f"min_{axis}":
            float(center[i])
            - extents[i]
        for i, axis
        in enumerate(
            "xyz"
        )
    } | {
        f"max_{axis}":
            float(center[i])
            + extents[i]
        for i, axis
        in enumerate(
            "xyz"
        )
    }


def _resize(
    doc,
    entity,
    op,
    record,
):
    units = int(
        doc.GetVariable(
            "INSUNITS"
        )
    )

    if (
        units
        != record["units"]
    ):
        raise ValueError(
            "Live units differ from "
            "the index; save and rescan"
        )

    delta = (
        from_mm(
            op[
                "delta_mm"
            ],
            units,
        )
        if "delta_mm"
        in op
        else None
    )

    value = (
        from_mm(
            op[
                "value_mm"
            ],
            units,
        )
        if "value_mm"
        in op
        else None
    )

    changes = []
    proposed = {}

    dimension = op[
        "dimension"
    ]

    if (
        dimension
        == "length"
    ):
        if (
            entity.ObjectName
            != "AcDbLine"
            or record[
                "entity_type"
            ]
            != "LINE"
        ):
            raise ValueError(
                "Length resizing currently "
                "supports LINE entities"
            )

        start = tuple(
            entity.StartPoint
        )

        end = tuple(
            entity.EndPoint
        )

        indexed = record[
            "geometry"
        ]

        if (
            not indexed
            or any(
                abs(
                    indexed[
                        f"{key}_{axis}"
                    ]
                    - p[i]
                )
                > 1e-6
                for key, p
                in (
                    (
                        "start",
                        start,
                    ),
                    (
                        "end",
                        end,
                    ),
                )
                for i, axis
                in enumerate(
                    "xyz"
                )
            )
        ):
            raise ValueError(
                "Live geometry differs "
                "from the index; "
                "save and rescan"
            )

        new_end = resize_endpoint(
            start,
            end,
            delta=delta,
            value=value,
        )

        changes.append(
            Assignment(
                entity,
                "EndPoint",
                end,
                new_end,
                op[
                    "handle"
                ],
                True,
                "length",
            )
        )

        proposed[
            record[
                "entity_id"
            ]
        ] = box_for_points(
            start,
            new_end,
        )

        with connection() as conn:
            related = (
                related_entities(
                    conn,
                    record[
                        "entity_id"
                    ],
                )
            )

            dependencies = (
                conn.execute(
                    """
                    SELECT 1
                    FROM relationships
                    WHERE relationship_type='depends_on'
                      AND (
                          source_entity_id=?
                          OR target_entity_id=?
                      )
                    """,
                    (
                        record[
                            "entity_id"
                        ],
                        record[
                            "entity_id"
                        ],
                    ),
                )
                .fetchall()
            )

        if dependencies:
            raise ValueError(
                "Explicit dependent/"
                "constraint entities require "
                "a supported dependency rule"
            )

        offset = tuple(
            b - a
            for a, b
            in zip(
                end,
                new_end,
            )
        )

        for other in related:
            obj = (
                doc.HandleToObject(
                    other[
                        "handle"
                    ]
                )
            )

            other_record = (
                get_entity(
                    other[
                        "entity_id"
                    ]
                )
            )

            if (
                other[
                    "drawing_id"
                ]
                != record[
                    "drawing_id"
                ]
            ):
                raise ValueError(
                    "Spatial dependency "
                    "crosses drawings"
                )

            if (
                obj.ObjectName
                == "AcDbBlockReference"
            ):
                before = tuple(
                    obj.InsertionPoint
                )

                if (
                    math.dist(
                        before,
                        end,
                    )
                    > from_mm(
                        0.01,
                        units,
                    )
                ):
                    continue

                after = tuple(
                    a + b
                    for a, b
                    in zip(
                        before,
                        offset,
                    )
                )

                changes.append(
                    Assignment(
                        obj,
                        "InsertionPoint",
                        before,
                        after,
                        other[
                            "handle"
                        ],
                        True,
                    )
                )

                if obj.HasAttributes:
                    for attr in (
                        obj.GetAttributes()
                    ):
                        position = tuple(
                            attr.InsertionPoint
                        )

                        changes.append(
                            Assignment(
                                attr,
                                "InsertionPoint",
                                position,
                                tuple(
                                    a + b
                                    for a, b
                                    in zip(
                                        position,
                                        offset,
                                    )
                                ),
                                attr.Handle,
                                True,
                            )
                        )

                proposed[
                    other[
                        "entity_id"
                    ]
                ] = {
                    f"{kind}_{axis}":
                        other_record[
                            "geometry"
                        ][
                            f"{kind}_{axis}"
                        ]
                        + offset[i]
                    for i, axis
                    in enumerate(
                        "xyz"
                    )
                    for kind
                    in (
                        "min",
                        "max",
                    )
                }

            elif (
                obj.ObjectName
                == "AcDbLine"
            ):
                a = tuple(
                    obj.StartPoint
                )

                b = tuple(
                    obj.EndPoint
                )

                field = (
                    "StartPoint"
                    if (
                        math.dist(
                            a,
                            end,
                        )
                        < from_mm(
                            0.01,
                            units,
                        )
                    )
                    else (
                        "EndPoint"
                        if (
                            math.dist(
                                b,
                                end,
                            )
                            < from_mm(
                                0.01,
                                units,
                            )
                        )
                        else None
                    )
                )

                if field:
                    before = (
                        a
                        if field
                        == "StartPoint"
                        else b
                    )

                    other_point = (
                        b
                        if field
                        == "StartPoint"
                        else a
                    )

                    if (
                        math.dist(
                            other_point,
                            new_end,
                        )
                        < 1e-9
                    ):
                        raise ValueError(
                            "Resize would collapse "
                            "a connected line"
                        )

                    changes.append(
                        Assignment(
                            obj,
                            field,
                            before,
                            new_end,
                            other[
                                "handle"
                            ],
                            True,
                        )
                    )

                    proposed[
                        other[
                            "entity_id"
                        ]
                    ] = box_for_points(
                        (
                            new_end
                            if field
                            == "StartPoint"
                            else a
                        ),
                        (
                            new_end
                            if field
                            == "EndPoint"
                            else b
                        ),
                    )

            else:
                raise ValueError(
                    "Unsupported connected "
                    f"entity: {obj.ObjectName}"
                )

    elif (
        dimension
        == "radius"
    ):
        if (
            entity.ObjectName
            not in {
                "AcDbCircle",
                "AcDbArc",
            }
            or record[
                "entity_type"
            ]
            not in {
                "CIRCLE",
                "ARC",
            }
        ):
            raise ValueError(
                "Radius resizing currently "
                "supports CIRCLE and ARC"
            )

        before = float(
            entity.Radius
        )

        after = (
            value
            if value is not None
            else before + delta
        )

        if (
            not math.isfinite(
                after
            )
            or after <= 0
        ):
            raise ValueError(
                "New radius must be "
                "positive and finite"
            )

        changes.append(
            Assignment(
                entity,
                "Radius",
                before,
                after,
                op[
                    "handle"
                ],
                field="radius",
            )
        )

        center = tuple(
            entity.Center
        )

        if (
            math.dist(
                tuple(
                    entity.Normal
                ),
                (
                    0.0,
                    0.0,
                    1.0,
                ),
            )
            > 1e-6
        ):
            raise ValueError(
                "Radius edits currently "
                "require a circle/arc "
                "in the XY plane"
            )

        proposed[
            record[
                "entity_id"
            ]
        ] = box_for_points(
            (
                center[0]
                - after,
                center[1]
                - after,
                center[2],
            ),
            (
                center[0]
                + after,
                center[1]
                + after,
                center[2],
            ),
        )

    elif (
        dimension
        in {
            "major_axis",
            "minor_axis",
        }
    ):
        if (
            entity.ObjectName
            != "AcDbEllipse"
            or record[
                "entity_type"
            ]
            != "ELLIPSE"
        ):
            raise ValueError(
                "Ellipse axis resizing "
                "requires an ELLIPSE"
            )

        major_before = float(
            entity.MajorRadius
        )

        minor_before = float(
            entity.MinorRadius
        )

        if (
            dimension
            == "major_axis"
        ):
            major_after = (
                value
                if value is not None
                else (
                    major_before
                    + delta
                )
            )

            if (
                not math.isfinite(
                    major_after
                )
                or major_after <= 0
            ):
                raise ValueError(
                    "New major axis must be "
                    "positive and finite"
                )

            if (
                major_after
                < minor_before
            ):
                raise ValueError(
                    "Major axis cannot be "
                    "smaller than the "
                    "current minor axis"
                )

            ratio_before = float(
                entity.RadiusRatio
            )

            ratio_after = (
                minor_before
                / major_after
            )

            changes.append(
                Assignment(
                    entity,
                    "MajorRadius",
                    major_before,
                    major_after,
                    op[
                        "handle"
                    ],
                    field=
                        "major_axis",
                )
            )

            changes.append(
                Assignment(
                    entity,
                    "RadiusRatio",
                    ratio_before,
                    ratio_after,
                    op[
                        "handle"
                    ],
                    field=
                        "radius_ratio",
                )
            )

            final_major = (
                major_after
            )

            final_minor = (
                minor_before
            )

        else:
            minor_after = (
                value
                if value is not None
                else (
                    minor_before
                    + delta
                )
            )

            if (
                not math.isfinite(
                    minor_after
                )
                or minor_after <= 0
            ):
                raise ValueError(
                    "New minor axis must be "
                    "positive and finite"
                )

            if (
                minor_after
                > major_before
            ):
                raise ValueError(
                    "Minor axis cannot exceed "
                    "the current major axis"
                )

            ratio_before = float(
                entity.RadiusRatio
            )

            ratio_after = (
                minor_after
                / major_before
            )

            changes.append(
                Assignment(
                    entity,
                    "RadiusRatio",
                    ratio_before,
                    ratio_after,
                    op[
                        "handle"
                    ],
                    field=
                        "minor_axis",
                )
            )

            final_major = (
                major_before
            )

            final_minor = (
                minor_after
            )

        proposed[
            record[
                "entity_id"
            ]
        ] = _ellipse_box(
            tuple(
                entity.Center
            ),
            tuple(
                entity.MajorAxis
            ),
            tuple(
                entity.Normal
            ),
            final_major,
            final_minor,
        )

    else:
        raise ValueError(
            "Unsupported resize "
            f"dimension: {dimension}"
        )

    _validate_proposed_bounds(
        proposed,
        units,
        verb="Resize",
    )

    return changes


def _scale_box(
    box,
    basepoint,
    factor,
):
    result = {}

    for i, axis in enumerate(
        "xyz"
    ):
        low = (
            basepoint[i]
            + (
                box[
                    f"min_{axis}"
                ]
                - basepoint[i]
            )
            * factor
        )

        high = (
            basepoint[i]
            + (
                box[
                    f"max_{axis}"
                ]
                - basepoint[i]
            )
            * factor
        )

        result[
            f"min_{axis}"
        ] = min(
            low,
            high,
        )

        result[
            f"max_{axis}"
        ] = max(
            low,
            high,
        )

    return result


def _resolve_scale_basepoint(
    obj,
    op,
    record,
):
    requested = op[
        "basepoint"
    ]

    if isinstance(
        requested,
        list,
    ):
        base = tuple(
            float(value)
            for value
            in requested
        )

        if (
            len(base) != 3
            or any(
                not math.isfinite(
                    value
                )
                for value
                in base
            )
        ):
            raise ValueError(
                "Scale basepoint must "
                "contain three finite "
                "coordinates"
            )

        return base

    if (
        requested
        == "origin"
    ):
        return (
            0.0,
            0.0,
            0.0,
        )

    if (
        requested
        == "center"
    ):
        geometry = record.get(
            "geometry"
        )

        if not geometry:
            raise ValueError(
                "Scale center requires "
                "indexed bounds"
            )

        return tuple(
            (
                geometry[
                    f"min_{axis}"
                ]
                + geometry[
                    f"max_{axis}"
                ]
            )
            / 2.0
            for axis
            in "xyz"
        )

    if (
        requested
        == "insertion_point"
    ):
        if (
            record[
                "entity_type"
            ]
            != "BLOCK_REF"
            or obj.ObjectName
            != "AcDbBlockReference"
        ):
            raise ValueError(
                "insertion_point basepoint "
                "requires a block reference"
            )

        return tuple(
            obj.InsertionPoint
        )

    if (
        requested
        == "start"
    ):
        if (
            record[
                "entity_type"
            ]
            != "LINE"
            or obj.ObjectName
            != "AcDbLine"
        ):
            raise ValueError(
                "start basepoint currently "
                "requires a LINE"
            )

        return tuple(
            obj.StartPoint
        )

    raise ValueError(
        "Unsupported scale basepoint"
    )


def _scale(
    doc,
    entity,
    op,
    record,
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

    units = int(
        doc.GetVariable(
            "INSUNITS"
        )
    )

    if (
        units
        != record["units"]
    ):
        raise ValueError(
            "Live units differ from "
            "the index; save and rescan"
        )

    with connection() as conn:
        dependencies = (
            conn.execute(
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
                """,
                (
                    record[
                        "entity_id"
                    ],
                    record[
                        "entity_id"
                    ],
                ),
            )
            .fetchall()
        )

    if dependencies:
        raise ValueError(
            "Scaling a connected/"
            "dependent entity requires "
            "a supported dependency rule"
        )

    basepoint = (
        _resolve_scale_basepoint(
            entity,
            op,
            record,
        )
    )

    geometry = record.get(
        "geometry"
    )

    if not geometry:
        raise ValueError(
            "Scaling requires "
            "indexed bounds"
        )

    after_box = _scale_box(
        geometry,
        basepoint,
        factor,
    )

    _validate_proposed_bounds(
        {
            record[
                "entity_id"
            ]:
                after_box
        },
        units,
        verb="Scale",
    )

    return [
        ScaleAction(
            entity,
            basepoint,
            factor,
            op[
                "handle"
            ],
            after_box,
        )
    ]


def _prepare(
    doc,
    op,
    record,
):
    command = op[
        "command"
    ]

    obj = None

    if "handle" in op:
        obj = (
            doc.HandleToObject(
                op[
                    "handle"
                ]
            )
        )

        if (
            obj.Handle.upper()
            != op[
                "handle"
            ].upper()
        ):
            raise ValueError(
                "AutoCAD resolved "
                "a different handle"
            )

    if (
        command
        == "RESIZE_COMPONENT"
    ):
        return _resize(
            doc,
            obj,
            op,
            record,
        )

    if (
        command
        == "SCALE_ENTITY"
    ):
        return _scale(
            doc,
            obj,
            op,
            record,
        )

    if (
        command
        == "SET_ENTITY_PROPERTY"
    ):
        property_name = op[
            "property"
        ]

        if (
            property_name
            == "true_color"
        ):
            return [
                Assignment(
                    obj,
                    "TrueColor",
                    _rgb_tuple(
                        obj.TrueColor
                    ),
                    tuple(
                        op[
                            "value"
                        ]
                    ),
                    obj.Handle,
                    field=
                        "true_color",
                )
            ]

        prop = {
            "color":
                "Color",
            "layer":
                "Layer",
            "linetype":
                "Linetype",
            "text":
                "TextString",
            "attribute":
                "TextString",
            "scale_x":
                "XScaleFactor",
            "scale_y":
                "YScaleFactor",
            "scale_z":
                "ZScaleFactor",
        }[
            property_name
        ]

        if (
            property_name
            == "attribute"
        ):
            matches = [
                attribute
                for attribute
                in obj.GetAttributes()
                if (
                    attribute
                    .TagString
                    .casefold()
                    == op[
                        "attribute_tag"
                    ].casefold()
                )
            ]

            if len(matches) != 1:
                raise ValueError(
                    "Attribute tag is "
                    "absent or ambiguous"
                )

            obj = matches[0]

        if (
            property_name
            in {
                "scale_x",
                "scale_y",
                "scale_z",
            }
        ):
            if (
                record[
                    "entity_type"
                ]
                != "BLOCK_REF"
                or obj.ObjectName
                != "AcDbBlockReference"
            ):
                raise ValueError(
                    "Block scale-factor "
                    "edits require a "
                    "block reference"
                )

        if (
            prop
            == "Layer"
        ):
            doc.Layers.Item(
                op[
                    "value"
                ]
            )

        if (
            prop
            == "Linetype"
        ):
            doc.Linetypes.Item(
                op[
                    "value"
                ]
            )

        return [
            Assignment(
                obj,
                prop,
                getattr(
                    obj,
                    prop,
                ),
                op[
                    "value"
                ],
                obj.Handle,
                field=
                    property_name,
            )
        ]

    if (
        command
        == "SET_LAYER_COLOR"
    ):
        obj = (
            doc.Layers.Item(
                op[
                    "layer"
                ]
            )
        )

        return [
            Assignment(
                obj,
                "Color",
                obj.Color,
                op[
                    "color"
                ],
                field=(
                    "layer:"
                    f"{op['layer']}:"
                    "color"
                ),
            )
        ]

    prop = {
        "title":
            "Title",
        "author":
            "Author",
        "subject":
            "Subject",
        "keywords":
            "Keywords",
        "comments":
            "Comments",
        "revision":
            "RevisionNumber",
    }.get(
        op[
            "property"
        ]
    )

    if prop is None:
        return []

    return [
        Assignment(
            doc.SummaryInfo,
            prop,
            getattr(
                doc.SummaryInfo,
                prop,
            ),
            op[
                "value"
            ],
            field=(
                "summary:"
                f"{op['property']}"
            ),
        )
    ]


def rename_file(
    op,
):
    """Filesystem-only rename; session index and AutoCAD lock files gate it."""
    source = Path(
        canonical_path(
            op[
                "target_dwg_path"
            ]
        )
    )

    destination = (
        source.with_name(
            op[
                "new_name"
            ]
        )
    )

    if (
        source.suffix.lower()
        != destination.suffix.lower()
        or destination.exists()
    ):
        raise ValueError(
            "Rename must preserve "
            "the file type and may "
            "not overwrite a file"
        )

    with connection() as conn:
        opened = conn.execute(
            """
            SELECT is_open
            FROM drawing_sessions
            WHERE path=?
            """,
            (
                str(source),
            ),
        ).fetchone()

        lock_files_exist = (
            source.with_suffix(
                ".dwl"
            ).exists()
            or source.with_suffix(
                ".dwl2"
            ).exists()
        )

        if (
            opened
            and opened[0]
            and not lock_files_exist
        ):
            conn.execute(
                """
                UPDATE drawing_sessions
                SET is_open=0
                WHERE path=?
                """,
                (
                    str(source),
                ),
            )

            opened = None

        if (
            (
                opened
                and opened[0]
            )
            or lock_files_exist
        ):
            raise ValueError(
                "Close the drawing "
                "in AutoCAD before renaming"
            )

        source.rename(
            destination
        )

        try:
            conn.execute(
                """
                UPDATE drawings
                SET
                    path=?,
                    filename=?,
                    scan_status='pending'
                WHERE path=?
                """,
                (
                    str(
                        destination
                    ),
                    destination.name,
                    str(source),
                ),
            )

            conn.execute(
                """
                DELETE
                FROM drawing_sessions
                WHERE path=?
                """,
                (
                    str(source),
                ),
            )

        except Exception:
            destination.rename(
                source
            )

            raise

    return {
        "path":
            str(destination),
        "changes": [
            {
                "handle":
                    None,
                "field":
                    "path",
                "before":
                    str(source),
                "after":
                    str(
                        destination
                    ),
            }
        ],
    }


def _backup_before_edit(
    path,
    preexisting_backup_path,
):
    if (
        preexisting_backup_path
        is not None
    ):
        backup = Path(
            preexisting_backup_path
        ).resolve(
            strict=True
        )

        if (
            not backup.is_file()
            or backup
            == Path(path)
        ):
            raise ValueError(
                "A separate, existing "
                "backup file is required "
                "before editing"
            )

        return str(
            backup
        )

    from src.backup import (
        backup_file,
    )

    return str(
        backup_file(
            Path(path)
        )
    )


def _saved_bbox(
    snapshot,
    handle,
):
    for box in (
        snapshot.spatial_data
    ):
        if (
            box.handle
            == handle
        ):
            return {
                f"min_{axis}":
                    box.minimum[i]
                for i, axis
                in enumerate(
                    "xyz"
                )
            } | {
                f"max_{axis}":
                    box.maximum[i]
                for i, axis
                in enumerate(
                    "xyz"
                )
            }

    return None


def _boxes_close(
    left,
    right,
    tolerance=1e-5,
):
    return (
        left is not None
        and all(
            math.isclose(
                float(
                    left[key]
                ),
                float(
                    right[key]
                ),
                rel_tol=
                    tolerance,
                abs_tol=
                    tolerance,
            )
            for key
            in right
        )
    )


def _verify_saved_result(
    snapshot,
    operation,
    changes,
):
    command = operation[
        "command"
    ]

    if (
        command
        == "RESIZE_COMPONENT"
    ):
        handle = operation[
            "handle"
        ]

        props = (
            snapshot
            .properties
            .get(
                handle
            )
        )

        if props is None:
            raise ValueError(
                "Saved-file re-extraction "
                "lost the edited entity"
            )

        key_by_property = {
            "EndPoint":
                "end",
            "Radius":
                "radius",
            "MajorRadius":
                "major_radius",
            "RadiusRatio":
                "radius_ratio",
        }

        for change in changes:
            if (
                isinstance(
                    change,
                    ScaleAction,
                )
                or change.handle
                != handle
            ):
                continue

            key = (
                key_by_property
                .get(
                    change.property
                )
            )

            if key is None:
                continue

            actual = props.get(
                key
            )

            expected = (
                list(
                    change.after
                )
                if change.is_point
                else change.after
            )

            if change.is_point:
                if (
                    actual is None
                    or math.dist(
                        tuple(actual),
                        tuple(
                            expected
                        ),
                    )
                    > 1e-6
                ):
                    raise ValueError(
                        "Saved-file "
                        "re-extraction did not "
                        "confirm the resize"
                    )

            elif (
                actual is None
                or not math.isclose(
                    float(actual),
                    float(
                        expected
                    ),
                    rel_tol=1e-7,
                    abs_tol=1e-7,
                )
            ):
                raise ValueError(
                    "Saved-file re-extraction "
                    "did not confirm the resize"
                )

        return

    if (
        command
        == "SCALE_ENTITY"
    ):
        action = changes[0]

        if not isinstance(
            action,
            ScaleAction,
        ):
            raise ValueError(
                "Scale verification "
                "metadata is missing"
            )

        if (
            operation[
                "handle"
            ]
            not in snapshot.properties
        ):
            raise ValueError(
                "Saved-file re-extraction "
                "lost the scaled entity"
            )

        actual_box = _saved_bbox(
            snapshot,
            operation[
                "handle"
            ],
        )

        if not _boxes_close(
            actual_box,
            action.after_box,
        ):
            raise ValueError(
                "Saved-file re-extraction "
                "did not confirm the scale"
            )

        return

    if (
        command
        == "SET_ENTITY_PROPERTY"
        and operation[
            "property"
        ]
        != "attribute"
    ):
        handle = operation[
            "handle"
        ]

        props = (
            snapshot
            .properties
            .get(
                handle
            )
        )

        key = {
            "color":
                "color",
            "true_color":
                "true_color",
            "layer":
                "layer",
            "linetype":
                "linetype",
            "text":
                "text",
            "scale_x":
                "xscale",
            "scale_y":
                "yscale",
            "scale_z":
                "zscale",
        }[
            operation[
                "property"
            ]
        ]

        expected = (
            list(
                changes[0].after
            )
            if (
                operation[
                    "property"
                ]
                == "true_color"
            )
            else changes[0].after
        )

        actual = (
            props.get(
                key
            )
            if props
            else None
        )

        if (
            key
            in {
                "layer",
                "linetype",
            }
        ):
            matches = (
                actual is not None
                and str(
                    actual
                ).casefold()
                == str(
                    expected
                ).casefold()
            )

        elif (
            key
            in {
                "xscale",
                "yscale",
                "zscale",
            }
        ):
            matches = (
                actual is not None
                and math.isclose(
                    float(
                        actual
                    ),
                    float(
                        expected
                    ),
                    rel_tol=1e-9,
                    abs_tol=1e-9,
                )
            )

        else:
            matches = (
                actual
                == expected
            )

        if (
            props is None
            or not matches
        ):
            raise ValueError(
                "Saved-file re-extraction "
                "did not confirm the "
                "property change"
            )

        return

    if (
        command
        == "SET_LAYER_COLOR"
    ):
        layers = (
            snapshot
            .document
            .properties
            .get(
                "_layers",
                {},
            )
        )

        layer = layers.get(
            operation[
                "layer"
            ]
        )

        if (
            layer is None
            or int(
                layer.get(
                    "color",
                    -1,
                )
            )
            != int(
                operation[
                    "color"
                ]
            )
        ):
            raise ValueError(
                "Saved-file re-extraction "
                "did not confirm the "
                "layer color"
            )

        return

    if (
        command
        == "SET_DOCUMENT_PROPERTY"
    ):
        summary = (
            snapshot
            .document
            .properties
            .get(
                "_summary_info",
                {},
            )
        )

        if (
            operation[
                "property"
            ]
            == "custom"
        ):
            actual = (
                summary
                .get(
                    "custom",
                    {},
                )
                .get(
                    operation[
                        "key"
                    ]
                )
            )
        else:
            actual = summary.get(
                operation[
                    "property"
                ]
            )

        if (
            actual
            != operation[
                "value"
            ]
        ):
            raise ValueError(
                "Saved-file re-extraction "
                "did not confirm the "
                "document property"
            )


def execute_operation(
    operation,
    *,
    acad=None,
    entity_id=None,
    verify_extractor=None,
    _preexisting_backup_path=None,
    project_id=None,
):
    validate_operation(
        operation
    )

    path = canonical_path(
        operation[
            "target_dwg_path"
        ]
    )

    with CAD_LOCK:
        if (
            operation[
                "command"
            ]
            == "RENAME_FILE"
        ):
            backup = (
                _backup_before_edit(
                    path,
                    _preexisting_backup_path,
                )
            )

            return dict(
                rename_file(
                    operation
                ),
                backup_path=
                    backup,
            )

        record = (
            _indexed_record(
                path,
                operation[
                    "handle"
                ],
                entity_id,
                project_id,
            )
            if "handle"
            in operation
            else None
        )

        if record:
            _verify_index(
                record,
                path,
            )

        with cad_session(
            acad
        ) as session:
            doc = get_document(
                session,
                path,
            )

            if not doc.Saved:
                raise ValueError(
                    "Save or discard "
                    "existing unsaved edits "
                    "before modifying "
                    "this drawing"
                )

            changes = _prepare(
                doc,
                operation,
                record,
            )

            backup = (
                _backup_before_edit(
                    path,
                    _preexisting_backup_path,
                )
            )

            applied = []

            custom = (
                operation[
                    "command"
                ]
                == "SET_DOCUMENT_PROPERTY"
                and operation[
                    "property"
                ]
                == "custom"
            )

            try:
                if custom:
                    info = (
                        doc.SummaryInfo
                    )

                    key = operation[
                        "key"
                    ]

                    try:
                        before = (
                            info.GetCustomByKey(
                                key
                            )
                        )
                    except Exception:
                        info.AddCustomInfo(
                            key,
                            operation[
                                "value"
                            ],
                        )

                        before = None
                    else:
                        info.SetCustomByKey(
                            key,
                            operation[
                                "value"
                            ],
                        )

                    summary = [
                        {
                            "handle":
                                None,
                            "field":
                                (
                                    "custom:"
                                    f"{key}"
                                ),
                            "before":
                                before,
                            "after":
                                operation[
                                    "value"
                                ],
                        }
                    ]

                else:
                    for change in changes:
                        applied.append(
                            change
                        )

                        _apply_change(
                            change
                        )

                    for change in changes:
                        _verify_live_assignment(
                            change
                        )

                    summary = [
                        change.summary()
                        for change
                        in changes
                    ]

                _com_retry(
                    lambda:
                        doc.Save(),
                    "saving document",
                )

            except Exception as original_exc:
                rollback_errors = []

                for change in reversed(
                    applied
                ):
                    try:
                        _rollback_change(
                            change
                        )
                    except Exception as rollback_exc:
                        label = getattr(
                            change,
                            "property",
                            "scale",
                        )

                        rollback_errors.append(
                            f"{label} on "
                            f"{change.handle}: "
                            f"{rollback_exc}"
                        )

                if (
                    custom
                    and "before"
                    in locals()
                ):
                    try:
                        if (
                            before
                            is None
                        ):
                            info.RemoveCustomByKey(
                                key
                            )
                        else:
                            info.SetCustomByKey(
                                key,
                                before,
                            )
                    except Exception as rollback_exc:
                        rollback_errors.append(
                            f"custom:{key}: "
                            f"{rollback_exc}"
                        )

                if rollback_errors:
                    raise RuntimeError(
                        "Edit failed "
                        f"({type(original_exc).__name__}: "
                        f"{original_exc}) and "
                        "rollback could not fully "
                        "undo it — the live document "
                        "may be left partially "
                        "modified (unsaved): "
                        + "; ".join(
                            rollback_errors
                        )
                    ) from original_exc

                raise

        snapshot = (
            verify_extractor.extract(
                path
            )
            if verify_extractor
            else None
        )

        if snapshot:
            _verify_saved_result(
                snapshot,
                operation,
                changes,
            )

        return {
            "path":
                path,
            "changes":
                summary,
            "verified_by_extraction":
                snapshot is not None,
            "backup_path":
                backup,
        }

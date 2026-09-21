"""Offline DXF/DWG extraction. DWG conversion is an injected dependency."""
import math
import re
from pathlib import Path
from tempfile import TemporaryDirectory

import ezdxf
from ezdxf import bbox

from .base import (
    DrawingExtractor,
    DrawingSnapshot,
    DocumentMetadata,
    EntityRecord,
    BlockRecord,
    BoundingBox,
)
from .converter import (
    DWGToDXFConverter,
)


_DWGPROPS_CODES = {
    2:
        "title",
    3:
        "subject",
    4:
        "author",
    6:
        "comments",
    7:
        "keywords",
    8:
        "last_saved_by",
    9:
        "revision",
}


_TAG_TEXT_PATTERN = re.compile(
    (
        r"(?<![A-Za-z0-9])"
        r"("
        r"[A-Za-z]"
        r"[A-Za-z0-9]{0,15}"
        r"-"
        r"\d{1,6}"
        r"[A-Za-z0-9-]{0,12}"
        r")"
        r"(?![A-Za-z0-9])"
    )
)


_PROXIMITY_TARGET_TYPES = {
    "BLOCK_REF",
    "LINE",
    "CIRCLE",
    "ARC",
    "ELLIPSE",
    "LWPOLYLINE",
    "POLYLINE",
}


def _json_value(
    value,
):
    if (
        isinstance(
            value,
            (
                str,
                int,
                float,
                bool,
            ),
        )
        or value is None
    ):
        return value

    try:
        return [
            _json_value(v)
            for v
            in value
        ]
    except TypeError:
        return str(
            value
        )


def _rgb_list(
    value,
):
    if value is None:
        return None

    try:
        return [
            int(value[0]),
            int(value[1]),
            int(value[2]),
        ]
    except (
        TypeError,
        IndexError,
    ):
        return None


def _extract_summary_info(
    doc,
):
    summary = {
        name: ""
        for name
        in _DWGPROPS_CODES.values()
    }

    summary[
        "hyperlink_base"
    ] = str(
        doc.header.get(
            "$HYPERLINKBASE",
            "",
        )
        or ""
    )

    summary[
        "custom"
    ] = {}

    try:
        record = (
            doc.rootdict.get(
                "DWGPROPS"
            )
        )
    except Exception:
        record = None

    if (
        record is None
        or not hasattr(
            record,
            "tags",
        )
    ):
        return summary

    for tag in record.tags:
        if (
            tag.code
            in _DWGPROPS_CODES
        ):
            summary[
                _DWGPROPS_CODES[
                    tag.code
                ]
            ] = str(
                tag.value
            )

        elif (
            300
            <= tag.code
            <= 309
            and isinstance(
                tag.value,
                str,
            )
        ):
            (
                key,
                separator,
                value,
            ) = (
                tag.value
                .partition(
                    "="
                )
            )

            if (
                separator
                and key
            ):
                summary[
                    "custom"
                ][
                    key
                ] = value

    return summary


def _extract_layers(
    doc,
):
    result = {}

    for layer in doc.layers:
        name = str(
            layer.dxf.name
        )

        result[
            name
        ] = {
            "color":
                int(
                    layer.dxf.get(
                        "color",
                        7,
                    )
                ),
            "true_color":
                _rgb_list(
                    getattr(
                        layer,
                        "rgb",
                        None,
                    )
                ),
            "linetype":
                str(
                    layer.dxf.get(
                        "linetype",
                        "CONTINUOUS",
                    )
                ),
            "is_off":
                bool(
                    layer.is_off()
                ),
            "is_frozen":
                bool(
                    layer.is_frozen()
                ),
            "is_locked":
                bool(
                    layer.is_locked()
                ),
        }

    return result


def _polyline_coordinates(
    entity,
    kind,
):
    if (
        kind
        == "LWPOLYLINE"
    ):
        elevation = float(
            entity.dxf.get(
                "elevation",
                0.0,
            )
        )

        return [
            [
                float(x),
                float(y),
                elevation,
            ]
            for x, y
            in entity.get_points(
                "xy"
            )
        ]

    if (
        kind
        == "POLYLINE"
    ):
        return [
            [
                float(
                    vertex
                    .dxf
                    .location
                    .x
                ),
                float(
                    vertex
                    .dxf
                    .location
                    .y
                ),
                float(
                    vertex
                    .dxf
                    .location
                    .z
                ),
            ]
            for vertex
            in entity.vertices
        ]

    return None


def _box_distance(
    left,
    right,
):
    squared = 0.0

    for index in range(
        3
    ):
        if (
            left.maximum[index]
            < right.minimum[index]
        ):
            gap = (
                right.minimum[index]
                - left.maximum[index]
            )

        elif (
            right.maximum[index]
            < left.minimum[index]
        ):
            gap = (
                left.minimum[index]
                - right.maximum[index]
            )

        else:
            gap = 0.0

        squared += (
            gap
            * gap
        )

    return math.sqrt(
        squared
    )


def _associate_proximity_tags(
    metadata,
    entities,
    properties,
    spatial,
    *,
    distance_mm,
    ambiguity_mm,
):
    if (
        distance_mm <= 0
        or ambiguity_mm < 0
    ):
        raise ValueError(
            "Proximity tag distances "
            "must be non-negative"
        )

    if metadata.units == 0:
        metadata.warnings.append(
            "Nearby TEXT/MTEXT tag association "
            "skipped because drawing units "
            "are unspecified."
        )

        return

    from src.cad.units import (
        from_mm,
    )

    max_distance = from_mm(
        distance_mm,
        metadata.units,
    )

    ambiguity_distance = from_mm(
        ambiguity_mm,
        metadata.units,
    )

    boxes = {
        box.handle:
            box
        for box
        in spatial
    }

    assignments = {}

    conflicted_targets = (
        set()
    )

    labels = []

    for entity in entities:
        if (
            entity.entity_type
            not in {
                "TEXT",
                "MTEXT",
            }
        ):
            continue

        text = str(
            properties
            .get(
                entity.handle,
                {},
            )
            .get(
                "text"
            )
            or ""
        )

        match = (
            _TAG_TEXT_PATTERN
            .search(
                text
            )
        )

        if (
            match
            and entity.handle
            in boxes
        ):
            labels.append(
                (
                    entity.handle,
                    match.group(
                        1
                    ),
                )
            )

    for (
        label_handle,
        label_tag,
    ) in labels:
        label_box = boxes[
            label_handle
        ]

        candidates = []

        for candidate in entities:
            if (
                candidate.handle
                == label_handle
            ):
                continue

            if (
                candidate.entity_type
                not in
                _PROXIMITY_TARGET_TYPES
            ):
                continue

            candidate_box = (
                boxes.get(
                    candidate.handle
                )
            )

            if (
                candidate_box
                is None
            ):
                continue

            distance = (
                _box_distance(
                    label_box,
                    candidate_box,
                )
            )

            if (
                distance
                <= max_distance
            ):
                candidates.append(
                    (
                        distance,
                        candidate,
                    )
                )

        candidates.sort(
            key=lambda item: (
                item[0],
                item[1].handle,
            )
        )

        if not candidates:
            continue

        if (
            len(
                candidates
            )
            > 1
            and (
                candidates[1][0]
                - candidates[0][0]
            )
            <= ambiguity_distance
        ):
            metadata.warnings.append(
                (
                    "Proximity tag "
                    f"{label_tag} was not "
                    "associated: nearest "
                    "candidates are ambiguous."
                )
            )

            continue

        target = (
            candidates[0][1]
        )

        if (
            target.tag_source
            == "explicit"
            or (
                target.tag
                and target.tag_source
                != "proximity"
            )
        ):
            continue

        if (
            target.handle
            in conflicted_targets
        ):
            continue

        previous = (
            assignments.get(
                target.handle
            )
        )

        if (
            previous is not None
            and previous.casefold()
            != label_tag.casefold()
        ):
            target.tag = None

            target.tag_source = (
                "none"
            )

            conflicted_targets.add(
                target.handle
            )

            metadata.warnings.append(
                (
                    "Proximity tags "
                    f"{previous} and "
                    f"{label_tag} compete "
                    "for handle "
                    f"{target.handle}; "
                    "no tag was associated."
                )
            )

            continue

        target.tag = label_tag

        target.tag_source = (
            "proximity"
        )

        assignments[
            target.handle
        ] = label_tag


class DXFExtractor(
    DrawingExtractor
):
    def __init__(
        self,
        converter:
            DWGToDXFConverter
            | None
            = None,
        *,
        proximity_tag_distance_mm:
            float
            = 250.0,
        proximity_tag_ambiguity_mm:
            float
            = 25.0,
    ):
        self.converter = (
            converter
        )

        self.proximity_tag_distance_mm = (
            float(
                proximity_tag_distance_mm
            )
        )

        self.proximity_tag_ambiguity_mm = (
            float(
                proximity_tag_ambiguity_mm
            )
        )

        self._key = None
        self._snapshot = None

    def extract(
        self,
        source,
    ) -> DrawingSnapshot:
        path = Path(
            source
        ).resolve(
            strict=True
        )

        stat = path.stat()

        key = (
            str(path),
            stat.st_size,
            stat.st_mtime_ns,
        )

        if (
            self._key
            == key
        ):
            return (
                self._snapshot
            )

        if (
            path.suffix.lower()
            == ".dxf"
        ):
            snapshot = self._parse(
                ezdxf.readfile(
                    path
                ),
                path,
            )

        elif (
            path.suffix.lower()
            == ".dwg"
        ):
            if (
                self.converter
                is None
            ):
                from .oda import (
                    require_oda_converter,
                )

                self.converter = (
                    require_oda_converter()
                )

            with TemporaryDirectory(
                prefix=
                    "cad-extract-"
            ) as directory:
                dxf = (
                    self.converter
                    .convert(
                        path,
                        Path(
                            directory
                        ),
                    )
                )

                snapshot = (
                    self._parse(
                        ezdxf.readfile(
                            dxf
                        ),
                        path,
                    )
                )

        else:
            raise ValueError(
                "Expected a .dwg "
                "or .dxf file"
            )

        self._key = key
        self._snapshot = snapshot

        return snapshot

    def _parse(
        self,
        doc,
        path,
    ):
        document_properties = dict(
            doc.header.custom_vars
        )

        document_properties[
            "_summary_info"
        ] = _extract_summary_info(
            doc
        )

        document_properties[
            "_layers"
        ] = _extract_layers(
            doc
        )

        metadata = DocumentMetadata(
            str(path),
            path.name,
            int(
                doc.units
            ),
            document_properties,
            [
                (
                    "DXF does not expose "
                    "full dynamic-block or "
                    "associative-constraint "
                    "semantics."
                )
            ],
        )

        entities = []
        properties = {}
        spatial = []

        blocks = [
            BlockRecord(
                block.name,
                block
                .block_record
                .dxf
                .handle,
                False,
            )
            for block
            in doc.blocks
            if not block.name.startswith(
                "*"
            )
        ]

        for layout in doc.layouts:
            for entity in layout:
                handle = (
                    entity.dxf.handle
                )

                kind = (
                    entity.dxftype()
                )

                attrs = {
                    attribute.dxf.tag:
                        attribute.dxf.text
                    for attribute
                    in getattr(
                        entity,
                        "attribs",
                        [],
                    )
                }

                values = {
                    key:
                        _json_value(
                            value
                        )
                    for key, value
                    in (
                        entity
                        .dxf
                        .all_existing_dxf_attribs()
                        .items()
                    )
                }

                values.update(
                    layout=
                        layout.name,
                    attributes=
                        attrs,
                    color=
                        entity.dxf.get(
                            "color",
                            256,
                        ),
                    true_color=
                        _rgb_list(
                            getattr(
                                entity,
                                "rgb",
                                None,
                            )
                        ),
                    linetype=
                        entity.dxf.get(
                            "linetype",
                            "BYLAYER",
                        ),
                )

                if (
                    kind
                    == "MTEXT"
                ):
                    values[
                        "text"
                    ] = (
                        entity.plain_text()
                    )

                if (
                    kind
                    in {
                        "LWPOLYLINE",
                        "POLYLINE",
                    }
                ):
                    values[
                        "coordinates"
                    ] = (
                        _polyline_coordinates(
                            entity,
                            kind,
                        )
                    )

                    values[
                        "closed"
                    ] = bool(
                        entity.closed
                        if kind
                        == "LWPOLYLINE"
                        else entity.is_closed
                    )

                elif (
                    kind
                    == "INSERT"
                ):
                    values.update(
                        xscale=
                            float(
                                entity.dxf.get(
                                    "xscale",
                                    1.0,
                                )
                            ),
                        yscale=
                            float(
                                entity.dxf.get(
                                    "yscale",
                                    1.0,
                                )
                            ),
                        zscale=
                            float(
                                entity.dxf.get(
                                    "zscale",
                                    1.0,
                                )
                            ),
                    )

                elif (
                    kind
                    == "ELLIPSE"
                ):
                    major_axis = tuple(
                        entity
                        .dxf
                        .major_axis
                    )

                    major_radius = (
                        math.dist(
                            (
                                0.0,
                                0.0,
                                0.0,
                            ),
                            major_axis,
                        )
                    )

                    ratio = float(
                        entity
                        .dxf
                        .ratio
                    )

                    values.update(
                        major_axis=
                            list(
                                major_axis
                            ),
                        radius_ratio=
                            ratio,
                        major_radius=
                            major_radius,
                        minor_radius=
                            (
                                major_radius
                                * ratio
                            ),
                    )

                xdata = {}

                if entity.xdata:
                    xdata = {
                        app: [
                            [
                                tag.code,
                                _json_value(
                                    tag.value
                                ),
                            ]
                            for tag
                            in tags
                        ]
                        for app, tags
                        in (
                            entity
                            .xdata
                            .data
                            .items()
                        )
                    }

                values[
                    "xdata"
                ] = xdata

                tag = next(
                    (
                        value
                        for key, value
                        in attrs.items()
                        if (
                            key.upper()
                            in {
                                "TAG",
                                "COMPONENT_TAG",
                                "P_TAG",
                            }
                        )
                    ),
                    None,
                )

                for tags in (
                    xdata.values()
                ):
                    for (
                        code,
                        value,
                    ) in tags:
                        if (
                            code == 1000
                            and isinstance(
                                value,
                                str,
                            )
                            and value
                            .upper()
                            .startswith(
                                "TAG="
                            )
                        ):
                            tag = (
                                tag
                                or value[4:]
                            )

                tag_source = (
                    "explicit"
                    if (
                        tag
                        and str(
                            tag
                        ).strip()
                    )
                    else "none"
                )

                entities.append(
                    EntityRecord(
                        handle,
                        (
                            "BLOCK_REF"
                            if kind
                            == "INSERT"
                            else kind
                        ),
                        entity.dxf.get(
                            "layer",
                            "0",
                        ),
                        tag,
                        tag_source,
                    )
                )

                properties[
                    handle
                ] = values

                if (
                    kind
                    == "INSERT"
                ):
                    blocks.append(
                        BlockRecord(
                            entity.dxf.name,
                            handle,
                            True,
                            attrs,
                        )
                    )

                if (
                    kind
                    in {
                        "ACAD_PROXY_ENTITY",
                        "ACAD_PROXY_OBJECT",
                    }
                ):
                    metadata.warnings.append(
                        f"Proxy {handle}: "
                        "vertical SDK semantics "
                        "are unavailable"
                    )

                start = (
                    tuple(
                        entity.dxf.start
                    )
                    if kind
                    == "LINE"
                    else None
                )

                end = (
                    tuple(
                        entity.dxf.end
                    )
                    if kind
                    == "LINE"
                    else None
                )

                points = (
                    [
                        start,
                        end,
                    ]
                    if start
                    else []
                )

                if (
                    kind
                    == "INSERT"
                ):
                    points = [
                        tuple(
                            entity.dxf.insert
                        )
                    ]

                elif (
                    kind
                    in {
                        "LWPOLYLINE",
                        "POLYLINE",
                    }
                ):
                    points = [
                        tuple(point)
                        for point
                        in values[
                            "coordinates"
                        ]
                    ]

                try:
                    box = bbox.extents(
                        [
                            entity
                        ]
                    )

                    if box.has_data:
                        spatial.append(
                            BoundingBox(
                                handle,
                                tuple(
                                    box.extmin
                                ),
                                tuple(
                                    box.extmax
                                ),
                                start,
                                end,
                                points,
                            )
                        )

                    elif points:
                        spatial.append(
                            BoundingBox(
                                handle,
                                points[0],
                                points[-1],
                                start,
                                end,
                                points,
                            )
                        )

                except Exception as exc:
                    metadata.warnings.append(
                        "No bounds for "
                        f"{handle}: "
                        f"{type(exc).__name__}"
                    )

        _associate_proximity_tags(
            metadata,
            entities,
            properties,
            spatial,
            distance_mm=
                self
                .proximity_tag_distance_mm,
            ambiguity_mm=
                self
                .proximity_tag_ambiguity_mm,
        )

        from src.cad.relationships import (
            infer_connections,
        )

        from src.cad.units import (
            from_mm,
        )

        tolerance = (
            from_mm(
                0.01,
                metadata.units,
            )
            if metadata.units
            else 1e-6
        )

        relationships = (
            infer_connections(
                spatial,
                properties,
                tolerance,
            )
        )

        return DrawingSnapshot(
            metadata,
            entities,
            blocks,
            properties,
            relationships,
            spatial,
        )

    def extract_document(
        self,
        source,
    ):
        return self.extract(
            source
        ).document

    def extract_entities(
        self,
        source,
    ):
        return self.extract(
            source
        ).entities

    def extract_blocks(
        self,
        source,
    ):
        return self.extract(
            source
        ).blocks

    def extract_properties(
        self,
        source,
    ):
        return self.extract(
            source
        ).properties

    def extract_relationships(
        self,
        source,
    ):
        return self.extract(
            source
        ).relationships

    def extract_spatial_data(
        self,
        source,
    ):
        return self.extract(
            source
        ).spatial_data

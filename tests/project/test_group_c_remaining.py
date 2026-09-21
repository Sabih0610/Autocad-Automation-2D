from __future__ import annotations

from pathlib import Path

import ezdxf
import pytest
from ezdxf.lldxf.types import DXFTag
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes import projects as project_routes
from src.cad.changes import ChangeManager
from src.cad.extractor import DXFExtractor
from src.cad.orchestrator import ProjectOrchestrator
from src.cad.scanner import (
    list_drawings,
    scan_project,
)
from src.framework.commands import (
    modification_executor as engine,
)
from src.storage.database import connection
from src.storage.entity_repository import (
    get_drawing_layers,
    get_drawing_summary,
)
from src.storage.project_repository import (
    register_project,
)
from tests.project.fake_cad import (
    Acad,
    Document,
)


def _new_doc(
    path: Path,
):
    doc = ezdxf.new(
        "R2010"
    )

    doc.units = 4

    doc.appids.new(
        "AUTOCAD_AI"
    )

    return doc


def _tag(
    entity,
    tag: str,
):
    entity.set_xdata(
        "AUTOCAD_AI",
        [
            (
                1000,
                f"TAG={tag}",
            )
        ],
    )

    return entity


def _register_and_scan(
    tmp_path: Path,
):
    project_id = (
        register_project(
            "Group C",
            str(
                tmp_path
            ),
        )
    )

    result = scan_project(
        project_id,
        max_workers=1,
    )

    assert (
        result[
            "errors"
        ]
        == []
    )

    return project_id


def _execute_planned(
    project_id,
    prompt,
    tag,
    draft,
    *,
    acad=None,
):
    def planner(
        _prompt,
        _context,
    ):
        return dict(
            draft
        )

    orchestrator = (
        ProjectOrchestrator(
            planner=
                planner,
            manager=
                ChangeManager(
                    acad=
                        acad
                        or Acad()
                ),
        )
    )

    job = orchestrator.plan(
        project_id,
        prompt,
        tag=tag,
    )

    assert (
        job["status"]
        == "pending"
    )

    result = (
        orchestrator.execute(
            job[
                "job_id"
            ]
        )
    )

    assert (
        result["status"]
        == "done"
    ), result

    return (
        job,
        result,
    )


@pytest.mark.parametrize(
    "kind,tag",
    [
        (
            "LWPOLYLINE",
            "PL-101",
        ),
        (
            "POLYLINE",
            "PL-102",
        ),
    ],
)
def test_polyline_scale_roundtrip_preserves_handle(
    tmp_path,
    kind,
    tag,
):
    path = (
        tmp_path
        / f"{kind.lower()}.dxf"
    )

    doc = _new_doc(
        path
    )

    msp = doc.modelspace()

    if (
        kind
        == "LWPOLYLINE"
    ):
        entity = (
            msp.add_lwpolyline(
                [
                    (
                        10,
                        10,
                    ),
                    (
                        20,
                        10,
                    ),
                    (
                        20,
                        20,
                    ),
                ]
            )
        )

    else:
        entity = (
            msp.add_polyline3d(
                [
                    (
                        10,
                        10,
                        0,
                    ),
                    (
                        20,
                        10,
                        0,
                    ),
                    (
                        20,
                        20,
                        5,
                    ),
                ]
            )
        )

    _tag(
        entity,
        tag,
    )

    handle = (
        entity.dxf.handle
    )

    doc.saveas(
        path
    )

    project_id = (
        _register_and_scan(
            tmp_path
        )
    )

    _execute_planned(
        project_id,
        (
            f"scale {tag} "
            "by 2 from origin"
        ),
        tag,
        {
            "command":
                "SCALE_ENTITY",
            "factor":
                2.0,
            "basepoint":
                "origin",
        },
    )

    snapshot = (
        DXFExtractor()
        .extract(
            path
        )
    )

    props = snapshot.properties[
        handle
    ]

    assert (
        handle
        in snapshot.properties
    )

    coordinates = props[
        "coordinates"
    ]

    assert (
        coordinates[0]
        == pytest.approx(
            [
                20.0,
                20.0,
                0.0,
            ]
        )
    )

    assert (
        coordinates[1][
            :2
        ]
        == pytest.approx(
            [
                40.0,
                20.0,
            ]
        )
    )


def test_insert_scale_factor_roundtrip_preserves_handle(
    tmp_path,
):
    path = (
        tmp_path
        / "block.dxf"
    )

    doc = _new_doc(
        path
    )

    block = (
        doc.blocks.new(
            "PUMP"
        )
    )

    block.add_circle(
        (
            0,
            0,
        ),
        5,
    )

    ref = (
        doc.modelspace()
        .add_blockref(
            "PUMP",
            (
                100,
                100,
                0,
            ),
        )
    )

    ref.add_attrib(
        "TAG",
        "B-101",
        (
            100,
            100,
            0,
        ),
    )

    handle = (
        ref.dxf.handle
    )

    doc.saveas(
        path
    )

    project_id = (
        _register_and_scan(
            tmp_path
        )
    )

    _execute_planned(
        project_id,
        (
            "set B-101 "
            "x scale to 2"
        ),
        "B-101",
        {
            "command":
                "SET_ENTITY_PROPERTY",
            "property":
                "scale_x",
            "value":
                2.0,
        },
    )

    snapshot = (
        DXFExtractor()
        .extract(
            path
        )
    )

    props = snapshot.properties[
        handle
    ]

    assert (
        props[
            "xscale"
        ]
        == pytest.approx(
            2.0
        )
    )


def test_ellipse_major_and_minor_axis_roundtrip_preserve_handle(
    tmp_path,
):
    path = (
        tmp_path
        / "ellipse.dxf"
    )

    doc = _new_doc(
        path
    )

    ellipse = _tag(
        doc.modelspace()
        .add_ellipse(
            (
                100,
                100,
                0,
            ),
            major_axis=(
                20,
                0,
                0,
            ),
            ratio=0.5,
        ),
        "E-101",
    )

    handle = (
        ellipse.dxf.handle
    )

    doc.saveas(
        path
    )

    project_id = (
        _register_and_scan(
            tmp_path
        )
    )

    _execute_planned(
        project_id,
        (
            "increase E-101 "
            "major axis by 10 mm"
        ),
        "E-101",
        {
            "command":
                "RESIZE_COMPONENT",
            "dimension":
                "major_axis",
            "delta_mm":
                10,
        },
    )

    props = (
        DXFExtractor()
        .extract(
            path
        )
        .properties[
            handle
        ]
    )

    assert (
        props[
            "major_radius"
        ]
        == pytest.approx(
            30.0
        )
    )

    assert (
        props[
            "minor_radius"
        ]
        == pytest.approx(
            10.0
        )
    )

    with connection() as conn:
        pending = (
            conn.execute(
                """
                SELECT change_set_id
                FROM change_sets
                WHERE status='pending'
                ORDER BY created_at DESC
                LIMIT 1
                """
            )
            .fetchone()[0]
        )

    ChangeManager(
        acad=Acad()
    ).keep(
        pending
    )

    _execute_planned(
        project_id,
        (
            "increase E-101 "
            "minor axis by 5 mm"
        ),
        "E-101",
        {
            "command":
                "RESIZE_COMPONENT",
            "dimension":
                "minor_axis",
            "delta_mm":
                5,
        },
    )

    props = (
        DXFExtractor()
        .extract(
            path
        )
        .properties[
            handle
        ]
    )

    assert (
        props[
            "major_radius"
        ]
        == pytest.approx(
            30.0
        )
    )

    assert (
        props[
            "minor_radius"
        ]
        == pytest.approx(
            15.0
        )
    )


def test_true_color_roundtrip_preserves_handle(
    tmp_path,
):
    path = (
        tmp_path
        / "truecolor.dxf"
    )

    doc = _new_doc(
        path
    )

    line = _tag(
        doc.modelspace()
        .add_line(
            (
                0,
                0,
                0,
            ),
            (
                100,
                0,
                0,
            ),
        ),
        "L-101",
    )

    handle = (
        line.dxf.handle
    )

    doc.saveas(
        path
    )

    project_id = (
        _register_and_scan(
            tmp_path
        )
    )

    _execute_planned(
        project_id,
        (
            "set L-101 true "
            "color to 12 34 56"
        ),
        "L-101",
        {
            "command":
                "SET_ENTITY_PROPERTY",
            "property":
                "true_color",
            "value": [
                12,
                34,
                56,
            ],
        },
    )

    props = (
        DXFExtractor()
        .extract(
            path
        )
        .properties[
            handle
        ]
    )

    assert (
        props[
            "true_color"
        ]
        == [
            12,
            34,
            56,
        ]
    )


def test_partial_arc_plan_uses_indexed_radius_not_bbox(
    tmp_path,
):
    path = (
        tmp_path
        / "arc.dxf"
    )

    doc = _new_doc(
        path
    )

    _tag(
        doc.modelspace()
        .add_arc(
            (
                100,
                100,
                0,
            ),
            10,
            0,
            30,
        ),
        "A-101",
    )

    doc.saveas(
        path
    )

    project_id = (
        _register_and_scan(
            tmp_path
        )
    )

    def planner(
        _prompt,
        _context,
    ):
        return {
            "command":
                "RESIZE_COMPONENT",
            "dimension":
                "radius",
            "delta_mm":
                -7,
        }

    orchestrator = (
        ProjectOrchestrator(
            planner=
                planner
        )
    )

    job = orchestrator.plan(
        project_id,
        (
            "shrink A-101 "
            "radius by 7 mm"
        ),
        tag="A-101",
    )

    preview = (
        job[
            "items"
        ][0][
            "operation"
        ][
            "preview"
        ]
    )

    assert (
        preview[
            "before"
        ]
        == pytest.approx(
            10.0
        )
    )

    assert (
        preview[
            "after"
        ]
        == pytest.approx(
            3.0
        )
    )


def test_unsupported_scale_rejected_before_job_row(
    tmp_path,
):
    path = (
        tmp_path
        / "text.dxf"
    )

    doc = _new_doc(
        path
    )

    text = (
        doc.modelspace()
        .add_text(
            "HEADER",
            dxfattribs={
                "insert":
                    (
                        0,
                        0,
                        0,
                    )
            },
        )
    )

    _tag(
        text,
        "T-101",
    )

    doc.saveas(
        path
    )

    project_id = (
        _register_and_scan(
            tmp_path
        )
    )

    def planner(
        _prompt,
        _context,
    ):
        return {
            "command":
                "SCALE_ENTITY",
            "factor":
                2.0,
            "basepoint":
                "center",
        }

    orchestrator = (
        ProjectOrchestrator(
            planner=
                planner
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "Scaling is not supported "
            "for TEXT"
        ),
    ):
        orchestrator.plan(
            project_id,
            "scale T-101",
            tag="T-101",
        )

    with connection() as conn:
        count = conn.execute(
            """
            SELECT count(*)
            FROM jobs_multi_file
            """
        ).fetchone()[0]

    assert count == 0


def test_clarify_is_first_class_and_creates_no_job(
    tmp_path,
    monkeypatch,
):
    path = (
        tmp_path
        / "clarify.dxf"
    )

    doc = _new_doc(
        path
    )

    _tag(
        doc.modelspace()
        .add_line(
            (
                0,
                0,
            ),
            (
                100,
                0,
            ),
        ),
        "P-101",
    )

    doc.saveas(
        path
    )

    project_id = (
        _register_and_scan(
            tmp_path
        )
    )

    def planner(
        _prompt,
        _context,
    ):
        return {
            "command":
                "CLARIFY",
            "message":
                (
                    "Do you mean a layer "
                    "color or a specific "
                    "title-block entity?"
                ),
        }

    orchestrator = (
        ProjectOrchestrator(
            planner=
                planner
        )
    )

    result = orchestrator.plan(
        project_id,
        (
            "change P-101 "
            "header color"
        ),
        tag="P-101",
    )

    assert (
        result[
            "status"
        ]
        == "clarify"
    )

    assert (
        "layer color"
        in result[
            "message"
        ]
    )

    with connection() as conn:
        count = conn.execute(
            """
            SELECT count(*)
            FROM jobs_multi_file
            """
        ).fetchone()[0]

    assert count == 0

    monkeypatch.setattr(
        project_routes,
        "orchestrator",
        lambda:
            orchestrator,
    )

    app = FastAPI()

    app.include_router(
        project_routes.router
    )

    response = (
        TestClient(
            app
        )
        .post(
            (
                "/api/projects/"
                f"{project_id}/plan"
            ),
            json={
                "prompt":
                    (
                        "change P-101 "
                        "header color"
                    ),
                "tag":
                    "P-101",
            },
        )
    )

    assert (
        response.status_code
        == 200
    )

    assert (
        response.json()[
            "status"
        ]
        == "clarify"
    )

    javascript = Path(
        "src/api/static/"
        "project-chat.js"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        'job.status === "clarify"'
        in javascript
    )

    assert (
        (
            'createMessage('
            '"assistant", '
            'job.message)'
        )
        in javascript
    )


def _add_dwgprops(
    doc,
    *,
    title="",
    author="",
    custom=None,
):
    record = (
        doc.rootdict
        .add_xrecord(
            "DWGPROPS"
        )
    )

    tags = []

    if title:
        tags.append(
            DXFTag(
                2,
                title,
            )
        )

    if author:
        tags.append(
            DXFTag(
                4,
                author,
            )
        )

    for (
        key,
        value,
    ) in (
        custom or {}
    ).items():
        tags.append(
            DXFTag(
                300,
                (
                    f"{key}="
                    f"{value}"
                ),
            )
        )

    record.tags.extend(
        tags
    )


def test_layers_and_summary_are_extracted_persisted_and_queryable(
    tmp_path,
):
    path = (
        tmp_path
        / "metadata.dxf"
    )

    doc = _new_doc(
        path
    )

    layer = (
        doc.layers.add(
            "PIPES",
            color=3,
        )
    )

    layer.rgb = (
        10,
        20,
        30,
    )

    _add_dwgprops(
        doc,
        title="Plant A",
        author="Engineer",
        custom={
            "AREA":
                "North"
        },
    )

    (
        doc.modelspace()
        .add_line(
            (
                0,
                0,
            ),
            (
                10,
                0,
            ),
            dxfattribs={
                "layer":
                    "PIPES"
            },
        )
    )

    doc.saveas(
        path
    )

    project_id = (
        _register_and_scan(
            tmp_path
        )
    )

    drawing_id = (
        list_drawings(
            project_id
        )[0][
            "drawing_id"
        ]
    )

    layers = get_drawing_layers(
        project_id,
        drawing_id,
    )

    summary = get_drawing_summary(
        project_id,
        drawing_id,
    )

    pipes = next(
        row
        for row
        in layers
        if (
            row[
                "name"
            ]
            == "PIPES"
        )
    )

    assert (
        pipes[
            "color"
        ]
        == 3
    )

    assert (
        pipes[
            "true_color"
        ]
        == [
            10,
            20,
            30,
        ]
    )

    assert (
        summary[
            "title"
        ]
        == "Plant A"
    )

    assert (
        summary[
            "author"
        ]
        == "Engineer"
    )

    assert (
        summary[
            "custom"
        ][
            "AREA"
        ]
        == "North"
    )

    app = FastAPI()

    app.include_router(
        project_routes.router
    )

    response = (
        TestClient(
            app
        )
        .get(
            (
                "/api/projects/"
                f"{project_id}/"
                "drawings/"
                f"{drawing_id}/"
                "metadata"
            )
        )
    )

    assert (
        response.status_code
        == 200
    )

    assert (
        response.json()[
            "summary"
        ][
            "title"
        ]
        == "Plant A"
    )


def test_layer_color_saved_file_verification_and_lying_save(
    tmp_path,
    monkeypatch,
):
    path = (
        tmp_path
        / "layer.dxf"
    )

    doc = _new_doc(
        path
    )

    doc.layers.add(
        "PIPES",
        color=7,
    )

    (
        doc.modelspace()
        .add_line(
            (
                0,
                0,
            ),
            (
                10,
                0,
            ),
            dxfattribs={
                "layer":
                    "PIPES"
            },
        )
    )

    doc.saveas(
        path
    )

    _register_and_scan(
        tmp_path
    )

    operation = {
        "command":
            "SET_LAYER_COLOR",
        "target_dwg_path":
            str(path),
        "layer":
            "PIPES",
        "color":
            3,
    }

    result = (
        engine.execute_operation(
            operation,
            acad=
                Acad(
                    [
                        Document(
                            path
                        )
                    ]
                ),
            verify_extractor=
                DXFExtractor(),
        )
    )

    assert (
        result[
            "verified_by_extraction"
        ]
        is True
    )

    assert (
        DXFExtractor()
        .extract(
            path
        )
        .document
        .properties[
            "_layers"
        ][
            "PIPES"
        ][
            "color"
        ]
        == 3
    )

    data = ezdxf.readfile(
        path
    )

    data.layers.get(
        "PIPES"
    ).dxf.color = 7

    data.saveas(
        path
    )

    with connection() as conn:
        project_id = (
            conn.execute(
                """
                SELECT project_id
                FROM drawings
                WHERE path=?
                """,
                (
                    str(
                        path.resolve()
                    ),
                ),
            )
            .fetchone()[0]
        )

    scan_project(
        project_id,
        max_workers=1,
    )

    fake_doc = Document(
        path
    )

    monkeypatch.setattr(
        fake_doc,
        "Save",
        lambda:
            None,
    )

    with pytest.raises(
        ValueError,
        match=(
            "did not confirm "
            "the layer color"
        ),
    ):
        engine.execute_operation(
            operation,
            acad=
                Acad(
                    [
                        fake_doc
                    ]
                ),
            verify_extractor=
                DXFExtractor(),
        )


def test_document_property_saved_file_verification_and_lying_save(
    tmp_path,
    monkeypatch,
):
    path = (
        tmp_path
        / "summary.dxf"
    )

    doc = _new_doc(
        path
    )

    _add_dwgprops(
        doc,
        title="Before",
    )

    (
        doc.modelspace()
        .add_line(
            (
                0,
                0,
            ),
            (
                10,
                0,
            ),
        )
    )

    doc.saveas(
        path
    )

    project_id = (
        _register_and_scan(
            tmp_path
        )
    )

    operation = {
        "command":
            "SET_DOCUMENT_PROPERTY",
        "target_dwg_path":
            str(path),
        "property":
            "title",
        "value":
            "After",
    }

    result = (
        engine.execute_operation(
            operation,
            acad=
                Acad(
                    [
                        Document(
                            path
                        )
                    ]
                ),
            verify_extractor=
                DXFExtractor(),
        )
    )

    assert (
        result[
            "verified_by_extraction"
        ]
        is True
    )

    assert (
        DXFExtractor()
        .extract(
            path
        )
        .document
        .properties[
            "_summary_info"
        ][
            "title"
        ]
        == "After"
    )

    data = ezdxf.readfile(
        path
    )

    record = (
        data.rootdict
        .get(
            "DWGPROPS"
        )
    )

    record.tags.clear()

    record.tags.append(
        DXFTag(
            2,
            "Before",
        )
    )

    data.saveas(
        path
    )

    scan_project(
        project_id,
        max_workers=1,
    )

    fake_doc = Document(
        path
    )

    monkeypatch.setattr(
        fake_doc,
        "Save",
        lambda:
            None,
    )

    with pytest.raises(
        ValueError,
        match=(
            "did not confirm "
            "the document property"
        ),
    ):
        engine.execute_operation(
            operation,
            acad=
                Acad(
                    [
                        fake_doc
                    ]
                ),
            verify_extractor=
                DXFExtractor(),
        )

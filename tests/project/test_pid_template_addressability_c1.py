from __future__ import annotations

from copy import deepcopy

import ezdxf

from src.ai import (
    pid_component_planner,
)
from src.ai.project_planner import (
    plan_operation,
)
from src.cad.scanner import (
    scan_project,
)
from src.framework.commands import (
    executor,
)
from src.framework.commands.operation_schema import (
    validate_operation,
)
from src.framework.pid.component_builder import (
    build_component_from_data,
    render_pid_component_scene_data,
)
from src.framework.pid.component_examples import (
    available_component_examples,
)
from src.framework.pid.component_templates import (
    available_pid_component_templates,
)
from src.framework.pid.components.base import (
    render_component,
)
from src.framework.pid.scene_renderer import (
    example_horizontal_separator_pid_scene,
    render_pid_scene_to_commands,
)
from src.storage.entity_repository import (
    find_by_tag,
)
from src.storage.project_repository import (
    register_project,
)
from tests.project.fake_cad import (
    Acad,
)


_ADDRESSABLE_COMPONENT_TYPES = {
    "horizontal_vessel",
    "vertical_vessel",
    "pipe_run",
    "gate_valve",
    "control_valve",
    "instrument_bubble",
}


_ADDRESSABLE_COMPONENT_CLASS_NAMES = {
    "HorizontalVesselComponent",
    "VerticalVesselComponent",
    "PipeRunComponent",
    "GateValveComponent",
    "ControlValveComponent",
    "InstrumentBubbleComponent",
}


def _identity_commands(
    commands: list[dict],
    tag: str,
) -> list[dict]:
    return [
        command
        for command in commands
        if command.get("tag") == tag
    ]


def test_every_shipped_component_template_has_one_identity_entity_per_addressable_component() -> None:
    templates = (
        available_pid_component_templates()
    )

    for (
        template_name,
        builder,
    ) in templates.items():
        scene = builder()

        seen_tags: set[str] = set()

        for data in scene[
            "components"
        ]:
            if (
                data["component_type"]
                not in
                _ADDRESSABLE_COMPONENT_TYPES
            ):
                continue

            tag = data.get(
                "tag"
            )

            assert tag, (
                f"{template_name}:"
                f"{data['id']} "
                "has no engineering tag"
            )

            assert (
                tag.casefold()
                not in seen_tags
            ), (
                "duplicate tag "
                f"{tag} in "
                f"{template_name}"
            )

            seen_tags.add(
                tag.casefold()
            )

            rendered = (
                render_component(
                    build_component_from_data(
                        data
                    )
                )
            )

            identity = (
                _identity_commands(
                    rendered.commands,
                    tag,
                )
            )

            assert len(identity) == 1, (
                f"{template_name}:"
                f"{data['id']} must "
                "render exactly one "
                "identity-bearing entity "
                f"tagged {tag}; "
                f"got {identity}"
            )


def test_every_shipped_component_example_has_one_identity_entity_per_addressable_component() -> None:
    examples = (
        available_component_examples()
    )

    for (
        example_name,
        builder,
    ) in examples.items():
        scene = builder()

        seen_tags: set[str] = set()

        for component in (
            scene.components
        ):
            if (
                component
                .__class__
                .__name__
                not in
                _ADDRESSABLE_COMPONENT_CLASS_NAMES
            ):
                continue

            assert component.tag, (
                f"{example_name}:"
                f"{component.id} "
                "has no engineering tag"
            )

            assert (
                component.tag.casefold()
                not in seen_tags
            )

            seen_tags.add(
                component.tag.casefold()
            )

            rendered = (
                render_component(
                    component
                )
            )

            identity = (
                _identity_commands(
                    rendered.commands,
                    component.tag,
                )
            )

            assert len(identity) == 1


def test_ai_planner_fills_missing_pipe_and_valve_tags(
    monkeypatch,
) -> None:
    response = {
        "schema_version":
            "1.0",
        "title":
            "Auto tag test",
        "drawing_type":
            "P&ID",
        "assumptions":
            [],
        "components": [
            {
                "component_type":
                    "horizontal_vessel",
                "id":
                    "V201",
                "tag":
                    "V-201",
                "center":
                    [0, 0],
                "length":
                    2800,
                "diameter":
                    760,
            },
            {
                "component_type":
                    "pipe_run",
                "id":
                    "P_IN",
                "points": [
                    [-2000, 0],
                    [-1400, 0],
                ],
            },
            {
                "component_type":
                    "pipe_run",
                "id":
                    "P_OUT",
                "points": [
                    [1400, 0],
                    [2000, 0],
                ],
            },
            {
                "component_type":
                    "gate_valve",
                "id":
                    "XV_IN",
                "center":
                    [-1700, 0],
                "orientation":
                    "H",
            },
            {
                "component_type":
                    "control_valve",
                "id":
                    "FV_OUT",
                "center":
                    [1700, 0],
                "orientation":
                    "H",
            },
        ],
    }

    monkeypatch.setattr(
        pid_component_planner,
        "ask_ai",
        lambda **_kwargs:
            deepcopy(response),
    )

    result = (
        pid_component_planner
        .plan_pid_component_scene(
            "Draw a separator P&ID"
        )
    )

    by_id = {
        component["id"]:
            component
        for component
        in result["components"]
    }

    assert (
        by_id["P_IN"]["tag"]
        == "P-101"
    )

    assert (
        by_id["P_OUT"]["tag"]
        == "P-102"
    )

    assert (
        by_id["XV_IN"]["tag"]
        == "XV-101"
    )

    assert (
        by_id["FV_OUT"]["tag"]
        == "FV-101"
    )


def test_legacy_scene_renderer_tags_pipe_and_valve_identity_entities() -> None:
    scene = (
        example_horizontal_separator_pid_scene()
    )

    sequence = (
        render_pid_scene_to_commands(
            scene
        )
    )

    tags = {
        command.get("tag")
        for command
        in sequence["commands"]
        if command.get("tag")
    }

    assert "P-INLET" in tags
    assert "XV-IN" in tags
    assert "LV-OIL" in tags


def test_template_generate_execute_scan_find_and_resize_plan_validates(
    tmp_path,
    monkeypatch,
) -> None:
    drawing = (
        tmp_path
        / "generated_pid.dxf"
    )

    doc = ezdxf.new(
        "R2010"
    )

    doc.units = 4

    doc.saveas(
        drawing
    )

    template = (
        available_pid_component_templates()[
            "horizontal_separator"
        ]()
    )

    sequence = (
        render_pid_component_scene_data(
            template
        )
    )

    acad = Acad([])

    monkeypatch.setattr(
        executor,
        "_get_acad",
        lambda: acad,
    )

    def immediate_retry(
        operation,
        description,
        attempts=5,
        delay_seconds=0.5,
    ):
        del (
            description,
            attempts,
            delay_seconds,
        )

        return operation()

    monkeypatch.setattr(
        executor,
        "_com_retry",
        immediate_retry,
    )

    result = (
        executor.execute_commands(
            sequence["commands"],
            target_dwg_path=
                str(drawing),
            save=True,
            zoom_extents=False,
        )
    )

    assert (
        result["ok"]
        is True
    )

    assert (
        result["errors"]
        == []
    )

    project_id = (
        register_project(
            "Generated P&ID",
            str(tmp_path),
        )
    )

    scan = scan_project(
        project_id,
        max_workers=1,
    )

    assert (
        scan["errors"]
        == []
    )

    matches = find_by_tag(
        project_id,
        "P-101",
    )

    assert len(matches) == 1

    pipe = matches[0]

    assert pipe[
        "entity_type"
    ] in {
        "LWPOLYLINE",
        "POLYLINE",
    }

    context = dict(
        pipe,
        occurrence_count=1,
        connection_count=0,
    )

    draft = plan_operation(
        (
            "Increase pipe P-101 "
            "length by 50 mm"
        ),
        context,
        ask=lambda **_kwargs: {
            "command":
                "RESIZE_COMPONENT",
            "dimension":
                "length",
            "delta_mm":
                50,
        },
    )

    operation = dict(
        draft,
        target_dwg_path=
            pipe["path"],
        handle=
            pipe["handle"],
    )

    assert (
        validate_operation(
            operation
        )
        == operation
    )
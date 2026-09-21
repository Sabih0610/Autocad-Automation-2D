"""Deterministic renderer for structured P&ID scenes."""

from __future__ import annotations

from src.framework.commands.schema import validate_command_sequence
from src.framework.pid.scene_schema import validate_pid_scene
from src.framework.pid.symbols import (
    PID_INSTRUMENT_RADIUS,
    PID_PIPE_LABEL_OFFSET,
    PID_TEXT_HEIGHT_NORMAL,
    PID_TEXT_HEIGHT_SMALL,
    PID_TEXT_HEIGHT_TITLE,
    PID_VALVE_SIZE,
    control_valve_commands,
    flow_arrow_commands,
    gate_valve_commands,
    horizontal_vessel_commands,
    instrument_bubble_commands,
    pid_standard_layers,
    pipe_line_commands,
    signal_line_commands,
    text_label_commands,
    vertical_vessel_commands,
    wrap_commands_as_sequence,
)


class PIDSceneRenderError(Exception):
    """Raised when a P&ID scene cannot be rendered to valid commands."""


def _legacy_identity_tag(
    component_id: str,
) -> str:
    """Derive a stable recoverable tag for legacy scene pipes/valves."""
    clean = (
        str(component_id)
        .strip()
        .upper()
        .replace("_", "-")
    )

    if not clean:
        raise PIDSceneRenderError(
            "legacy P&ID component id "
            "cannot be empty"
        )

    return clean


def _label_position_for_pipe(
    points: list[
        list[float]
    ],
) -> list[float]:
    longest_segment = (
        points[0],
        points[-1],
    )

    longest_length = -1.0

    for start, end in zip(
        points,
        points[1:],
    ):
        dx = (
            float(end[0])
            - float(start[0])
        )

        dy = (
            float(end[1])
            - float(start[1])
        )

        length = (
            dx * dx
            + dy * dy
        )

        if length > longest_length:
            longest_segment = (
                start,
                end,
            )

            longest_length = (
                length
            )

    start, end = longest_segment

    mid_x = (
        float(start[0])
        + float(end[0])
    ) / 2.0

    mid_y = (
        float(start[1])
        + float(end[1])
    ) / 2.0

    dx = abs(
        float(end[0])
        - float(start[0])
    )

    dy = abs(
        float(end[1])
        - float(start[1])
    )

    if dx >= dy:
        return [
            mid_x
            - PID_PIPE_LABEL_OFFSET
            * 1.3,
            mid_y
            + PID_PIPE_LABEL_OFFSET,
        ]

    return [
        mid_x
        + PID_PIPE_LABEL_OFFSET
        * 0.45,
        mid_y
        - PID_PIPE_LABEL_OFFSET
        * 0.25,
    ]


def render_pid_scene_to_commands(
    scene: dict,
) -> dict:
    """Render a validated P&ID scene into a command sequence."""
    scene_errors = (
        validate_pid_scene(
            scene
        )
    )

    if scene_errors:
        joined_errors = "\n".join(
            f"- {error}"
            for error in scene_errors
        )

        raise PIDSceneRenderError(
            "Invalid P&ID scene:\n"
            f"{joined_errors}"
        )

    commands = []

    commands += (
        pid_standard_layers()
    )

    for equipment in scene[
        "equipment"
    ]:
        if (
            equipment["type"]
            == "horizontal_vessel"
        ):
            commands += (
                horizontal_vessel_commands(
                    center=
                        equipment[
                            "center"
                        ],
                    length=
                        equipment[
                            "length"
                        ],
                    diameter=
                        equipment[
                            "diameter"
                        ],
                    tag=
                        equipment[
                            "tag"
                        ],
                )
            )

        elif (
            equipment["type"]
            == "vertical_vessel"
        ):
            commands += (
                vertical_vessel_commands(
                    center=
                        equipment[
                            "center"
                        ],
                    height=
                        equipment[
                            "height"
                        ],
                    diameter=
                        equipment[
                            "diameter"
                        ],
                    tag=
                        equipment[
                            "tag"
                        ],
                )
            )

        else:
            raise PIDSceneRenderError(
                "Unsupported equipment type: "
                f"{equipment['type']}"
            )

    for pipe in scene["pipes"]:
        commands += (
            pipe_line_commands(
                pipe["points"],
                tag=
                    _legacy_identity_tag(
                        pipe["id"]
                    ),
            )
        )

        if pipe.get("label"):
            commands += (
                text_label_commands(
                    pipe["label"],
                    _label_position_for_pipe(
                        pipe["points"]
                    ),
                    height=
                        PID_TEXT_HEIGHT_NORMAL,
                )
            )

    for valve in scene[
        "valves"
    ]:
        if (
            valve["type"]
            == "gate_valve"
        ):
            commands += (
                gate_valve_commands(
                    center=
                        valve[
                            "center"
                        ],
                    size=
                        valve.get(
                            "size",
                            PID_VALVE_SIZE,
                        ),
                    orientation=
                        valve[
                            "orientation"
                        ],
                    tag=
                        _legacy_identity_tag(
                            valve["id"]
                        ),
                )
            )

        elif (
            valve["type"]
            == "control_valve"
        ):
            commands += (
                control_valve_commands(
                    center=
                        valve[
                            "center"
                        ],
                    size=
                        valve.get(
                            "size",
                            PID_VALVE_SIZE,
                        ),
                    orientation=
                        valve[
                            "orientation"
                        ],
                    tag=
                        _legacy_identity_tag(
                            valve["id"]
                        ),
                )
            )

        else:
            raise PIDSceneRenderError(
                "Unsupported valve type: "
                f"{valve['type']}"
            )

    for instrument in scene[
        "instruments"
    ]:
        commands += (
            instrument_bubble_commands(
                center=
                    instrument[
                        "center"
                    ],
                tag=
                    instrument[
                        "tag"
                    ],
                radius=
                    instrument.get(
                        "radius",
                        PID_INSTRUMENT_RADIUS,
                    ),
            )
        )

        if instrument.get(
            "signal_to"
        ):
            commands += (
                signal_line_commands(
                    instrument[
                        "signal_to"
                    ]
                )
            )

    for signal_line in scene[
        "signal_lines"
    ]:
        commands += (
            signal_line_commands(
                signal_line[
                    "points"
                ]
            )
        )

    for label in scene[
        "labels"
    ]:
        commands += (
            text_label_commands(
                label["text"],
                label[
                    "position"
                ],
                height=
                    label.get(
                        "height",
                        PID_TEXT_HEIGHT_NORMAL,
                    ),
            )
        )

    for arrow in scene[
        "flow_arrows"
    ]:
        commands += (
            flow_arrow_commands(
                position=
                    arrow[
                        "position"
                    ],
                direction=
                    arrow[
                        "direction"
                    ],
                size=
                    arrow.get(
                        "size",
                        100,
                    ),
            )
        )

    commands += (
        text_label_commands(
            scene["title"],
            [-1600, 1600],
            height=
                PID_TEXT_HEIGHT_TITLE,
        )
    )

    sequence = (
        wrap_commands_as_sequence(
            commands,
            summary=(
                "P&ID scene: "
                f"{scene['title']}"
            ),
        )
    )

    sequence[
        "assumptions"
    ].extend(
        scene.get(
            "assumptions",
            [],
        )
    )

    command_errors = (
        validate_command_sequence(
            sequence
        )
    )

    if command_errors:
        joined_errors = "\n".join(
            f"- {error}"
            for error
            in command_errors
        )

        raise PIDSceneRenderError(
            "Rendered P&ID commands "
            "failed validation:\n"
            f"{joined_errors}"
        )

    return sequence

def example_horizontal_separator_pid_scene() -> dict:
    """Return a deterministic horizontal separator P&ID-style scene."""
    return {
        "schema_version": "1.0",
        "title": "Horizontal Separator P&ID",
        "drawing_type": "P&ID",
        "assumptions": [
            "Schematic layout is not fabrication-grade.",
            "Valve and instrument symbols are deterministic placeholders.",
        ],
        "equipment": [
            {
                "id": "V101",
                "type": "horizontal_vessel",
                "tag": "V-101",
                "center": [0, 0],
                "length": 2600,
                "diameter": 700,
            }
        ],
        "pipes": [
            {
                "id": "P_INLET",
                "points": [
                    [-2900, 0],
                    [-1300, 0],
                ],
                "label": "3 Phase Inlet",
            },
            {
                "id": "P_VAPOR",
                "points": [
                    [900, 350],
                    [900, 780],
                    [2350, 780],
                ],
                "label": "Vapor Outlet",
            },
            {
                "id": "P_WATER",
                "points": [
                    [-650, -350],
                    [-650, -900],
                    [-2450, -900],
                ],
                "label": "Water Outlet",
            },
            {
                "id": "P_OIL",
                "points": [
                    [650, -350],
                    [650, -1080],
                    [2450, -1080],
                ],
                "label": "Oil Outlet",
            },
        ],
        "valves": [
            {
                "id": "XV_IN",
                "type": "gate_valve",
                "center": [-2050, 0],
                "orientation": "H",
                "size": 120,
            },
            {
                "id": "XV_VAP",
                "type": "gate_valve",
                "center": [1500, 780],
                "orientation": "H",
                "size": 115,
            },
            {
                "id": "XV_WTR",
                "type": "gate_valve",
                "center": [-1550, -900],
                "orientation": "H",
                "size": 115,
            },
            {
                "id": "XV_OIL",
                "type": "gate_valve",
                "center": [1380, -1080],
                "orientation": "H",
                "size": 115,
            },
            {
                "id": "LV_OIL",
                "type": "control_valve",
                "center": [1900, -1080],
                "orientation": "H",
                "size": 125,
            },
        ],
        "instruments": [
            {
                "id": "PT101",
                "tag": "PT-101",
                "center": [-520, 850],
                "radius": 85,
                "signal_to": [
                    [-520, 765],
                    [-520, 350],
                ],
            },
            {
                "id": "PI101",
                "tag": "PI-101",
                "center": [1500, 1050],
                "radius": 85,
                "signal_to": [
                    [1500, 965],
                    [1500, 780],
                ],
            },
            {
                "id": "LT101",
                "tag": "LT-101",
                "center": [1580, 250],
                "radius": 85,
                "signal_to": [
                    [1495, 250],
                    [1320, 250],
                    [1300, 120],
                ],
            },
            {
                "id": "LC101",
                "tag": "LC-101",
                "center": [2050, 250],
                "radius": 85,
                "signal_to": [
                    [2050, 165],
                    [2050, -900],
                    [1900, -900],
                    [1900, -980],
                ],
            },
        ],
        "labels": [
            {
                "text": "Level Control",
                "position": [1780, 485],
                "height": PID_TEXT_HEIGHT_SMALL,
            },
        ],
        "flow_arrows": [
            {
                "position": [-2600, 0],
                "direction": "RIGHT",
                "size": 85,
            },
            {
                "position": [2180, 780],
                "direction": "RIGHT",
                "size": 85,
            },
            {
                "position": [-2240, -900],
                "direction": "LEFT",
                "size": 85,
            },
            {
                "position": [2260, -1080],
                "direction": "RIGHT",
                "size": 85,
            },
        ],
        "signal_lines": [
            {
                "points": [
                    [1665, 250],
                    [1965, 250],
                ],
            }
        ],
    }


def render_example_horizontal_separator_pid() -> dict:
    scene = example_horizontal_separator_pid_scene()

    return render_pid_scene_to_commands(
        scene
    )
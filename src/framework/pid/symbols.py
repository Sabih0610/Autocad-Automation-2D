"""Deterministic P&ID command templates.

All functions return command dictionaries compatible with the Mode 2 command
schema. Coordinates are in millimeters.
"""

from __future__ import annotations

from src.framework.commands.schema import COMMAND_SCHEMA_VERSION


PID_LAYER_EQUIPMENT = "PID_EQUIPMENT"
PID_LAYER_PIPING = "PID_PIPING"
PID_LAYER_VALVES = "PID_VALVES"
PID_LAYER_INSTRUMENTS = "PID_INSTRUMENTS"
PID_LAYER_TEXT = "PID_TEXT"
PID_LAYER_SIGNAL = "PID_SIGNAL"
PID_LAYER_FLOW = "PID_FLOW"

# AutoCAD ACI colors for presentation/demo output.
# 1 red, 2 yellow, 3 green, 4 cyan, 5 blue, 6 magenta,
# 7 white/black foreground, 8 gray, 9 light gray, 30 orange-ish.
PID_COLOR_EQUIPMENT = 4      # cyan / blue-style equipment
PID_COLOR_PIPING = 3         # green piping
PID_COLOR_VALVES = 6         # magenta valves
PID_COLOR_INSTRUMENTS = 2    # yellow instruments
PID_COLOR_TEXT = 7           # white / foreground text
PID_COLOR_SIGNAL = 8         # gray signal/controller lines
PID_COLOR_FLOW = 30          # orange-ish flow arrows

# Presentation-friendly text sizing.
PID_TEXT_HEIGHT_NORMAL = 85
PID_TEXT_HEIGHT_SMALL = 55
PID_TEXT_HEIGHT_TITLE = 150
PID_INSTRUMENT_RADIUS = 85
PID_VALVE_SIZE = 120
PID_PIPE_LABEL_OFFSET = 140

# Keep equipment tags readable without dominating the drawing.
PID_EQUIPMENT_TAG_HEIGHT = 70


def _xy(point: list[float]) -> tuple[float, float]:
    if not isinstance(point, list) or len(point) < 2:
        raise ValueError("point must contain at least two coordinates")
    return float(point[0]), float(point[1])


def _validate_positive(value: float, name: str) -> None:
    if float(value) <= 0:
        raise ValueError(f"{name} must be positive")


def _validate_orientation(orientation: str) -> str:
    normalized = orientation.upper()
    if normalized not in {"H", "V"}:
        raise ValueError("orientation must be 'H' or 'V'")
    return normalized


def _validate_direction(direction: str) -> str:
    normalized = direction.upper()
    if normalized not in {"RIGHT", "LEFT", "UP", "DOWN"}:
        raise ValueError("direction must be RIGHT, LEFT, UP, or DOWN")
    return normalized


def _estimated_text_width(text: str, height: float) -> float:
    return len(text) * height * 0.55


def _equipment_tag_height(size: float) -> float:
    """Return a controlled tag height for equipment tags.

    The previous sizing could make tags very large on big equipment. This keeps
    the output more suitable for demo videos and client presentation screenshots.
    """
    minimum = PID_EQUIPMENT_TAG_HEIGHT * 0.65
    maximum = PID_EQUIPMENT_TAG_HEIGHT + 10.0
    return min(max(float(size) * 0.12, minimum), maximum)


def pid_standard_layers() -> list[dict]:
    """Return standard colored P&ID layers.

    The Mode 2 command executor supports the ``color`` key on LAYER commands,
    so new P&ID drawings will use presentation colors automatically.
    """
    return [
        {
            "command": "LAYER",
            "layer_name": PID_LAYER_EQUIPMENT,
            "color": PID_COLOR_EQUIPMENT,
        },
        {
            "command": "LAYER",
            "layer_name": PID_LAYER_PIPING,
            "color": PID_COLOR_PIPING,
        },
        {
            "command": "LAYER",
            "layer_name": PID_LAYER_VALVES,
            "color": PID_COLOR_VALVES,
        },
        {
            "command": "LAYER",
            "layer_name": PID_LAYER_INSTRUMENTS,
            "color": PID_COLOR_INSTRUMENTS,
        },
        {
            "command": "LAYER",
            "layer_name": PID_LAYER_TEXT,
            "color": PID_COLOR_TEXT,
        },
        {
            "command": "LAYER",
            "layer_name": PID_LAYER_SIGNAL,
            "color": PID_COLOR_SIGNAL,
        },
        {
            "command": "LAYER",
            "layer_name": PID_LAYER_FLOW,
            "color": PID_COLOR_FLOW,
        },
    ]


def pipe_line_commands(
    points: list[list[float]],
    layer: str = PID_LAYER_PIPING,
    tag: str | None = None,
) -> list[dict]:
    if not isinstance(points, list) or len(points) < 2:
        raise ValueError("points must contain at least two coordinate pairs")

    command = {
        "command": "POLYLINE",
        "points": [[float(x), float(y)] for x, y in (_xy(point) for point in points)],
        "closed": False,
        "layer": layer,
    }
    # Attach the pipe's engineering tag (e.g. "P-101") as recoverable identity on
    # the polyline itself (see executor.py's `_apply_entity_tag`). Without this,
    # a generated pipe is geometry with no tag anywhere the project index can
    # read back, so it can never be found again for a resize/edit request.
    if tag:
        command["tag"] = tag

    return [command]


def horizontal_vessel_commands(
    center: list[float],
    length: float,
    diameter: float,
    tag: str = "V-101",
    layer: str = PID_LAYER_EQUIPMENT,
) -> list[dict]:
    _validate_positive(length, "length")
    _validate_positive(diameter, "diameter")
    if not tag:
        raise ValueError("tag cannot be empty")

    cx, cy = _xy(center)
    radius = float(diameter) / 2.0
    left_x = cx - float(length) / 2.0
    right_x = cx + float(length) / 2.0
    top_y = cy + radius
    bottom_y = cy - radius

    tag_height = _equipment_tag_height(diameter)
    tag_width = _estimated_text_width(tag, tag_height)
    tag_x = cx - tag_width / 2.0
    tag_y = cy + float(diameter) * 0.12

    # If the tag would be too large inside the vessel, place it above.
    if tag_width > float(length) * 0.65 or tag_height > float(diameter) * 0.35:
        tag_y = top_y + tag_height * 0.75

    return [
        {
            # The top shell LINE is this vessel's identity-bearing entity (see
            # executor.py's `_apply_entity_tag`) — it's also what RESIZE_COMPONENT
            # "length" edits target, so tagging it doubles as making the vessel
            # both findable and resizable by tag.
            "command": "LINE",
            "from": [left_x, top_y],
            "to": [right_x, top_y],
            "layer": layer,
            "tag": tag,
        },
        {
            "command": "LINE",
            "from": [left_x, bottom_y],
            "to": [right_x, bottom_y],
            "layer": layer,
        },
        {
            "command": "ARC",
            "center": [left_x, cy],
            "radius": radius,
            "start_angle_degrees": 90,
            "end_angle_degrees": 270,
            "layer": layer,
        },
        {
            "command": "ARC",
            "center": [right_x, cy],
            "radius": radius,
            "start_angle_degrees": 270,
            "end_angle_degrees": 90,
            "layer": layer,
        },
        {
            "command": "TEXT",
            "text": tag,
            "position": [tag_x, tag_y],
            "height": tag_height,
            "layer": PID_LAYER_TEXT,
        },
    ]


def vertical_vessel_commands(
    center: list[float],
    height: float,
    diameter: float,
    tag: str = "V-101",
    layer: str = PID_LAYER_EQUIPMENT,
) -> list[dict]:
    _validate_positive(height, "height")
    _validate_positive(diameter, "diameter")
    if not tag:
        raise ValueError("tag cannot be empty")

    cx, cy = _xy(center)
    radius = float(diameter) / 2.0
    left_x = cx - radius
    right_x = cx + radius
    top_y = cy + float(height) / 2.0
    bottom_y = cy - float(height) / 2.0

    tag_height = _equipment_tag_height(diameter)
    tag_width = _estimated_text_width(tag, tag_height)
    tag_x = cx - tag_width / 2.0
    tag_y = cy + float(diameter) * 0.12

    # If the tag would be too wide inside the vessel, place it above.
    if tag_width > float(diameter) * 0.9:
        tag_y = top_y + tag_height * 0.75

    return [
        {
            # See the matching comment in horizontal_vessel_commands: this LINE
            # is the vessel's identity-bearing entity and its RESIZE_COMPONENT
            # "length" target.
            "command": "LINE",
            "from": [left_x, bottom_y],
            "to": [left_x, top_y],
            "layer": layer,
            "tag": tag,
        },
        {
            "command": "LINE",
            "from": [right_x, bottom_y],
            "to": [right_x, top_y],
            "layer": layer,
        },
        {
            "command": "ARC",
            "center": [cx, top_y],
            "radius": radius,
            "start_angle_degrees": 0,
            "end_angle_degrees": 180,
            "layer": layer,
        },
        {
            "command": "ARC",
            "center": [cx, bottom_y],
            "radius": radius,
            "start_angle_degrees": 180,
            "end_angle_degrees": 360,
            "layer": layer,
        },
        {
            "command": "TEXT",
            "text": tag,
            "position": [tag_x, tag_y],
            "height": tag_height,
            "layer": PID_LAYER_TEXT,
        },
    ]


def gate_valve_commands(
    center: list[float],
    size: float = PID_VALVE_SIZE,
    orientation: str = "H",
    layer: str = PID_LAYER_VALVES,
    tag: str | None = None,
) -> list[dict]:
    _validate_positive(size, "size")
    orientation = _validate_orientation(orientation)
    cx, cy = _xy(center)
    half = float(size) / 2.0
    body_half = half * 0.82
    body_width = half * 0.52
    connector = half * 0.32
    stem = half * 0.55
    handle = half * 0.42

    if orientation == "H":
        first_wedge = {
            "command": "POLYLINE",
            "points": [
                [cx - body_half, cy - body_width],
                [cx, cy],
                [cx - body_half, cy + body_width],
            ],
            "closed": True,
            "layer": layer,
        }
        # The first body wedge is this valve's identity-bearing entity — see
        # executor.py's `_apply_entity_tag`.
        if tag:
            first_wedge["tag"] = tag

        return [
            first_wedge,
            {
                "command": "POLYLINE",
                "points": [
                    [cx + body_half, cy - body_width],
                    [cx, cy],
                    [cx + body_half, cy + body_width],
                ],
                "closed": True,
                "layer": layer,
            },
            {
                "command": "LINE",
                "from": [cx - half - connector, cy],
                "to": [cx - body_half, cy],
                "layer": layer,
            },
            {
                "command": "LINE",
                "from": [cx + body_half, cy],
                "to": [cx + half + connector, cy],
                "layer": layer,
            },
            {
                "command": "LINE",
                "from": [cx, cy + body_width],
                "to": [cx, cy + body_width + stem],
                "layer": layer,
            },
            {
                "command": "LINE",
                "from": [cx - handle, cy + body_width + stem],
                "to": [cx + handle, cy + body_width + stem],
                "layer": layer,
            },
        ]

    first_wedge = {
        "command": "POLYLINE",
        "points": [
            [cx - body_width, cy - body_half],
            [cx, cy],
            [cx + body_width, cy - body_half],
        ],
        "closed": True,
        "layer": layer,
    }
    if tag:
        first_wedge["tag"] = tag

    return [
        first_wedge,
        {
            "command": "POLYLINE",
            "points": [
                [cx - body_width, cy + body_half],
                [cx, cy],
                [cx + body_width, cy + body_half],
            ],
            "closed": True,
            "layer": layer,
        },
        {
            "command": "LINE",
            "from": [cx, cy - half - connector],
            "to": [cx, cy - body_half],
            "layer": layer,
        },
        {
            "command": "LINE",
            "from": [cx, cy + body_half],
            "to": [cx, cy + half + connector],
            "layer": layer,
        },
        {
            "command": "LINE",
            "from": [cx + body_width, cy],
            "to": [cx + body_width + stem, cy],
            "layer": layer,
        },
        {
            "command": "LINE",
            "from": [cx + body_width + stem, cy - handle],
            "to": [cx + body_width + stem, cy + handle],
            "layer": layer,
        },
    ]


def control_valve_commands(
    center: list[float],
    size: float = 140,
    orientation: str = "H",
    layer: str = PID_LAYER_VALVES,
    tag: str | None = None,
) -> list[dict]:
    _validate_positive(size, "size")
    orientation = _validate_orientation(orientation)
    cx, cy = _xy(center)
    actuator_radius = float(size) * 0.22
    offset = float(size) * 0.88
    commands = gate_valve_commands(center, size=size, orientation=orientation, layer=layer, tag=tag)

    if orientation == "H":
        actuator_center = [cx, cy + offset]
        stem_to = [cx, cy + float(size) * 0.48]
    else:
        actuator_center = [cx + offset, cy]
        stem_to = [cx + float(size) * 0.48, cy]

    commands += [
        {
            "command": "CIRCLE",
            "center": actuator_center,
            "radius": actuator_radius,
            "layer": layer,
        },
        {
            "command": "LINE",
            "from": actuator_center,
            "to": stem_to,
            "layer": layer,
        },
    ]
    return commands


def instrument_bubble_commands(
    center: list[float],
    tag: str,
    radius: float = PID_INSTRUMENT_RADIUS,
    layer: str = PID_LAYER_INSTRUMENTS,
) -> list[dict]:
    _validate_positive(radius, "radius")
    if not tag:
        raise ValueError("tag cannot be empty")

    cx, cy = _xy(center)
    text_height = min(max(float(radius) * 0.24, 32.0), 52.0)
    text_width = _estimated_text_width(tag, text_height)
    return [
        {
            # The bubble CIRCLE is this instrument's identity-bearing entity —
            # see executor.py's `_apply_entity_tag`. `tag` is required (validated
            # above), so it's always attached here, unlike the optional-tag
            # symbol functions elsewhere in this module.
            "command": "CIRCLE",
            "center": [cx, cy],
            "radius": float(radius),
            "layer": layer,
            "tag": tag,
        },
        {
            "command": "LINE",
            "from": [cx - radius, cy],
            "to": [cx + radius, cy],
            "layer": layer,
        },
        {
            "command": "TEXT",
            "text": tag,
            "position": [cx - text_width / 2.0, cy + float(radius) * 0.12],
            "height": text_height,
            "layer": PID_LAYER_TEXT,
        },
    ]


def signal_line_commands(
    points: list[list[float]],
    layer: str = PID_LAYER_SIGNAL,
) -> list[dict]:
    """Return signal line commands.

    Dashed linetype handling can be added later when linetype availability is
    managed centrally.
    """
    return pipe_line_commands(points, layer=layer)


def flow_arrow_commands(
    position: list[float],
    direction: str = "RIGHT",
    size: float = 100,
    layer: str = PID_LAYER_FLOW,
) -> list[dict]:
    _validate_positive(size, "size")
    direction = _validate_direction(direction)
    x, y = _xy(position)
    half = float(size) * 0.45
    width = float(size) * 0.26

    if direction == "RIGHT":
        points = [[x + half, y], [x - half, y - width], [x - half, y + width]]
    elif direction == "LEFT":
        points = [[x - half, y], [x + half, y - width], [x + half, y + width]]
    elif direction == "UP":
        points = [[x, y + half], [x - width, y - half], [x + width, y - half]]
    else:
        points = [[x, y - half], [x - width, y + width], [x + width, y + width]]

    return [
        {
            "command": "POLYLINE",
            "points": points,
            "closed": True,
            "layer": layer,
        }
    ]


def text_label_commands(
    text: str,
    position: list[float],
    height: float = PID_TEXT_HEIGHT_NORMAL,
    layer: str = PID_LAYER_TEXT,
) -> list[dict]:
    if not text:
        raise ValueError("text cannot be empty")
    _validate_positive(height, "height")
    x, y = _xy(position)
    return [
        {
            "command": "TEXT",
            "text": text,
            "position": [x, y],
            "height": float(height),
            "layer": layer,
        }
    ]


def wrap_commands_as_sequence(
    commands: list[dict],
    summary: str = "P&ID symbol test",
) -> dict:
    return {
        "schema_version": COMMAND_SCHEMA_VERSION,
        "summary": summary,
        "estimated_drawing_type": "P&ID schematic",
        "assumptions": ["Generated from deterministic P&ID symbol templates."],
        "commands": commands,
    }
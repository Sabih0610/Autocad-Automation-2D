from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from src.api.chat_routing import (
    CHAT_ROUTE_CAD3D,
    CHAT_ROUTE_CAD3D_EDIT,
    CHAT_ROUTE_EDIT,
    CHAT_ROUTE_PID,
    CHAT_ROUTE_SKETCH,
    decide_chat_route,
    has_explicit_2d_intent,
    has_explicit_3d_intent,
    has_negated_3d_intent,
    has_cad3d_edit_intent,
    is_3d_request,
    is_edit_request,
    is_new_drawing_request,
    is_pid_request,
)


@pytest.mark.parametrize(
    "prompt",
    [
        "Create a detailed P&ID for a small process unit.",
        "Draw a clean P&ID with one horizontal separator vessel, vapor outlet, oil outlet, and water outlet.",
        "Generate a piping and instrumentation diagram with pumps, tanks, and instruments.",
        (
            "Create a detailed P&ID for a small process unit. Include one horizontal separator vessel "
            "tagged V-201, one vertical vessel tagged V-301, one storage tank tagged T-101, two pumps "
            "tagged P-101 and P-102, one heat exchanger tagged E-101."
        ),
    ],
)
def test_pid_creation_prompts_route_to_pid_generate(prompt: str) -> None:
    assert is_new_drawing_request(prompt) is True
    assert is_pid_request(prompt) is True
    assert is_edit_request(prompt) is False
    assert decide_chat_route(prompt) == CHAT_ROUTE_PID


@pytest.mark.parametrize(
    "prompt",
    [
        "Create a 3D equipment layout with tank pump and vessel.",
        "Generate a 3D CAD model of a skid with pipes.",
        "Build a 3D model with one vertical tank and horizontal vessel.",
        (
            "Create a 3D equipment layout with one vertical storage tank T-101 on the left, "
            "one pump P-101 in the middle, one horizontal separator V-201 on the right, "
            "a skid base underneath, and connecting pipes between tank, pump, and separator."
        ),
    ],
)
def test_3d_creation_prompts_route_to_cad3d_generate(prompt: str) -> None:
    assert is_new_drawing_request(prompt) is True
    assert is_3d_request(prompt) is True
    assert is_edit_request(prompt) is False
    assert decide_chat_route(prompt) == CHAT_ROUTE_CAD3D


def test_explicit_3d_helpers_detect_positive_intent() -> None:
    assert has_explicit_3d_intent("Create a 3D model") is True
    assert has_explicit_3d_intent("Create a solid model") is True


def test_negated_3d_helper_detects_negative_intent() -> None:
    assert has_negated_3d_intent("not a 3D model") is True


def test_explicit_2d_helper_detects_2d_intent() -> None:
    assert has_explicit_2d_intent("Create a 2D drawing") is True
    assert has_explicit_2d_intent("Create a flat diagram") is True


@pytest.mark.parametrize(
    "prompt, expected",
    [
        ("Create a 2D diagram, not a 3D model", False),
        ("Create equipment layout with tank pump vessel", False),
        ("Create a 3D equipment layout with tank pump vessel", True),
    ],
)
def test_3d_request_requires_unnegated_explicit_3d_intent(prompt: str, expected: bool) -> None:
    assert is_3d_request(prompt) is expected


@pytest.mark.parametrize(
    "prompt",
    [
        "Create a clean professional colored 2D process layout titled Pump Transfer Layout with tank, pump, vessel, and pipes.",
        "Create an equipment layout with tank, pump, vessel, and connecting pipes.",
        "Create a heat exchanger skid with pump, valves, flanges, supports, and labels.",
        "Create a 2D process diagram with tank, pump, separator, pipes, and labels, no 3D.",
    ],
)
def test_2d_and_equipment_process_prompts_do_not_route_to_cad3d(prompt: str) -> None:
    assert is_3d_request(prompt) is False
    assert decide_chat_route(prompt) != CHAT_ROUTE_CAD3D


def test_2d_flat_pid_not_3d_prompt_routes_to_pid() -> None:
    prompt = "Create a 2D flat AutoCAD P&ID diagram, not a 3D model."

    assert has_negated_3d_intent(prompt) is True
    assert is_3d_request(prompt) is False
    assert decide_chat_route(prompt) == CHAT_ROUTE_PID


@pytest.mark.parametrize(
    "prompt",
    [
        "Create a clean professional 3D equipment layout with tank, pump, vessel, skid base, and connecting pipes.",
        "Create a 3D heat exchanger skid with pump, valves, flanges, supports, and labels.",
    ],
)
def test_explicit_3d_process_prompts_route_to_cad3d(prompt: str) -> None:
    assert is_3d_request(prompt) is True
    assert decide_chat_route(prompt) == CHAT_ROUTE_CAD3D


def test_pid_prompt_routes_to_pid_after_3d_negation_checks() -> None:
    prompt = "Create a P&ID with one horizontal separator, valves, instruments, and flow arrows."

    assert is_3d_request(prompt) is False
    assert decide_chat_route(prompt) == CHAT_ROUTE_PID


def test_simple_rectangle_routes_to_sketch() -> None:
    prompt = "Draw a 1000mm by 500mm rectangle with a circle in the center."

    assert decide_chat_route(prompt) == CHAT_ROUTE_SKETCH


def test_simple_edit_routes_to_autocad_edit() -> None:
    prompt = "Delete the title text."

    assert has_cad3d_edit_intent(prompt) is False
    assert decide_chat_route(prompt) == CHAT_ROUTE_EDIT


@pytest.mark.parametrize(
    "prompt",
    [
        "Move pump P-101 1000 mm to the right.",
        "Change V-201 length to 4500 mm.",
        "Set T-101 height to 6000 mm.",
        "Delete pump P-101.",
        "Add support legs under V-201.",
    ],
)
def test_cad3d_component_edit_prompts_route_to_cad3d_edit(prompt: str) -> None:
    assert has_cad3d_edit_intent(prompt) is True
    assert decide_chat_route(prompt) == CHAT_ROUTE_CAD3D_EDIT


def test_title_text_edit_does_not_route_to_cad3d_edit() -> None:
    prompt = "Delete the title text."

    assert has_cad3d_edit_intent(prompt) is False
    assert decide_chat_route(prompt) == CHAT_ROUTE_EDIT


def test_new_3d_generation_prompt_is_not_cad3d_edit() -> None:
    prompt = "Create a 3D tank pump separator layout."

    assert has_cad3d_edit_intent(prompt) is False
    assert decide_chat_route(prompt) == CHAT_ROUTE_CAD3D


def test_move_title_text_up_remains_generic_edit() -> None:
    prompt = "Move title text up."

    assert has_cad3d_edit_intent(prompt) is False
    assert decide_chat_route(prompt) == CHAT_ROUTE_EDIT


@pytest.mark.parametrize(
    "prompt",
    [
        "Draw a rectangle 1000mm wide and 500mm high with a circle in the center.",
        "Create a simple concept sketch of a tank.",
        "Generate a block diagram layout.",
        "Draw a simple process block layout.",
    ],
)
def test_non_pid_creation_prompts_route_to_sketch_generate(prompt: str) -> None:
    assert is_new_drawing_request(prompt) is True
    assert is_edit_request(prompt) is False
    assert decide_chat_route(prompt) == CHAT_ROUTE_SKETCH


@pytest.mark.parametrize(
    "prompt",
    [
        "Delete the circle in the current drawing.",
        "Delete the circle.",
        "Remove the title text.",
        "Move the vessel 500 units to the right.",
        "Add one drain valve to the existing separator outlet.",
        "Add one more valve to the outlet line.",
        "Rename V-201 to V-202.",
        "Connect this line to the vessel.",
        "Edit the current drawing to add a drain valve.",
    ],
)
def test_current_drawing_edit_prompts_route_to_autocad_edit(prompt: str) -> None:
    assert is_edit_request(prompt) is True
    assert decide_chat_route(prompt) == CHAT_ROUTE_EDIT


def test_new_pid_prompt_with_add_words_does_not_route_to_edit() -> None:
    prompt = (
        "Create a detailed P&ID for a small process unit. Add at least 8 gate valves, "
        "add PI-101 on pump discharge, and add title: Integrated Process Unit P&ID."
    )

    assert is_new_drawing_request(prompt) is True
    assert is_pid_request(prompt) is True
    assert is_edit_request(prompt) is False
    assert decide_chat_route(prompt) == CHAT_ROUTE_PID


def test_static_ui_keeps_separate_sketch_and_pid_approve_endpoints() -> None:
    html = Path("src/api/static/sketch.html").read_text(encoding="utf-8")

    assert "/api/sketch/approve" in html
    assert "/api/pid/approve" in html
    assert "/api/cad3d/approve" in html
    assert "/api/cad3d/edit" in html
    assert "data.route_type = CHAT_ROUTES.SKETCH" in html
    assert "data.route_type = CHAT_ROUTES.PID" in html
    assert "data.route_type = CHAT_ROUTES.CAD3D" in html
    assert "CHAT_ROUTES.CAD3D_EDIT" in html
    assert "function decideChatRoute" in html
    assert "function is3DRequest" in html
    assert "function hasNegated3DIntent" in html
    assert "function hasExplicit3DIntent" in html
    assert "function hasExplicit2DIntent" in html
    assert "function hasCAD3DEditIntent" in html
    assert "function hasCAD3DContext" in html
    assert "function shouldRouteToCAD3DEdit" in html
    assert "function handleCAD3DRequest" in html
    assert "function handleCAD3DEditRequest" in html


def test_static_ui_javascript_routing_matches_expected_endpoints() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not available for static UI routing check")

    html = Path("src/api/static/sketch.html").read_text(encoding="utf-8")
    start = html.index("    const CHAT_ROUTES")
    end = html.index("    function detailsHtml")
    routing_js = html[start:end]
    prompts = [
        "Create a 3D equipment layout with tank pump and vessel.",
        "Create a clean professional colored 2D process layout titled Pump Transfer Layout with tank, pump, vessel, and pipes.",
        "Create a 2D flat AutoCAD P&ID diagram, not a 3D model.",
        "Create a clean professional 3D equipment layout with tank, pump, vessel, skid base, and connecting pipes.",
        "Create an equipment layout with tank, pump, vessel, and connecting pipes.",
        "Create a 3D heat exchanger skid with pump, valves, flanges, supports, and labels.",
        "Create a heat exchanger skid with pump, valves, flanges, supports, and labels.",
        "Create a P&ID with one horizontal separator, valves, instruments, and flow arrows.",
        "Draw a 1000mm by 500mm rectangle with a circle in the center.",
        "Delete the title text.",
        "Create a 2D process diagram with tank, pump, separator, pipes, and labels, no 3D.",
        "Create a detailed P&ID for a small process unit.",
        "Draw a rectangle 1000mm wide and 500mm high with a circle in the center.",
        "Delete the circle.",
        "Remove the title text.",
    ]
    script = (
        routing_js
        + "\nconst prompts = "
        + json.dumps(prompts)
        + ";\nconsole.log(JSON.stringify(prompts.map((prompt) => decideChatRoute(prompt))));\n"
    )

    result = subprocess.run(
        [node, "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == [
        CHAT_ROUTE_CAD3D,
        CHAT_ROUTE_PID,
        CHAT_ROUTE_PID,
        CHAT_ROUTE_CAD3D,
        CHAT_ROUTE_PID,
        CHAT_ROUTE_CAD3D,
        CHAT_ROUTE_PID,
        CHAT_ROUTE_PID,
        CHAT_ROUTE_SKETCH,
        CHAT_ROUTE_EDIT,
        CHAT_ROUTE_PID,
        CHAT_ROUTE_PID,
        CHAT_ROUTE_SKETCH,
        CHAT_ROUTE_EDIT,
        CHAT_ROUTE_EDIT,
    ]


def test_static_ui_routes_cad3d_edits_when_cad3d_context_exists() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not available for static UI routing check")

    html = Path("src/api/static/sketch.html").read_text(encoding="utf-8")
    start = html.index("    const CHAT_ROUTES")
    end = html.index("    function detailsHtml")
    routing_js = html[start:end]
    prompts = [
        "Move pump P-101 1000 mm to the right.",
        "Change V-201 length to 4500 mm.",
        "Set T-101 height to 6000 mm.",
        "Delete pump P-101.",
        "Add support legs under V-201.",
        "Delete the title text.",
        "Create a 3D tank pump separator layout.",
        "Create a 2D flat P&ID diagram.",
        "Draw a rectangle with a circle.",
        "Move title text up.",
    ]
    script = (
        "let latestGeneration = { token: 'cad3d-token', type: 'cad3d', approveUrl: '/api/cad3d/approve', editUrl: '/api/cad3d/edit' };\n"
        "let latestCAD3DToken = 'cad3d-token';\n"
        + routing_js
        + "\nconst prompts = "
        + json.dumps(prompts)
        + ";\nconsole.log(JSON.stringify(prompts.map((prompt) => decideChatRoute(prompt))));\n"
    )

    result = subprocess.run(
        [node, "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == [
        CHAT_ROUTE_CAD3D_EDIT,
        CHAT_ROUTE_CAD3D_EDIT,
        CHAT_ROUTE_CAD3D_EDIT,
        CHAT_ROUTE_CAD3D_EDIT,
        CHAT_ROUTE_CAD3D_EDIT,
        CHAT_ROUTE_EDIT,
        CHAT_ROUTE_CAD3D,
        CHAT_ROUTE_PID,
        CHAT_ROUTE_SKETCH,
        CHAT_ROUTE_EDIT,
    ]

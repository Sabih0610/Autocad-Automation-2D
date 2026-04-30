from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from src.api.chat_routing import (
    CHAT_ROUTE_EDIT,
    CHAT_ROUTE_PID,
    CHAT_ROUTE_SKETCH,
    decide_chat_route,
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
    assert "data.route_type = CHAT_ROUTES.SKETCH" in html
    assert "data.route_type = CHAT_ROUTES.PID" in html
    assert "function decideChatRoute" in html


def test_static_ui_javascript_routing_matches_expected_endpoints() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not available for static UI routing check")

    html = Path("src/api/static/sketch.html").read_text(encoding="utf-8")
    start = html.index("    const CHAT_ROUTES")
    end = html.index("    function detailsHtml")
    routing_js = html[start:end]
    prompts = [
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
        CHAT_ROUTE_PID,
        CHAT_ROUTE_SKETCH,
        CHAT_ROUTE_EDIT,
        CHAT_ROUTE_EDIT,
    ]

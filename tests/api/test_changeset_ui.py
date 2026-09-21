import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest


def _render_change_set_controls(page_path: str, data: dict) -> str:
    node = shutil.which("node")

    if node is None:
        pytest.skip(
            "Node.js is not available for static UI rendering check"
        )

    html = Path(page_path).read_text(
        encoding="utf-8"
    )

    start_marker = (
        "function changeSetControlsHtml(data) {"
    )

    end_marker = (
        "async function performChangeSetAction"
    )

    assert start_marker in html, (
        f"{page_path} does not define "
        "changeSetControlsHtml(data)"
    )

    assert end_marker in html, (
        f"{page_path} does not define "
        "performChangeSetAction(...)"
    )

    start = html.index(start_marker)
    end = html.index(
        end_marker,
        start,
    )

    renderer_js = html[start:end]

    script = f"""
function escapeText(value) {{
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}}

{renderer_js}

const payload = {json.dumps(data)};

process.stdout.write(
  changeSetControlsHtml(payload)
);
"""

    completed = subprocess.run(
        [
            node,
            "-e",
            script,
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    return completed.stdout


def _assert_button_text(
    html: str,
    label: str,
) -> None:
    """
    Assert that a rendered HTML button contains the requested text without
    depending on indentation or line wrapping.

    Both of these are equivalent:

        <button>Revert</button>

    and:

        <button>
            Revert
        </button>
    """
    pattern = (
        r">\s*"
        + re.escape(label)
        + r"\s*<"
    )

    assert re.search(
        pattern,
        html,
        flags=re.DOTALL,
    ), (
        f"Could not find button/text label "
        f"{label!r} in rendered HTML:\n{html}"
    )


def _assert_result_renderer_used(
    html: str,
    renderer: str,
) -> None:
    """
    Verify createResultMessage(data, renderer(data)) regardless of whitespace
    and line wrapping.
    """
    pattern = (
        r"createResultMessage\s*"
        r"\(\s*"
        r"data\s*,\s*"
        + re.escape(renderer)
        + r"\s*\(\s*data\s*\)"
    )

    assert re.search(
        pattern,
        html,
        flags=re.DOTALL,
    ), (
        f"{renderer}(data) is not passed "
        "to createResultMessage(data, ...)"
    )


def test_all_write_surfaces_render_safe_changeset_controls() -> None:
    sketch_path = (
        "src/api/static/sketch.html"
    )

    place_symbol_path = (
        "src/api/static/place_symbol.html"
    )

    malicious_id = (
        'cs-123"><img src=x '
        'onerror=alert(1)>'
    )

    malicious_reason = (
        '<script>'
        'alert("stored-xss")'
        '</script>'
    )

    for page_path in (
        sketch_path,
        place_symbol_path,
    ):
        action_html = (
            _render_change_set_controls(
                page_path,
                {
                    "change_set_id":
                        malicious_id,
                    "change_set_skipped_reason":
                        None,
                },
            )
        )

        assert "Change set:" in action_html

        _assert_button_text(
            action_html,
            "Revert",
        )

        _assert_button_text(
            action_html,
            "Keep",
        )

        # Raw server-controlled HTML must never survive.
        assert malicious_id not in action_html
        assert "<img" not in action_html

        # The tag must instead be encoded as text.
        assert (
            "&lt;img src=x "
            "onerror=alert(1)&gt;"
            in action_html
        )

        info_html = (
            _render_change_set_controls(
                page_path,
                {
                    "change_set_id":
                        None,
                    "change_set_skipped_reason":
                        malicious_reason,
                },
            )
        )

        assert (
            "Change history:"
            in info_html
        )

        assert (
            'class="change-set-panel info"'
            in info_html
        )

        # A skipped ChangeSet is informational.
        # It must not provide Keep/Revert buttons.
        assert (
            "change-set-button"
            not in info_html
        )

        # It must also be escaped rather than
        # inserted as executable HTML.
        assert (
            malicious_reason
            not in info_html
        )

        assert (
            "<script>"
            not in info_html
        )

        assert (
            "&lt;script&gt;"
            in info_html
        )


def test_sketch_write_routes_use_changeset_result_renderer() -> None:
    sketch_path = Path(
        "src/api/static/sketch.html"
    )

    sketch_html = (
        sketch_path.read_text(
            encoding="utf-8"
        )
    )

    endpoints = (
        "/api/sketch/approve",
        "/api/pid/approve",
        "/api/cad3d/approve",
        "/api/cad3d/edit",
        "/api/autocad/edit",
    )

    for endpoint in endpoints:
        assert endpoint in sketch_html

    renderers = (
        "buildResultHtml",
        "pidBuildResultHtml",
        "cad3dBuildResultHtml",
        "cad3dEditResultHtml",
        "editResultHtml",
    )

    for renderer in renderers:
        _assert_result_renderer_used(
            sketch_html,
            renderer,
        )

    # All five active-drawing write paths
    # must explicitly opt in.
    assert (
        sketch_html.count(
            "use_active_document: true"
        )
        >= 5
    )

    # Verify the ChangeSet action URL exists
    # without depending on code indentation.
    assert (
        "/api/change-sets/"
        "${encodeURIComponent(changeSetId)}"
        "/${action}"
        in sketch_html
    )


def test_place_symbol_surface_uses_changeset_controls() -> None:
    place_symbol_path = Path(
        "src/api/static/place_symbol.html"
    )

    place_symbol_html = (
        place_symbol_path.read_text(
            encoding="utf-8"
        )
    )

    assert (
        "/api/place-symbol"
        in place_symbol_html
    )

    assert re.search(
        r"renderChangeSetControls\s*"
        r"\(\s*data\s*\)\s*;",
        place_symbol_html,
        flags=re.DOTALL,
    )

    assert re.search(
        r"use_active_document\s*:\s*"
        r"execute",
        place_symbol_html,
        flags=re.DOTALL,
    )

    assert (
        "/api/change-sets/"
        "${encodeURIComponent(changeSetId)}"
        "/${action}"
        in place_symbol_html
    )
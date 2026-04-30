from __future__ import annotations

import pytest

from src.use_cases import sketch_drawing as sketch_module
from src.use_cases.sketch_drawing import sketch_drawing


APPROVE_VERIFICATION = {
    "schema_version": "1.0",
    "verdict": "APPROVE",
    "summary": "The command sequence appears internally consistent.",
    "issues": [],
    "command_annotations": [],
}

NOTES_VERIFICATION = {
    "schema_version": "1.0",
    "verdict": "APPROVE_WITH_NOTES",
    "summary": "The sequence can execute, but one label may need review.",
    "issues": [
        {
            "severity": "WARNING",
            "description": "Text label may overlap geometry.",
            "command_index": 2,
            "suggested_fix": "Move label upward.",
        }
    ],
    "command_annotations": [
        {
            "command_index": 2,
            "annotation": "Possible label overlap.",
            "concern_level": "MINOR",
        }
    ],
}

REJECT_VERIFICATION = {
    "schema_version": "1.0",
    "verdict": "REJECT",
    "summary": "The command sequence has blocker issues.",
    "issues": [
        {
            "severity": "BLOCKER",
            "description": "Rectangle is missing one side.",
            "command_index": 3,
            "suggested_fix": "Add the missing closing LINE command.",
        }
    ],
    "command_annotations": [],
}


def _fake_command_sequence() -> dict:
    return {
        "schema_version": "1.0",
        "summary": "Simple rectangle",
        "estimated_drawing_type": "test",
        "assumptions": ["Draft-quality test."],
        "commands": [
            {"command": "LAYER", "layer_name": "TEST"},
            {"command": "LINE", "from": [0, 0], "to": [100, 0], "layer": "TEST"},
        ],
    }


def _patch_generator_verifier_executor(
    monkeypatch,
    verifier_result: dict | None = None,
    execution_result: dict | None = None,
    preview_path: str = r"E:\RC-Projects\autocad-ai\outputs\previews\test_preview.dxf",
    preview_error: Exception | None = None,
):
    captured = {
        "generator_prompt": None,
        "verifier_called": False,
        "verifier_prompt": None,
        "verifier_output": None,
        "preview_called": False,
        "preview_output": None,
        "executor_called": False,
        "target_dwg_path": None,
        "save": None,
    }

    def fake_generate(prompt):
        captured["generator_prompt"] = prompt
        return _fake_command_sequence()

    def fake_verify(prompt, command_sequence):
        captured["verifier_called"] = True
        captured["verifier_prompt"] = prompt
        captured["verifier_output"] = command_sequence
        return verifier_result or APPROVE_VERIFICATION

    def fake_preview(command_sequence, output_path):
        captured["preview_called"] = True
        captured["preview_output"] = output_path

        if preview_error is not None:
            raise preview_error

        return output_path or preview_path

    def fake_execute(command_sequence, target_dwg_path=None, save=True):
        captured["executor_called"] = True
        captured["target_dwg_path"] = target_dwg_path
        captured["save"] = save
        return execution_result or _fake_execution_result()

    monkeypatch.setattr(sketch_module, "generate_commands", fake_generate)
    monkeypatch.setattr(sketch_module, "verify_commands", fake_verify)
    monkeypatch.setattr(sketch_module, "render_preview_sequence", fake_preview)
    monkeypatch.setattr(sketch_module, "execute_command_sequence", fake_execute)

    return captured


def _fake_execution_result(ok: bool = True) -> dict:
    return {
        "ok": ok,
        "executed_count": 2 if ok else 1,
        "total_count": 2,
        "errors": [] if ok else [{"command_index": 1, "error": "test error"}],
        "dwg_path": None,
    }


def test_empty_prompt_raises_value_error() -> None:
    with pytest.raises(ValueError, match="prompt cannot be empty"):
        sketch_drawing("  ")


def test_user_cancel_does_not_call_executor(monkeypatch) -> None:
    captured = _patch_generator_verifier_executor(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")

    result = sketch_drawing("draw a rectangle")

    assert result["ok"] is False
    assert result["reason"] == "User cancelled"
    assert result["executed"] is False
    assert result["verifier_result"] == APPROVE_VERIFICATION
    assert result["verifier_verdict"] == "APPROVE"
    assert result["preview_created"] is True
    assert result["preview_path"]
    assert captured["executor_called"] is False


def test_default_auto_confirm_calls_generator_verifier_preview_and_executor(monkeypatch) -> None:
    captured = _patch_generator_verifier_executor(monkeypatch)

    result = sketch_drawing("  draw a rectangle  ", auto_confirm=True)

    assert captured["generator_prompt"] == "draw a rectangle"
    assert captured["verifier_called"] is True
    assert captured["verifier_prompt"] == "draw a rectangle"
    assert captured["preview_called"] is True
    assert captured["executor_called"] is True
    assert result["ok"] is True
    assert result["executed"] is True


def test_run_verifier_false_skips_verifier_and_still_executes(monkeypatch) -> None:
    captured = _patch_generator_verifier_executor(monkeypatch)

    result = sketch_drawing(
        "draw a rectangle",
        auto_confirm=True,
        run_verifier=False,
    )

    assert captured["verifier_called"] is False
    assert captured["executor_called"] is True
    assert result["verifier_result"] is None
    assert result["verifier_verdict"] is None
    assert result["ok"] is True


def test_create_preview_false_skips_preview_and_still_executes(monkeypatch) -> None:
    captured = _patch_generator_verifier_executor(monkeypatch)

    result = sketch_drawing(
        "draw a rectangle",
        auto_confirm=True,
        create_preview=False,
    )

    assert captured["preview_called"] is False
    assert captured["executor_called"] is True
    assert result["preview_path"] is None
    assert result["preview_created"] is False
    assert result["ok"] is True


def test_preview_output_path_is_passed_to_preview_renderer(monkeypatch) -> None:
    captured = _patch_generator_verifier_executor(monkeypatch)

    result = sketch_drawing(
        "draw a rectangle",
        auto_confirm=True,
        preview_output_path=r"E:\RC-Projects\custom_preview.dxf",
    )

    assert captured["preview_output"] == r"E:\RC-Projects\custom_preview.dxf"
    assert result["preview_path"] == r"E:\RC-Projects\custom_preview.dxf"
    assert result["preview_created"] is True


def test_result_includes_preview_path_when_preview_succeeds(monkeypatch) -> None:
    _patch_generator_verifier_executor(monkeypatch)

    result = sketch_drawing("draw a rectangle", auto_confirm=True)

    assert result["preview_created"] is True
    assert result["preview_path"]


def test_preview_error_stops_before_executor(monkeypatch) -> None:
    captured = _patch_generator_verifier_executor(
        monkeypatch,
        preview_error=RuntimeError("preview broke"),
    )

    result = sketch_drawing("draw a rectangle", auto_confirm=True)

    assert captured["preview_called"] is True
    assert captured["executor_called"] is False
    assert result["ok"] is False
    assert result["reason"] == "Preview generation failed"
    assert result["executed"] is False
    assert result["preview_created"] is False
    assert result["preview_error"] == "RuntimeError: preview broke"


def test_approve_verifier_result_is_included(monkeypatch) -> None:
    _patch_generator_verifier_executor(monkeypatch, verifier_result=APPROVE_VERIFICATION)

    result = sketch_drawing("draw a rectangle", auto_confirm=True)

    assert result["verifier_verdict"] == "APPROVE"
    assert result["verifier_result"] == APPROVE_VERIFICATION


def test_approve_with_notes_includes_notes_and_executes_with_auto_confirm(monkeypatch) -> None:
    captured = _patch_generator_verifier_executor(
        monkeypatch,
        verifier_result=NOTES_VERIFICATION,
    )

    result = sketch_drawing("draw a rectangle", auto_confirm=True)

    assert captured["executor_called"] is True
    assert result["verifier_verdict"] == "APPROVE_WITH_NOTES"
    assert result["verifier_result"]["issues"][0]["severity"] == "WARNING"
    assert result["ok"] is True


def test_reject_verifier_result_user_cancel_does_not_call_executor(monkeypatch) -> None:
    captured = _patch_generator_verifier_executor(
        monkeypatch,
        verifier_result=REJECT_VERIFICATION,
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "n")

    result = sketch_drawing("draw a rectangle")

    assert captured["executor_called"] is False
    assert result["ok"] is False
    assert result["reason"] == "User cancelled"
    assert result["verifier_verdict"] == "REJECT"
    assert result["verifier_result"] == REJECT_VERIFICATION


def test_reject_verifier_result_auto_confirm_still_executes(monkeypatch) -> None:
    captured = _patch_generator_verifier_executor(
        monkeypatch,
        verifier_result=REJECT_VERIFICATION,
    )

    result = sketch_drawing("draw a rectangle", auto_confirm=True)

    assert captured["executor_called"] is True
    assert result["verifier_verdict"] == "REJECT"
    assert result["ok"] is True


def test_result_includes_summary_assumptions_command_count_and_execution_result(monkeypatch) -> None:
    execution_result = _fake_execution_result()
    _patch_generator_verifier_executor(
        monkeypatch,
        execution_result=execution_result,
    )

    result = sketch_drawing("draw a rectangle", auto_confirm=True)

    assert result["summary"] == "Simple rectangle"
    assert result["estimated_drawing_type"] == "test"
    assert result["assumptions"] == ["Draft-quality test."]
    assert result["command_count"] == 2
    assert result["verifier_result"] == APPROVE_VERIFICATION
    assert result["verifier_verdict"] == "APPROVE"
    assert result["preview_created"] is True
    assert result["preview_path"]
    assert result["execution_result"] == execution_result


def test_no_save_passes_save_false_to_executor(monkeypatch) -> None:
    captured = _patch_generator_verifier_executor(monkeypatch)

    sketch_drawing("draw a rectangle", auto_confirm=True, save=False)

    assert captured["save"] is False


def test_target_dwg_path_is_passed_to_executor(monkeypatch) -> None:
    captured = _patch_generator_verifier_executor(monkeypatch)

    sketch_drawing(
        "draw a rectangle",
        auto_confirm=True,
        target_dwg_path=r"E:\RC-Projects\test.dwg",
    )

    assert captured["target_dwg_path"] == r"E:\RC-Projects\test.dwg"


def test_executor_errors_are_included_in_result(monkeypatch) -> None:
    execution_result = _fake_execution_result(ok=False)
    _patch_generator_verifier_executor(
        monkeypatch,
        execution_result=execution_result,
    )

    result = sketch_drawing("draw a rectangle", auto_confirm=True)

    assert result["ok"] is False
    assert result["execution_result"]["errors"] == [
        {"command_index": 1, "error": "test error"}
    ]


def test_cli_skip_verifier_passes_run_verifier_false(monkeypatch) -> None:
    captured = {}

    def fake_sketch_drawing(
        prompt,
        auto_confirm=False,
        save=True,
        target_dwg_path=None,
        run_verifier=True,
        create_preview=True,
        preview_output_path=None,
    ):
        captured["prompt"] = prompt
        captured["auto_confirm"] = auto_confirm
        captured["save"] = save
        captured["target_dwg_path"] = target_dwg_path
        captured["run_verifier"] = run_verifier
        captured["create_preview"] = create_preview
        captured["preview_output_path"] = preview_output_path
        return {
            "ok": True,
            "verifier_verdict": None,
            "preview_path": None,
            "execution_result": {"executed_count": 2},
        }

    monkeypatch.setattr(sketch_module, "sketch_drawing", fake_sketch_drawing)
    monkeypatch.setattr(
        "sys.argv",
        [
            "sketch_drawing",
            "--prompt",
            "draw a rectangle",
            "--yes",
            "--no-save",
            "--target-dwg",
            r"E:\RC-Projects\test.dwg",
            "--skip-verifier",
        ],
    )

    sketch_module._cli()

    assert captured == {
        "prompt": "draw a rectangle",
        "auto_confirm": True,
        "save": False,
        "target_dwg_path": r"E:\RC-Projects\test.dwg",
        "run_verifier": False,
        "create_preview": True,
        "preview_output_path": None,
    }


def test_cli_skip_preview_passes_create_preview_false(monkeypatch) -> None:
    captured = {}

    def fake_sketch_drawing(
        prompt,
        auto_confirm=False,
        save=True,
        target_dwg_path=None,
        run_verifier=True,
        create_preview=True,
        preview_output_path=None,
    ):
        captured["create_preview"] = create_preview
        captured["preview_output_path"] = preview_output_path
        return {
            "ok": True,
            "verifier_verdict": "APPROVE",
            "preview_path": None,
            "execution_result": {"executed_count": 2},
        }

    monkeypatch.setattr(sketch_module, "sketch_drawing", fake_sketch_drawing)
    monkeypatch.setattr(
        "sys.argv",
        [
            "sketch_drawing",
            "--prompt",
            "draw a rectangle",
            "--yes",
            "--skip-preview",
        ],
    )

    sketch_module._cli()

    assert captured["create_preview"] is False
    assert captured["preview_output_path"] is None


def test_cli_preview_output_passes_custom_preview_path(monkeypatch) -> None:
    captured = {}

    def fake_sketch_drawing(
        prompt,
        auto_confirm=False,
        save=True,
        target_dwg_path=None,
        run_verifier=True,
        create_preview=True,
        preview_output_path=None,
    ):
        captured["create_preview"] = create_preview
        captured["preview_output_path"] = preview_output_path
        return {
            "ok": True,
            "verifier_verdict": "APPROVE",
            "preview_path": preview_output_path,
            "execution_result": {"executed_count": 2},
        }

    monkeypatch.setattr(sketch_module, "sketch_drawing", fake_sketch_drawing)
    monkeypatch.setattr(
        "sys.argv",
        [
            "sketch_drawing",
            "--prompt",
            "draw a rectangle",
            "--yes",
            "--preview-output",
            r"E:\RC-Projects\custom_preview.dxf",
        ],
    )

    sketch_module._cli()

    assert captured["create_preview"] is True
    assert captured["preview_output_path"] == r"E:\RC-Projects\custom_preview.dxf"

"""Mode 2 sketch drawing CLI.

Natural language prompt
-> AI-generated structured command JSON
-> user review and confirmation
-> deterministic AutoCAD command executor
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from src.ai.command_generator import generate_commands
from src.ai.command_verifier import verify_commands
from src.framework.commands.executor import execute_command_sequence
from src.framework.commands.preview import render_preview_sequence


def _identity_log_job(_job_name: str) -> Callable:
    """Fallback decorator if project logging is not available."""
    def decorator(func: Callable) -> Callable:
        return func

    return decorator


try:
    from src.logging.decorators import log_job  # type: ignore
except Exception:
    log_job = _identity_log_job


def _print_review(command_sequence: dict[str, Any]) -> None:
    summary = command_sequence.get("summary") or ""
    estimated_drawing_type = command_sequence.get("estimated_drawing_type") or ""
    assumptions = command_sequence.get("assumptions") or []
    commands = command_sequence.get("commands") or []

    print()
    print(f"Summary: {summary}")
    print(f"Estimated drawing type: {estimated_drawing_type or 'unspecified'}")
    print("Assumptions:")

    if assumptions:
        for assumption in assumptions:
            print(f"  - {assumption}")
    else:
        print("  - none")

    print(f"Command count: {len(commands)}")
    print()


def _print_verifier_review(verifier_result: dict[str, Any]) -> None:
    verdict = verifier_result.get("verdict") or "UNKNOWN"
    summary = verifier_result.get("summary") or ""
    issues = verifier_result.get("issues") or []
    annotations = verifier_result.get("command_annotations") or []

    print()
    print(f"Verifier verdict: {verdict}")
    print(f"Verifier summary: {summary}")
    print("Verifier issues:")

    if issues:
        for issue in issues:
            severity = issue.get("severity", "UNKNOWN")
            description = issue.get("description", "")
            command_index = issue.get("command_index")
            suggested_fix = issue.get("suggested_fix")
            location = (
                f" command {command_index}"
                if command_index is not None
                else ""
            )
            print(f"  - [{severity}]{location}: {description}")

            if suggested_fix:
                print(f"    Suggested fix: {suggested_fix}")
    else:
        print("  - none")

    if annotations:
        print(f"Command annotations: {len(annotations)}")
    else:
        print("Command annotations: none")

    print()


def _confirmation_prompt_for(verifier_verdict: str | None) -> str:
    if verifier_verdict == "REJECT":
        return "Verifier rejected this command sequence. Execute anyway? [y/n]: "

    if verifier_verdict == "APPROVE_WITH_NOTES":
        print("Verifier returned notes. Review them before executing.")

    return "Execute these commands in AutoCAD? [y/n]: "


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_preview_output_path() -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return _project_root() / "outputs" / "previews" / f"sketch_preview_{timestamp}.dxf"


@log_job("sketch_drawing")
def sketch_drawing(
    prompt: str,
    auto_confirm: bool = False,
    save: bool = True,
    target_dwg_path: str | None = None,
    run_verifier: bool = True,
    create_preview: bool = True,
    preview_output_path: str | None = None,
) -> dict:
    """Generate and optionally execute a Mode 2 sketch command sequence."""
    clean_prompt = prompt.strip()

    if not clean_prompt:
        raise ValueError("prompt cannot be empty")

    print("Generating AutoCAD command sequence with AI...")
    command_sequence = generate_commands(clean_prompt)

    _print_review(command_sequence)

    verifier_result = None
    verifier_verdict = None

    if run_verifier:
        print("Verifying command sequence with AI...")
        verifier_result = verify_commands(clean_prompt, command_sequence)
        verifier_verdict = verifier_result.get("verdict")
        _print_verifier_review(verifier_result)
    else:
        print("Verifier skipped.")

    preview_path = None
    preview_created = False

    if create_preview:
        print("Rendering DXF preview...")
        preview_target = (
            Path(preview_output_path)
            if preview_output_path
            else _default_preview_output_path()
        )

        try:
            preview_path = render_preview_sequence(command_sequence, str(preview_target))
            preview_created = True
        except Exception as exc:
            preview_error = f"{type(exc).__name__}: {exc}"
            return {
                "ok": False,
                "reason": "Preview generation failed",
                "executed": False,
                "prompt": clean_prompt,
                "summary": command_sequence.get("summary"),
                "estimated_drawing_type": command_sequence.get("estimated_drawing_type"),
                "assumptions": command_sequence.get("assumptions", []),
                "command_count": len(command_sequence.get("commands", [])),
                "verifier_result": verifier_result,
                "verifier_verdict": verifier_verdict,
                "preview_path": None,
                "preview_created": False,
                "preview_error": preview_error,
            }

        print(f"Preview DXF written to: {preview_path}")
    else:
        print("Preview skipped.")

    if not auto_confirm:
        if preview_created:
            prompt_text = "Review the DXF preview, then execute these commands in AutoCAD? [y/n]: "
        else:
            prompt_text = _confirmation_prompt_for(verifier_verdict)

        answer = input(prompt_text).strip().lower()

        if answer != "y":
            return {
                "ok": False,
                "reason": "User cancelled",
                "executed": False,
                "verifier_result": verifier_result,
                "verifier_verdict": verifier_verdict,
                "preview_path": preview_path,
                "preview_created": preview_created,
            }

    execution_result = execute_command_sequence(
        command_sequence,
        target_dwg_path=target_dwg_path,
        save=save,
    )

    return {
        "ok": bool(execution_result.get("ok")),
        "executed": True,
        "prompt": clean_prompt,
        "summary": command_sequence.get("summary"),
        "estimated_drawing_type": command_sequence.get("estimated_drawing_type"),
        "assumptions": command_sequence.get("assumptions", []),
        "command_count": len(command_sequence.get("commands", [])),
        "verifier_result": verifier_result,
        "verifier_verdict": verifier_verdict,
        "preview_path": preview_path,
        "preview_created": preview_created,
        "execution_result": execution_result,
    }


def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="Generate and execute a draft AutoCAD sketch from a prompt.",
    )
    parser.add_argument(
        "--prompt",
        required=True,
        help="Natural-language drawing request.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation and execute immediately.",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Do not save the drawing after command execution.",
    )
    parser.add_argument(
        "--target-dwg",
        default=None,
        help="Optional DWG path to open before executing commands.",
    )
    parser.add_argument(
        "--skip-verifier",
        action="store_true",
        help="Skip AI verification before confirmation and execution.",
    )
    parser.add_argument(
        "--skip-preview",
        action="store_true",
        help="Skip DXF preview generation before confirmation and execution.",
    )
    parser.add_argument(
        "--preview-output",
        default=None,
        help="Optional path for the generated DXF preview.",
    )

    args = parser.parse_args()

    try:
        result = sketch_drawing(
            prompt=args.prompt,
            auto_confirm=args.yes,
            save=not args.no_save,
            target_dwg_path=args.target_dwg,
            run_verifier=not args.skip_verifier,
            create_preview=not args.skip_preview,
            preview_output_path=args.preview_output,
        )
    except Exception as exc:
        print(f"Failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)

    if not result.get("ok"):
        print(f"Failed: {result.get('reason', 'Command execution failed.')}", file=sys.stderr)
        execution_result = result.get("execution_result") or {}

        for error in execution_result.get("errors", []):
            print(f"  - {error}", file=sys.stderr)

        sys.exit(1)

    execution_result = result.get("execution_result") or {}
    verifier_verdict = result.get("verifier_verdict")
    preview_path = result.get("preview_path")

    if preview_path:
        print(f"Preview DXF: {preview_path}")

    if verifier_verdict:
        print(f"Verifier verdict: {verifier_verdict}")

    print(f"Executed commands: {execution_result.get('executed_count', 0)}")


if __name__ == "__main__":
    _cli()

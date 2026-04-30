"""
End-to-end vessel generator.

Phase 20:
Natural language vessel request
-> AI extracts structured parameters
-> user reviews extracted values
-> deterministic validation runs
-> vessel renderer creates DXF or DWG

Important:
AI does not draw CAD.
AI only extracts parameters.
The deterministic generator validates and renders.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from src.ai.vessel_planner import (
    extracted_to_vessel_parameters,
    format_for_review,
    plan_vessel,
)
from src.parametric.vessel.parameters import validate_parameters
from src.parametric.vessel.render import render_vessel


def _identity_log_job(_job_name: str) -> Callable:
    """Fallback decorator if project logging is not available."""
    def decorator(func: Callable) -> Callable:
        return func

    return decorator


try:
    from src.logging.decorators import log_job  # type: ignore
except Exception:
    log_job = _identity_log_job


def _project_root() -> Path:
    """Return project root from this file location."""
    return Path(__file__).resolve().parents[2]


def _safe_filename(value: str) -> str:
    """Make a safe filename from a vessel tag."""
    return (
        str(value)
        .replace(" ", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
    )


@log_job("generate_vessel")
def generate_vessel(
    user_prompt: str,
    output_format: str = "dwg",
    auto_confirm: bool = False,
) -> dict[str, Any]:
    """
    Run the full natural-language -> vessel drawing pipeline.

    Args:
        user_prompt:
            Natural-language vessel request.

        output_format:
            "dxf" or "dwg".
            DWG requires AutoCAD to be open.

        auto_confirm:
            If True, skip the user confirmation prompt.

    Returns:
        Result dict from the rendering pipeline.
    """
    if not user_prompt or not user_prompt.strip():
        return {
            "ok": False,
            "reason": "Prompt is empty.",
        }

    output_format = output_format.lower().strip()

    if output_format not in {"dxf", "dwg"}:
        return {
            "ok": False,
            "reason": f"Unsupported output format: {output_format}",
        }

    print("Extracting vessel parameters with AI...")
    extracted = plan_vessel(user_prompt)

    print()
    print(format_for_review(extracted))
    print()

    if not auto_confirm:
        answer = input("Generate this vessel? [y/n]: ").strip().lower()

        if answer not in {"y", "yes"}:
            return {
                "ok": False,
                "reason": "User cancelled after review.",
                "extracted": extracted,
            }

    params = extracted_to_vessel_parameters(extracted)

    validation_errors = validate_parameters(params)

    if validation_errors:
        return {
            "ok": False,
            "reason": "Validation failed.",
            "errors": validation_errors,
            "extracted": extracted,
        }

    project_root = _project_root()
    output_dir = project_root / "outputs" / "vessels"
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    extension = "dwg" if output_format == "dwg" else "dxf"

    output_path = output_dir / f"{_safe_filename(params.tag)}_ai_{timestamp}.{extension}"

    print(f"Rendering {params.tag} to {output_format.upper()}...")
    print(f"Output path: {output_path}")

    result = render_vessel(
        params=params,
        output_path=str(output_path),
        output_format=output_format,
    )

    return {
        "ok": bool(result.get("ok")),
        "format": result.get("format"),
        "path": result.get("path"),
        "dxf_intermediate": result.get("dxf_intermediate"),
        "scale": result.get("scale"),
        "sheet": result.get("sheet"),
        "vessel_tag": params.tag,
        "extracted": extracted,
        "message": result.get("message"),
    }


def _cli() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        description="Generate a vessel drawing from a natural-language prompt.",
    )

    parser.add_argument(
        "--prompt",
        required=True,
        help="Natural-language vessel description.",
    )

    parser.add_argument(
        "--format",
        choices=["dxf", "dwg"],
        default="dwg",
        help="Output format. DWG requires AutoCAD running.",
    )

    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt.",
    )

    args = parser.parse_args()

    try:
        result = generate_vessel(
            user_prompt=args.prompt,
            output_format=args.format,
            auto_confirm=args.yes,
        )
    except Exception as exc:
        print(f"Failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)

    print()
    print("Result:")
    print(result)

    if not result.get("ok"):
        print()
        print(f"Failed: {result.get('reason', 'Unknown error')}", file=sys.stderr)

        for error in result.get("errors", []):
            print(f"  - {error}", file=sys.stderr)

        sys.exit(1)

    print()
    print(f"Done: {result.get('path')}")


if __name__ == "__main__":
    _cli()
"""
Batch render vessel examples.

Phase 18 Step 2:
- Render all canonical vessel examples.
- Save each DXF into one timestamped batch folder.
- Print success/failure per vessel.
- Report selected sheet scale for each vessel.

Run from project root:
    python -m src.parametric.vessel.batch_render
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from traceback import format_exc

from src.parametric.vessel.examples import get_all_examples
from src.parametric.vessel.parameters import validate_parameters
from src.parametric.vessel.render import render_vessel_dxf


def safe_filename(name: str) -> str:
    """Make a safe filename from an example name."""
    return (
        name.replace(" ", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
    )


def batch_render_all() -> Path:
    """
    Render all vessel examples into a timestamped output folder.

    Returns:
        Path to the batch output folder.
    """
    project_root = Path(__file__).resolve().parents[3]

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_dir = project_root / "outputs" / "vessels" / f"batch_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    examples = get_all_examples()

    print("Batch rendering vessel examples")
    print(f"Output folder: {output_dir}")
    print(f"Example count: {len(examples)}")
    print("-" * 80)

    success_count = 0
    failure_count = 0

    for example_name, params in examples.items():
        print(f"\nRendering: {example_name} ({params.tag})")

        validation_errors = validate_parameters(params)

        if validation_errors:
            failure_count += 1
            print("STATUS: FAILED VALIDATION")
            for error in validation_errors:
                print(f"  - {error}")
            continue

        output_path = output_dir / f"{safe_filename(example_name)}_{safe_filename(params.tag)}.dxf"

        try:
            layout = render_vessel_dxf(params, str(output_path))

            success_count += 1
            print("STATUS: OK")
            print(f"DXF: {output_path}")
            print(f"Sheet: {layout.paper.name}")
            print(f"Scale: {layout.scale_text}")
            print(
                "Modelspace sheet size: "
                f"{layout.sheet_width:.0f} x {layout.sheet_height:.0f} mm"
            )

        except Exception:
            failure_count += 1
            print("STATUS: FAILED RENDER")
            print(format_exc())

    print("\n" + "=" * 80)
    print("Batch render complete")
    print(f"Success: {success_count}")
    print(f"Failed: {failure_count}")
    print(f"Output folder: {output_dir}")
    print("=" * 80)

    return output_dir


def main() -> None:
    """CLI entry point."""
    batch_render_all()


if __name__ == "__main__":
    main()
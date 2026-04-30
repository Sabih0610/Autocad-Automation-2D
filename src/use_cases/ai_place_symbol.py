"""
Phase 5 AI-driven symbol placer.

Pipeline:
1. User writes a natural language drafting instruction.
2. AI planner converts it into validated symbol placement JSON.
3. AutoCAD executor inserts the symbol.

Dry-run by default:
    python -m src.use_cases.ai_place_symbol --prompt "Add pump P-101 at 500,250 on layer P-EQUIPMENT for cooling water."

Actual insert:
    python -m src.use_cases.ai_place_symbol --prompt "Add pump P-101 at 500,250 on layer P-EQUIPMENT for cooling water." --execute

AutoCAD must be open with symbol_test.dwg active.
"""

from __future__ import annotations

import argparse
import sys
import time

from src.ai.symbol_planner import plan_symbol_placement
from src.logging.decorators import log_job
from src.use_cases.place_symbol import connect_to_autocad, insert_symbol


DEFAULT_PROMPT = (
    "Add pump P-101 at coordinates 500, 250 "
    "on layer P-EQUIPMENT for cooling water."
)


@log_job("place_symbol")
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--prompt",
        type=str,
        default=DEFAULT_PROMPT,
        help="Natural language symbol placement instruction.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually insert the symbol. Without this flag, runs dry-run only.",
    )

    args = parser.parse_args()

    user_prompt = args.prompt.strip()
    dry_run = not args.execute

    if not user_prompt:
        print("ERROR: Prompt cannot be empty.")
        sys.exit(1)

    print("User prompt:")
    print(user_prompt)

    print("\nPlanning with AI...")
    try:
        planned_spec = plan_symbol_placement(user_prompt)
    except Exception as e:
        print("ERROR: AI planning failed.")
        print(f"Details: {type(e).__name__}: {e}")
        sys.exit(1)

    print("\nAI planned JSON:")
    print(planned_spec)

    acad, doc = connect_to_autocad()

    print(f"\nConnected to: {acad.Caption}")
    print(f"Active drawing: {doc.Name}")

    print("\nExecuting AutoCAD placement...")
    result = insert_symbol(
        doc=doc,
        spec=planned_spec,
        dry_run=dry_run,
    )

    print("\nResult:")
    print(result)

    if not result.get("ok"):
        print("\nPlacement failed. No symbol inserted.")
        sys.exit(1)

    if dry_run:
        print("\nDry-run complete. No AutoCAD changes made.")
        print("Run again with --execute when ready.")
        return

    if result.get("inserted"):
        acad.ZoomExtents()
        time.sleep(0.3)
        print("\nInserted AI-planned symbol should now be visible in AutoCAD.")


if __name__ == "__main__":
    main()

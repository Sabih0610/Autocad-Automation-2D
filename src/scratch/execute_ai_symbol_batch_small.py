"""
Phase 5.8 controlled batch execution test.

This inserts ONLY 3 AI-planned symbols into AutoCAD and verifies each one.

Important:
- This DOES modify the active AutoCAD drawing.
- Use only with symbol_test.dwg active.
- Each insert must pass readback verification.

Run from project root:
    python -m src.scratch.execute_ai_symbol_batch_small
"""

from __future__ import annotations

import sys
import time
import traceback
from pprint import pprint

from src.ai.symbol_planner import plan_symbol_placement
from src.use_cases.place_symbol import connect_to_autocad, insert_symbol


TEST_PROMPTS = [
    "Place a 6 inch gate valve at 2000, 200 on layer P-VALVES with tag V-2045 for process water.",
    "Add pump P-101 at coordinates 2200, 350 on layer P-EQUIPMENT for cooling water.",
    "Place a control valve CV-900 at 2400, 500 rotated 90 degrees on layer P-CONTROL. Size 8 inch. Service steam.",
]


def run_case(index: int, prompt: str, doc):
    print("\n" + "=" * 80)
    print(f"EXECUTE TEST {index}")
    print("Prompt:")
    print(prompt)

    print("\nPlanning with AI...")
    planned_spec = plan_symbol_placement(prompt)

    print("\nAI planned JSON:")
    pprint(planned_spec)

    print("\nInserting into AutoCAD...")
    result = insert_symbol(
        doc=doc,
        spec=planned_spec,
        dry_run=False,
    )

    print("\nInsert result:")
    pprint(result)

    if not result.get("ok"):
        raise RuntimeError(f"Insert failed: {result}")

    if not result.get("inserted"):
        raise RuntimeError(f"Insert result did not report inserted=True: {result}")

    if not result.get("verified"):
        raise RuntimeError(f"Insert result did not verify successfully: {result}")

    return {
        "prompt": prompt,
        "planned_spec": planned_spec,
        "result": result,
    }


def main():
    acad, doc = connect_to_autocad()

    print(f"Connected to: {acad.Caption}")
    print(f"Active drawing: {doc.Name}")
    print(f"Executing {len(TEST_PROMPTS)} real symbol insertions...")

    passed = 0
    failed = 0
    failures = []

    for index, prompt in enumerate(TEST_PROMPTS, start=1):
        try:
            run_case(index, prompt, doc)
            passed += 1
            print(f"\nEXECUTE TEST {index} PASSED")
            time.sleep(0.3)

        except Exception as e:
            failed += 1
            failures.append(
                {
                    "index": index,
                    "prompt": prompt,
                    "error": f"{type(e).__name__}: {e}",
                }
            )
            print(f"\nEXECUTE TEST {index} FAILED")
            print(f"Error: {type(e).__name__}: {e}")
            traceback.print_exc()

    try:
        doc.Regen(1)
        acad.ZoomExtents()
    except Exception:
        pass

    print("\n" + "=" * 80)
    print("CONTROLLED BATCH EXECUTION SUMMARY")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")

    if failures:
        print("\nFailures:")
        for failure in failures:
            print(f"- Test {failure['index']}: {failure['error']}")
            print(f"  Prompt: {failure['prompt']}")

    if failed == 0:
        print("\nAll 3 controlled insertions passed and verified.")
        print("The inserted symbols should now be visible in AutoCAD.")
    else:
        print("\nSome controlled insertions failed. Do not run full batch yet.")
        sys.exit(1)


if __name__ == "__main__":
    main()
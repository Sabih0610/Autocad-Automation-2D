"""
Phase 5.8 batch symbol prompt test.

This tests many natural language prompts through the full planning
and AutoCAD validation pipeline.

Important:
- This is dry-run only.
- It does NOT insert symbols.
- It does require AutoCAD open with symbol_test.dwg active because
  AutoCAD validation checks whether the block definitions exist.

Run from project root:
    python -m src.scratch.test_ai_symbol_batch
"""

from __future__ import annotations

import traceback

from src.ai.symbol_planner import plan_symbol_placement
from src.use_cases.place_symbol import connect_to_autocad, insert_symbol


TEST_PROMPTS = [
    "Place a 6 inch gate valve at 100, 200 on layer P-VALVES with tag V-2045 for process water.",
    "Add pump P-101 at coordinates 500, 250 on layer P-EQUIPMENT for cooling water.",
    "Put a check valve tagged CV-300 at x 700 y 125 on layer P-VALVES. Size is 4 inch.",
    "Add instrument bubble LT-101 at 300, 900 on layer P-INSTRUMENTS.",
    "Place a control valve CV-900 at 1200, 450 rotated 90 degrees on layer P-CONTROL. Size 8 inch. Service steam.",
    "Insert vessel V-101 at 1500, 600 on layer P-VESSELS for separator service.",
    "Add a 3 inch check valve at 250, 850 on layer P-VALVES with tag CV-222 for condensate.",
    "Place gate valve V-777 at coordinates 900, 300 on layer P-VALVES. Size 10 inch. Service crude oil.",
    "Put pump P-202 at x 1100 y 700 on layer P-EQUIPMENT.",
    "Add instrument bubble PT-404 at 450, 650 on layer P-INSTRUMENTS for pressure indication.",
    "Place a control valve tagged FCV-101 at 1300, 800 on layer P-CONTROL. Size 2 inch. Service fuel gas.",
    "Add vessel T-301 at coordinates 1700, 950 on layer P-VESSELS.",
]


def run_case(index: int, prompt: str, doc):
    print("\n" + "=" * 80)
    print(f"TEST {index}")
    print("Prompt:")
    print(prompt)

    planned_spec = plan_symbol_placement(prompt)

    print("\nAI planned JSON:")
    print(planned_spec)

    result = insert_symbol(
        doc=doc,
        spec=planned_spec,
        dry_run=True,
    )

    print("\nDry-run validation result:")
    print(result)

    if not result.get("ok"):
        raise RuntimeError(f"Dry-run failed: {result}")

    return {
        "prompt": prompt,
        "planned_spec": planned_spec,
        "result": result,
    }


def main():
    acad, doc = connect_to_autocad()

    print(f"Connected to: {acad.Caption}")
    print(f"Active drawing: {doc.Name}")
    print(f"Running {len(TEST_PROMPTS)} dry-run prompt tests...")

    passed = 0
    failed = 0
    failures = []

    for index, prompt in enumerate(TEST_PROMPTS, start=1):
        try:
            run_case(index, prompt, doc)
            passed += 1
            print(f"\nTEST {index} PASSED")
        except Exception as e:
            failed += 1
            failures.append(
                {
                    "index": index,
                    "prompt": prompt,
                    "error": f"{type(e).__name__}: {e}",
                }
            )
            print(f"\nTEST {index} FAILED")
            print(f"Error: {type(e).__name__}: {e}")
            traceback.print_exc()

    print("\n" + "=" * 80)
    print("BATCH TEST SUMMARY")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")

    if failures:
        print("\nFailures:")
        for failure in failures:
            print(f"- Test {failure['index']}: {failure['error']}")
            print(f"  Prompt: {failure['prompt']}")

    if failed == 0:
        print("\nAll batch dry-run tests passed.")
    else:
        print("\nSome tests failed. We need to fix those before executing more symbols.")


if __name__ == "__main__":
    main()
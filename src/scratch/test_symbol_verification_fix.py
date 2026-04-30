"""
Targeted verification fix test.

This tests the exact failure types from the full batch:
1. Gate valve handle readback issue
2. Vessel layer/insertion_point readback issue

This DOES insert 3 new symbols into AutoCAD.
"""

from __future__ import annotations

import sys
import traceback
from pprint import pprint

from src.ai.symbol_planner import plan_symbol_placement
from src.use_cases.place_symbol import connect_to_autocad, insert_symbol


TEST_PROMPTS = [
    "Place a 6 inch gate valve at 4300, 200 on layer P-VALVES with tag V-2045 for process water.",
    "Insert vessel V-101 at 4300, 400 on layer P-VESSELS for separator service.",
    "Add vessel T-301 at coordinates 4300, 650 on layer P-VESSELS.",
]


def run_case(index: int, prompt: str, doc):
    print("\n" + "=" * 80)
    print(f"TARGETED TEST {index}")
    print("Prompt:")
    print(prompt)

    planned_spec = plan_symbol_placement(prompt)

    print("\nAI planned JSON:")
    pprint(planned_spec)

    result = insert_symbol(
        doc=doc,
        spec=planned_spec,
        dry_run=False,
    )

    print("\nInsert result:")
    pprint(result)

    if not result.get("ok"):
        raise RuntimeError(f"Insert failed: {result}")

    if not result.get("verified"):
        raise RuntimeError(f"Verification failed: {result}")

    return result


def main():
    acad, doc = connect_to_autocad()

    print(f"Connected to: {acad.Caption}")
    print(f"Active drawing: {doc.Name}")
    print("Running targeted verification fix tests...")

    passed = 0
    failed = 0

    for index, prompt in enumerate(TEST_PROMPTS, start=1):
        try:
            run_case(index, prompt, doc)
            passed += 1
            print(f"\nTARGETED TEST {index} PASSED")
        except Exception as e:
            failed += 1
            print(f"\nTARGETED TEST {index} FAILED")
            print(f"Error: {type(e).__name__}: {e}")
            traceback.print_exc()

    try:
        doc.Regen(1)
        acad.ZoomExtents()
    except Exception:
        pass

    print("\n" + "=" * 80)
    print("TARGETED VERIFICATION FIX SUMMARY")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")

    if failed:
        print("\nStill failing. Do not rerun the full batch yet.")
        sys.exit(1)

    print("\nVerification fix passed. Next step will be rerunning full batch safely.")


if __name__ == "__main__":
    main()
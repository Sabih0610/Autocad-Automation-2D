"""
Test AI explanation for Phase 6 consistency mismatches.

This does NOT touch AutoCAD.
It uses the 2 deliberate mismatches we just confirmed.
"""

from pprint import pprint

from src.ai.consistency_explainer import explain_consistency_mismatches


TEST_MISMATCHES = [
    {
        "type": "FIELD_MISMATCH",
        "line_no": "4B-150-CS1",
        "field": "SERVICE",
        "pid_value": "PROCESS WATER",
        "excel_value": "WRONG SERVICE",
        "details": "SERVICE differs between P&ID and Excel.",
    },
    {
        "type": "FIELD_MISMATCH",
        "line_no": "4B-200-CS1",
        "field": "SIZE",
        "pid_value": '8"',
        "excel_value": "999 inch",
        "details": "SIZE differs between P&ID and Excel.",
    },
]


def main():
    result = explain_consistency_mismatches(TEST_MISMATCHES)

    print("AI consistency explanation:")
    pprint(result)


if __name__ == "__main__":
    main()
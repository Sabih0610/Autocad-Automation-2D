"""
Final Phase 4 symbol planner test.

This does NOT touch AutoCAD.

It tests the reusable src.ai.symbol_planner module that Phase 5 will use.
"""

from src.ai.symbol_planner import plan_symbol_placement


def run_case(prompt: str):
    print("\nUSER PROMPT:")
    print(prompt)

    result = plan_symbol_placement(prompt)

    print("\nPLANNED SYMBOL JSON:")
    print(result)


def main():
    test_prompts = [
        "Place a 6 inch gate valve at 100, 200 on layer P-VALVES with tag V-2045 for process water.",
        "Add pump P-101 at coordinates 500, 250 on layer P-EQUIPMENT for cooling water.",
        "Put a check valve tagged CV-300 at x 700 y 125 on layer P-VALVES. Size is 4 inch.",
        "Add instrument bubble LT-101 at 300, 900 on layer P-INSTRUMENTS.",
        "Place a control valve CV-900 at 1200, 450 rotated 90 degrees on layer P-CONTROL. Size 8 inch. Service steam.",
    ]

    for prompt in test_prompts:
        run_case(prompt)


if __name__ == "__main__":
    main()
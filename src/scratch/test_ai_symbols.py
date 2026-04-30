"""
Phase 4 symbol-planning test.

This does NOT touch AutoCAD.

Goal:
- Test that ask_ai() can convert natural language into a stricter
  symbol placement JSON structure.
- Enforce non-empty required values.
- Use UNKNOWN when the user does not provide size/service.
"""

from src.ai.client import ask_ai


NON_EMPTY_STRING = {
    "type": "string",
    "minLength": 1,
}


SYMBOL_PLACEMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "task_type": {
            "type": "string",
            "enum": ["place_symbol"],
        },
        "block_name": {
            "type": "string",
            "enum": [
                "GATE_VALVE",
                "CHECK_VALVE",
                "CONTROL_VALVE",
                "PUMP",
                "VESSEL",
                "INSTRUMENT_BUBBLE",
            ],
        },
        "insertion_point": {
            "type": "object",
            "properties": {
                "x": {"type": "number"},
                "y": {"type": "number"},
                "z": {"type": "number"},
            },
            "required": ["x", "y", "z"],
            "additionalProperties": False,
        },
        "rotation_degrees": {"type": "number"},
        "scale": {"type": "number"},
        "layer": NON_EMPTY_STRING,
        "attributes": {
            "type": "object",
            "properties": {
                "TAG": NON_EMPTY_STRING,
                "SIZE": NON_EMPTY_STRING,
                "SERVICE": NON_EMPTY_STRING,
            },
            "required": ["TAG", "SIZE", "SERVICE"],
            "additionalProperties": False,
        },
    },
    "required": [
        "task_type",
        "block_name",
        "insertion_point",
        "rotation_degrees",
        "scale",
        "layer",
        "attributes",
    ],
    "additionalProperties": False,
}


SYSTEM_PROMPT = """
You are converting drafting instructions into AutoCAD symbol placement JSON.

Use these exact block mappings:
- gate valve = GATE_VALVE
- check valve = CHECK_VALVE
- control valve = CONTROL_VALVE
- pump = PUMP
- vessel = VESSEL
- instrument bubble = INSTRUMENT_BUBBLE

Rules:
- task_type must always be place_symbol.
- z must always be 0 unless the user gives a z coordinate.
- rotation_degrees must be 0 unless the user gives a rotation.
- scale must be 1 unless the user gives a scale.
- Preserve layer names exactly as written by the user.
- Put tag, size, and service inside attributes.
- If size is not mentioned, use "UNKNOWN".
- If service is not mentioned, use "UNKNOWN".
- Never return empty strings.
- Never add fields that are not in the schema.
"""


def run_case(prompt: str):
    print("\nUSER PROMPT:")
    print(prompt)

    result = ask_ai(
        prompt=prompt,
        schema=SYMBOL_PLACEMENT_SCHEMA,
        system_prompt=SYSTEM_PROMPT,
    )

    print("\nVALID JSON RESULT:")
    print(result)


def main():
    test_prompts = [
        "Place a 6 inch gate valve at 100, 200 on layer P-VALVES with tag V-2045 for process water.",
        "Add pump P-101 at coordinates 500, 250 on layer P-EQUIPMENT for cooling water.",
        "Put a check valve tagged CV-300 at x 700 y 125 on layer P-VALVES. Size is 4 inch.",
        "Add instrument bubble LT-101 at 300, 900 on layer P-INSTRUMENTS.",
    ]

    for prompt in test_prompts:
        run_case(prompt)


if __name__ == "__main__":
    main()
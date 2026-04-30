"""
Phase 4 isolated AI test.

This test does NOT touch AutoCAD.
It only checks:

1. .env loads correctly
2. DeepSeek API key works
3. ask_ai() returns valid JSON
4. JSON matches our schema
"""

from src.ai.client import ask_ai


SYMBOL_SCHEMA = {
    "type": "object",
    "properties": {
        "block": {"type": "string"},
        "x": {"type": "number"},
        "y": {"type": "number"},
        "size": {"type": "string"},
        "layer": {"type": "string"},
        "tag": {"type": "string"},
    },
    "required": ["block", "x", "y", "size", "layer", "tag"],
    "additionalProperties": False,
}


def main():
    prompt = (
        "Add a 6-inch gate valve at coordinates 100, 200 "
        "on layer P-VALVES with tag V-2045."
    )

    result = ask_ai(
        prompt=prompt,
        schema=SYMBOL_SCHEMA,
    )

    print("AI returned valid JSON:")
    print(result)


if __name__ == "__main__":
    main()
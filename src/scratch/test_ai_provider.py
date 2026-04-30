"""
Phase 4 provider-wrapper sanity check.

This does NOT touch AutoCAD.

Goal:
- Confirm AI_PROVIDER is read from .env.
- Confirm the ask_ai() wrapper still works through the provider switch.
- This is the final check before Phase 5.
"""

import os

from dotenv import load_dotenv

from src.ai.client import ask_ai


TEST_SCHEMA = {
    "type": "object",
    "properties": {
        "provider_test": {"type": "string", "minLength": 1},
        "status": {"type": "string", "enum": ["ok"]},
    },
    "required": ["provider_test", "status"],
    "additionalProperties": False,
}


def main():
    load_dotenv()

    provider = os.getenv("AI_PROVIDER", "").strip()
    print(f"AI_PROVIDER from .env: {provider}")

    result = ask_ai(
        prompt="Return JSON saying the provider wrapper test is successful.",
        schema=TEST_SCHEMA,
    )

    print("Provider wrapper returned valid JSON:")
    print(result)


if __name__ == "__main__":
    main()
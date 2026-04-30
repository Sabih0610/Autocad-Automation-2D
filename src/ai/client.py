"""
Provider-agnostic AI client.

Phase 4 goal:
- Test AI in isolation.
- Return schema-validated JSON.
- Do NOT touch AutoCAD here.

Current provider:
- deepseek via OpenAI-compatible API

Future providers:
- openai
- anthropic
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from jsonschema import Draft7Validator, ValidationError
from openai import OpenAI


class AIConfigError(Exception):
    """Raised when AI provider config is missing or invalid."""


class AIResponseError(Exception):
    """Raised when the AI response is invalid or cannot be validated."""


def _load_env() -> None:
    """Load .env from project root."""
    load_dotenv()


def _get_provider() -> str:
    """Return configured AI provider."""
    provider = os.getenv("AI_PROVIDER", "").strip().lower()

    if not provider:
        raise AIConfigError("AI_PROVIDER is missing in .env")

    return provider


def _get_deepseek_client() -> OpenAI:
    """Create OpenAI-compatible client for DeepSeek."""
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()

    if not api_key:
        raise AIConfigError("DEEPSEEK_API_KEY is missing in .env")

    return OpenAI(
        api_key=api_key,
        base_url=base_url,
    )


def _validate_schema(schema: Dict[str, Any]) -> None:
    """Validate that the provided JSON schema itself is valid enough to use."""
    if not isinstance(schema, dict):
        raise AIConfigError("schema must be a dictionary")

    if schema.get("type") != "object":
        raise AIConfigError("schema must be a JSON object schema with type='object'")

    Draft7Validator.check_schema(schema)


def _validate_response(data: Dict[str, Any], schema: Dict[str, Any]) -> None:
    """Validate AI JSON response against the provided schema."""
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: e.path)

    if errors:
        first_error = errors[0]
        path = ".".join(str(p) for p in first_error.path) or "root"
        raise ValidationError(f"{path}: {first_error.message}")


def _extract_json(content: str) -> Dict[str, Any]:
    """Parse model response content as JSON."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise AIResponseError(f"AI returned invalid JSON: {e}")

    if not isinstance(data, dict):
        raise AIResponseError("AI JSON response must be an object/dictionary")

    return data


def _build_system_prompt(schema: Dict[str, Any], extra_system_prompt: Optional[str]) -> str:
    """Build system prompt that forces JSON-only behavior."""
    schema_text = json.dumps(schema, indent=2)

    base_prompt = f"""
You are an AI planner for an AutoCAD automation system.

Your job is to convert user instructions into valid JSON only.

Rules:
- Return JSON only.
- Do not include markdown.
- Do not include explanation text.
- Do not include comments.
- The JSON must match this schema exactly.
- Do not invent fields that are not in the schema.
- If a value is unknown, use null only if the schema allows it.

JSON schema:
{schema_text}
""".strip()

    if extra_system_prompt:
        return base_prompt + "\n\nExtra rules:\n" + extra_system_prompt.strip()

    return base_prompt


def _resolve_max_tokens(max_tokens: int | None) -> int:
    if max_tokens is None:
        return 800

    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens <= 0:
        raise ValueError("max_tokens must be a positive integer")

    return max_tokens


def _ask_deepseek(
    prompt: str,
    schema: Dict[str, Any],
    system_prompt: Optional[str] = None,
    max_retries: int = 1,
    max_tokens: int | None = None,
) -> Dict[str, Any]:
    """
    Ask DeepSeek and return validated JSON.

    Retries once by default if:
    - JSON parsing fails
    - schema validation fails
    """
    client = _get_deepseek_client()
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()
    resolved_max_tokens = _resolve_max_tokens(max_tokens)

    messages = [
        {
            "role": "system",
            "content": _build_system_prompt(schema, system_prompt),
        },
        {
            "role": "user",
            "content": f"Return valid JSON for this request:\n{prompt}",
        },
    ]

    last_error: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=resolved_max_tokens,
            )

            content = response.choices[0].message.content

            if not content:
                raise AIResponseError("AI returned empty content")

            data = _extract_json(content)
            _validate_response(data, schema)
            return data

        except Exception as e:
            last_error = e

            if attempt >= max_retries:
                break

            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous response failed validation. "
                        f"Exact error: {type(e).__name__}: {e}. "
                        "Return one complete valid JSON object only. "
                        "Do not include markdown, comments, or prose. "
                        "If the JSON would be too long, shorten arrays or text "
                        "values while preserving the required schema."
                    ),
                }
            )

    raise AIResponseError(f"AI failed after retry. Last error: {last_error}")


def ask_ai(
    prompt: str,
    schema: Dict[str, Any],
    system_prompt: Optional[str] = None,
    max_retries: int = 1,
    max_tokens: int | None = None,
) -> Dict[str, Any]:
    """
    Provider-agnostic AI entry point.

    Usage:
        result = ask_ai(prompt, schema)

    Returns:
        dict matching the given JSON schema
    """
    _load_env()
    _validate_schema(schema)
    _resolve_max_tokens(max_tokens)

    provider = _get_provider()

    if provider == "deepseek":
        return _ask_deepseek(
            prompt=prompt,
            schema=schema,
            system_prompt=system_prompt,
            max_retries=max_retries,
            max_tokens=max_tokens,
        )

    raise AIConfigError(
        f"Unsupported AI_PROVIDER='{provider}'. "
        "Currently supported: deepseek"
    )

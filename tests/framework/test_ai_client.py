from __future__ import annotations

import pytest

from src.ai import client as ai_client


_SCHEMA = {
    "type": "object",
    "properties": {},
    "additionalProperties": True,
}


def test_ask_ai_passes_max_tokens_to_provider(monkeypatch) -> None:
    captured = {}

    monkeypatch.setattr(ai_client, "_load_env", lambda: None)
    monkeypatch.setattr(ai_client, "_get_provider", lambda: "deepseek")

    def fake_ask_deepseek(
        prompt,
        schema,
        system_prompt=None,
        max_retries=1,
        max_tokens=None,
    ):
        captured["prompt"] = prompt
        captured["schema"] = schema
        captured["system_prompt"] = system_prompt
        captured["max_retries"] = max_retries
        captured["max_tokens"] = max_tokens
        return {"ok": True}

    monkeypatch.setattr(ai_client, "_ask_deepseek", fake_ask_deepseek)

    result = ai_client.ask_ai(
        prompt="test",
        schema=_SCHEMA,
        system_prompt="system",
        max_retries=2,
        max_tokens=1234,
    )

    assert result == {"ok": True}
    assert captured["prompt"] == "test"
    assert captured["schema"] == _SCHEMA
    assert captured["system_prompt"] == "system"
    assert captured["max_retries"] == 2
    assert captured["max_tokens"] == 1234


@pytest.mark.parametrize("max_tokens", [0, -1, 1.5, True, "100"])
def test_ask_ai_invalid_max_tokens_raises_value_error(monkeypatch, max_tokens) -> None:
    monkeypatch.setattr(ai_client, "_load_env", lambda: None)

    with pytest.raises(ValueError, match="max_tokens must be a positive integer"):
        ai_client.ask_ai(
            prompt="test",
            schema=_SCHEMA,
            max_tokens=max_tokens,
        )

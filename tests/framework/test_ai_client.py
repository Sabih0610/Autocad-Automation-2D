from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.ai import client as ai_client


_SCHEMA = {
    "type": "object",
    "properties": {},
    "additionalProperties": True,
}


def _stub_deepseek_provider(
    monkeypatch,
    *,
    content: str = "{}",
    finish_reason: str = "stop",
) -> list[dict]:
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason=finish_reason,
                    message=SimpleNamespace(content=content),
                )
            ]
        )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=create),
        )
    )
    monkeypatch.setattr(ai_client, "_get_deepseek_client", lambda: fake_client)
    return calls


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


def test_deepseek_length_finish_reason_reports_truncation(monkeypatch) -> None:
    calls = _stub_deepseek_provider(
        monkeypatch,
        content='{"unfinished":',
        finish_reason="length",
    )

    with pytest.raises(ai_client.AIResponseTruncatedError) as exc_info:
        ai_client._ask_deepseek("test", _SCHEMA, max_retries=1)

    message = str(exc_info.value)
    assert "truncated" in message
    assert "smaller request" in message
    assert "invalid JSON" not in message
    assert len(calls) == 1


def test_deepseek_uses_larger_default_max_tokens(monkeypatch) -> None:
    calls = _stub_deepseek_provider(monkeypatch)

    assert ai_client._ask_deepseek("test", _SCHEMA, max_retries=0) == {}
    assert calls[0]["max_tokens"] == 4000


def test_deepseek_explicit_max_tokens_overrides_default(monkeypatch) -> None:
    calls = _stub_deepseek_provider(monkeypatch)

    assert ai_client._ask_deepseek(
        "test",
        _SCHEMA,
        max_retries=0,
        max_tokens=1234,
    ) == {}
    assert calls[0]["max_tokens"] == 1234


@pytest.mark.parametrize(
    "content",
    [
        '{"value": NaN}',
        '{"value": Infinity}',
        '{"value": -Infinity}',
    ],
)
def test_extract_json_rejects_non_finite_number_literals(content: str) -> None:
    with pytest.raises(ai_client.AIResponseError, match="non-finite number literal"):
        ai_client._extract_json(content)

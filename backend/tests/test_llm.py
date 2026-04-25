"""Tests for the LLM client wrapper.

These never hit the real OpenRouter API. The live integration is exercised
manually with a real key set; routine CI just ensures the module's
boundaries (auth check, error wrapping) behave.
"""

from __future__ import annotations

import json

import pytest

from app import llm


def test_chat_complete_raises_when_api_key_missing(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(llm.LLMUnavailableError, match="OPENROUTER_API_KEY"):
        llm.chat_complete(
            messages=[{"role": "user", "content": "hi"}],
            mnda_state={},
        )


def test_chat_complete_wraps_litellm_failure(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    def boom(**_kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(llm.litellm, "completion", boom)

    with pytest.raises(llm.LLMUnavailableError, match="network down"):
        llm.chat_complete(
            messages=[{"role": "user", "content": "hi"}],
            mnda_state={},
        )


def test_chat_complete_parses_structured_response(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    payload = {
        "assistant_message": "What's the effective date?",
        "mnda_updates": {"purpose": "Evaluating a deal"},
        "done": False,
    }

    class FakeMessage:
        content = json.dumps(payload)

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    captured: dict = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(llm.litellm, "completion", fake_completion)

    result = llm.chat_complete(
        messages=[{"role": "user", "content": "I need an NDA with Acme."}],
        mnda_state={"purpose": ""},
    )
    assert result == payload

    # Sanity-check the routing constraints we actually care about.
    assert captured["model"] == "openrouter/openai/gpt-oss-120b"
    assert captured["extra_body"]["provider"] == {
        "order": ["cerebras"],
        "allow_fallbacks": False,
    }
    assert captured["response_format"]["type"] == "json_schema"
    # System prompt should embed the current MNDA state for grounding.
    system = captured["messages"][0]
    assert system["role"] == "system"
    assert '"purpose"' in system["content"]

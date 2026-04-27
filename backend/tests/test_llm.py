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


def _fake_response(payload: dict) -> object:
    """Build the minimum object shape `chat_complete` reads from a litellm response."""

    class FakeMessage:
        content = json.dumps(payload)

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    return FakeResponse()


def test_chat_complete_parses_structured_response(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    payload = {
        "assistant_message": "What's the effective date?",
        "mnda_updates": {"purpose": "Evaluating a deal"},
        "done": False,
    }

    captured: dict = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return _fake_response(payload)

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


def test_system_prompt_embeds_full_catalog(monkeypatch):
    """The catalog must be inlined so the LLM can route across all 11 doc types."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    captured: dict = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return _fake_response(
            {"assistant_message": "What kind of agreement?", "mnda_updates": {}, "done": False},
        )

    monkeypatch.setattr(llm.litellm, "completion", fake_completion)

    llm.chat_complete(
        messages=[{"role": "user", "content": "hi"}],
        mnda_state={},
    )

    system = captured["messages"][0]["content"]
    # A representative sample of catalog ids — if the catalog injection ever
    # regresses, these IDs disappear together.
    assert "mutual-nda" in system
    assert "cloud-service-agreement" in system
    assert "business-associate-agreement" in system


def test_chat_complete_retries_when_followup_question_missing(monkeypatch):
    """If done=False and the message has no '?', retry once with a corrective nudge."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    bad = {
        "assistant_message": "Got it. I'll keep that in mind.",
        "mnda_updates": {},
        "done": False,
    }
    good = {
        "assistant_message": "Thanks. What's the effective date?",
        "mnda_updates": {},
        "done": False,
    }
    responses = iter([_fake_response(bad), _fake_response(good)])
    calls: list[dict] = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return next(responses)

    monkeypatch.setattr(llm.litellm, "completion", fake_completion)

    result = llm.chat_complete(
        messages=[{"role": "user", "content": "We're partnering with Acme."}],
        mnda_state={},
    )

    assert result == good
    assert len(calls) == 2
    # The retry's system prompt should explicitly call out the rule violation.
    retry_system = calls[1]["messages"][0]["content"]
    assert "did not end with a question" in retry_system


def test_chat_complete_preserves_first_call_updates_across_retry(monkeypatch):
    """A retry triggered by missing question should not drop fields the first call extracted."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    bad = {
        "assistant_message": "Got it.",
        "mnda_updates": {"purpose": "Evaluating a partnership"},
        "done": False,
    }
    good = {
        "assistant_message": "Thanks. What's the effective date?",
        "mnda_updates": {"governingLaw": "Delaware"},
        "done": False,
    }
    responses = iter([_fake_response(bad), _fake_response(good)])
    monkeypatch.setattr(llm.litellm, "completion", lambda **_kw: next(responses))

    result = llm.chat_complete(
        messages=[{"role": "user", "content": "Acme partnership."}],
        mnda_state={},
    )

    # Both turns' extractions must survive — the retry only existed to fix
    # phrasing, not to re-discover data.
    assert result["mnda_updates"] == {
        "purpose": "Evaluating a partnership",
        "governingLaw": "Delaware",
    }


def test_chat_complete_appends_followup_when_retry_also_fails(monkeypatch):
    """Last-resort fallback: append a generic question so the user always has something to answer."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    bad1 = {"assistant_message": "Got it.", "mnda_updates": {}, "done": False}
    bad2 = {"assistant_message": "Understood.", "mnda_updates": {}, "done": False}
    responses = iter([_fake_response(bad1), _fake_response(bad2)])
    monkeypatch.setattr(llm.litellm, "completion", lambda **_kw: next(responses))

    result = llm.chat_complete(
        messages=[{"role": "user", "content": "ok"}],
        mnda_state={},
    )

    assert result["assistant_message"].startswith("Understood.")
    assert result["assistant_message"].rstrip()[-1] in ("?", "？")


def test_chat_complete_skips_followup_check_when_done(monkeypatch):
    """A finishing message ending with '.' is fine — only !done turns require a question."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    payload = {
        "assistant_message": "All set — your MNDA is ready to download.",
        "mnda_updates": {},
        "done": True,
    }
    calls: list[dict] = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return _fake_response(payload)

    monkeypatch.setattr(llm.litellm, "completion", fake_completion)

    result = llm.chat_complete(
        messages=[{"role": "user", "content": "looks good"}],
        mnda_state={},
    )
    assert result == payload
    assert len(calls) == 1  # no retry


def test_chat_complete_chinese_fallback_when_message_is_chinese(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    bad_zh = {"assistant_message": "好的，我知道了。", "mnda_updates": {}, "done": False}
    responses = iter([_fake_response(bad_zh), _fake_response(bad_zh)])
    monkeypatch.setattr(llm.litellm, "completion", lambda **_kw: next(responses))

    result = llm.chat_complete(
        messages=[{"role": "user", "content": "我们要和 Acme 合作。"}],
        mnda_state={},
    )
    assert result["assistant_message"].endswith("？")

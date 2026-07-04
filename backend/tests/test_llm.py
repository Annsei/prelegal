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


def test_chat_complete_wraps_litellm_failure_with_friendly_message(monkeypatch):
    """Generic transport failures get a short message, not the raw exception."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    def boom(**_kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(llm.litellm, "completion", boom)

    with pytest.raises(llm.LLMUnavailableError) as info:
        llm.chat_complete(
            messages=[{"role": "user", "content": "hi"}],
            mnda_state={},
        )
    # The classifier hides the raw "network down" detail behind a
    # short, user-actionable sentence.
    assert "network down" not in str(info.value)
    assert "AI service" in str(info.value)


def test_chat_complete_classifies_rate_limit(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    class RateLimitError(Exception):
        pass

    def boom(**_kwargs):
        raise RateLimitError(
            'OpenrouterException - '
            '{"error":{"code":429,"message":"rate-limited upstream"}}',
        )

    monkeypatch.setattr(llm.litellm, "completion", boom)

    with pytest.raises(llm.LLMUnavailableError) as info:
        llm.chat_complete(
            messages=[{"role": "user", "content": "hi"}],
            mnda_state={},
        )
    assert "rate-limited" in str(info.value).lower()
    # No raw exception payload leaks into the user-facing message.
    assert "OpenrouterException" not in str(info.value)


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
    # Normalization fills in the optional keys the model omitted.
    assert result == {**payload, "selected_doc_id": "", "field_updates": {}}

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
            {
                "assistant_message": "What kind of agreement?",
                "mnda_updates": {},
                "done": False,
            },
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

    # Spot-check the post-merge shape rather than full equality — the merge
    # adds field_updates={} which was absent from the per-call payloads.
    assert result["assistant_message"] == good["assistant_message"]
    assert result["done"] is False
    assert result["mnda_updates"] == {}
    assert result["field_updates"] == {}
    assert len(calls) == 2
    # The retry's system prompt should explicitly call out the rule violation.
    retry_system = calls[1]["messages"][0]["content"]
    assert "did not end with a question" in retry_system


def test_chat_complete_preserves_first_call_updates_across_retry(monkeypatch):
    """A retry triggered by a missing question must not drop fields the
    first call extracted."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    bad = {
        "assistant_message": "Got it.",
        "selected_doc_id": "mutual-nda",
        "mnda_updates": {"purpose": "Evaluating a partnership"},
        "field_updates": {"Customer": "Acme"},
        "done": False,
    }
    good = {
        "assistant_message": "Thanks. What's the effective date?",
        # Retry leaves selected_doc_id blank — must inherit from first call.
        "mnda_updates": {"governingLaw": "Delaware"},
        "field_updates": {"Provider": "Globex"},
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
    assert result["field_updates"] == {"Customer": "Acme", "Provider": "Globex"}
    assert result["selected_doc_id"] == "mutual-nda"


def test_chat_response_schema_has_multi_doc_fields():
    """selected_doc_id and field_updates must be in the JSON schema we send."""
    props = llm.CHAT_RESPONSE_SCHEMA["properties"]
    assert "selected_doc_id" in props
    assert "field_updates" in props
    assert props["field_updates"]["additionalProperties"] == {"type": "string"}


def test_chat_complete_appends_followup_when_retry_also_fails(monkeypatch):
    """Last-resort fallback: append a generic question so the user always
    has something to answer."""
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
    """A finishing message ending with '.' is fine — only !done turns
    require a question."""
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
    assert result == {**payload, "selected_doc_id": "", "field_updates": {}}
    assert len(calls) == 1  # no retry


def test_chat_complete_rejects_response_missing_assistant_message(monkeypatch):
    """Non-strict structured outputs can omit keys — that must surface as a
    classified LLMUnavailableError (502), never a KeyError-driven raw 500."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    payload = {"mnda_updates": {"purpose": "Evaluating"}, "done": False}
    monkeypatch.setattr(
        llm.litellm, "completion", lambda **_kw: _fake_response(payload),
    )

    with pytest.raises(llm.LLMUnavailableError, match="incomplete reply"):
        llm.chat_complete(
            messages=[{"role": "user", "content": "hi"}],
            mnda_state={},
        )


def test_chat_complete_rejects_non_object_json(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    class FakeMessage:
        content = json.dumps(["not", "an", "object"])

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    monkeypatch.setattr(llm.litellm, "completion", lambda **_kw: FakeResponse())

    with pytest.raises(llm.LLMUnavailableError, match="unparseable"):
        llm.chat_complete(
            messages=[{"role": "user", "content": "hi"}],
            mnda_state={},
        )


def test_chat_complete_coerces_non_string_field_values(monkeypatch):
    """The model sometimes returns numbers/booleans for field values; they
    must be stringified so the route's dict[str, str] response validates."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    payload = {
        "assistant_message": "Noted. What else?",
        "selected_doc_id": "cloud-service-agreement",
        "mnda_updates": {},
        "field_updates": {"Subscription Period": 12, "Auto Renew": True},
        "done": False,
    }
    monkeypatch.setattr(
        llm.litellm, "completion", lambda **_kw: _fake_response(payload),
    )

    result = llm.chat_complete(
        messages=[{"role": "user", "content": "12 months, auto-renew"}],
        mnda_state={},
    )
    assert result["field_updates"] == {
        "Subscription Period": "12",
        "Auto Renew": "true",
    }


def test_chat_complete_chinese_fallback_when_message_is_chinese(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    bad_zh = {
        "assistant_message": "好的，我知道了。",
        "mnda_updates": {},
        "done": False,
    }
    responses = iter([_fake_response(bad_zh), _fake_response(bad_zh)])
    monkeypatch.setattr(llm.litellm, "completion", lambda **_kw: next(responses))

    result = llm.chat_complete(
        messages=[{"role": "user", "content": "我们要和 Acme 合作。"}],
        mnda_state={},
    )
    assert result["assistant_message"].endswith("？")


def test_chat_complete_injects_manifest_checklist_for_csa(monkeypatch):
    """When the open doc has a manifest, the prompt gains its field
    checklist and the schema pins field_updates to exactly those keys."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    captured: dict = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return _fake_response(
            {
                "assistant_message": "Who is the provider?",
                "mnda_updates": {},
                "done": False,
            },
        )

    monkeypatch.setattr(llm.litellm, "completion", fake_completion)

    llm.chat_complete(
        messages=[{"role": "user", "content": "12 month subscription"}],
        mnda_state={},
        doc_id="cloud-service-agreement",
    )

    system = captured["messages"][0]["content"]
    assert "## Field checklist" in system
    assert '"General Cap Amount" (required)' in system
    assert '"Technical Support" (optional)' in system

    field_schema = captured["response_format"]["json_schema"]["schema"][
        "properties"
    ]["field_updates"]
    assert field_schema["additionalProperties"] is False
    assert "Subscription Period" in field_schema["properties"]
    assert "Provider Covered Claims" in field_schema["properties"]


def test_chat_complete_keeps_freeform_schema_without_manifest(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    captured: dict = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return _fake_response(
            {
                "assistant_message": "Which document?",
                "mnda_updates": {},
                "done": False,
            },
        )

    monkeypatch.setattr(llm.litellm, "completion", fake_completion)

    llm.chat_complete(
        messages=[{"role": "user", "content": "hi"}],
        mnda_state={},
        doc_id="pilot-agreement",  # no manifest yet
    )

    system = captured["messages"][0]["content"]
    assert "## Field checklist" not in system
    field_schema = captured["response_format"]["json_schema"]["schema"][
        "properties"
    ]["field_updates"]
    assert field_schema["additionalProperties"] == {"type": "string"}

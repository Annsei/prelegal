"""Tests for /api/chat with the LLM call mocked.

We never make a real network call here. The chat route is a thin wrapper
around `app.llm.chat_complete`, so we patch that function and check:
  - happy path: response is shaped correctly,
  - last-message-must-be-user validation,
  - LLM failures surface as 502, not 500.
"""

from __future__ import annotations

import pytest

from app import llm
from app.routes import chat as chat_route


@pytest.fixture
def chat_client(client, monkeypatch):
    captured: dict = {}

    def fake_chat_complete(messages, mnda_state):
        captured["messages"] = messages
        captured["mnda_state"] = mnda_state
        return {
            "assistant_message": "Got it — what's the effective date?",
            "mnda_updates": {"purpose": "Evaluating a partnership"},
            "done": False,
        }

    monkeypatch.setattr(chat_route, "chat_complete", fake_chat_complete)
    client.captured = captured
    return client


def test_chat_returns_assistant_message_and_updates(chat_client):
    res = chat_client.post(
        "/api/chat",
        json={
            "messages": [
                {"role": "user", "content": "Hi, I need an MNDA with Acme."},
            ],
            "mnda_state": {"purpose": ""},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["assistant_message"].startswith("Got it")
    assert body["mnda_updates"]["purpose"] == "Evaluating a partnership"
    assert body["done"] is False

    # The route should have forwarded both history and state to the LLM layer.
    assert chat_client.captured["mnda_state"] == {"purpose": ""}
    assert chat_client.captured["messages"][0]["role"] == "user"


def test_chat_rejects_when_last_message_is_assistant(chat_client):
    res = chat_client.post(
        "/api/chat",
        json={
            "messages": [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Sure, what's the purpose?"},
            ],
            "mnda_state": {},
        },
    )
    assert res.status_code == 400
    assert "last message must be from the user" in res.json()["detail"]


def test_chat_rejects_empty_history(chat_client):
    res = chat_client.post("/api/chat", json={"messages": [], "mnda_state": {}})
    assert res.status_code == 422  # pydantic min_length=1


def test_chat_returns_502_when_llm_unavailable(client, monkeypatch):
    def boom(messages, mnda_state):
        raise llm.LLMUnavailableError("OPENROUTER_API_KEY is not set.")

    monkeypatch.setattr(chat_route, "chat_complete", boom)

    res = client.post(
        "/api/chat",
        json={
            "messages": [{"role": "user", "content": "hello"}],
            "mnda_state": {},
        },
    )
    assert res.status_code == 502
    assert "OPENROUTER_API_KEY" in res.json()["detail"]

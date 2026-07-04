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


def _auth_headers(client) -> dict[str, str]:
    """Register a throwaway user and return its bearer headers — /api/chat
    is a protected endpoint."""
    res = client.post(
        "/api/auth/register",
        json={
            "email": "chatter@example.com",
            "password": "hunter2hunter2",
            "name": "Chatter",
        },
    )
    assert res.status_code == 201
    return {"Authorization": f"Bearer {res.json()['token']}"}


@pytest.fixture
def chat_client(client, monkeypatch):
    captured: dict = {}

    def fake_chat_complete(messages, mnda_state, doc_id=""):
        captured["messages"] = messages
        captured["mnda_state"] = mnda_state
        return {
            "assistant_message": "Got it — what's the effective date?",
            "selected_doc_id": "mutual-nda",
            "mnda_updates": {"purpose": "Evaluating a partnership"},
            "field_updates": {},
            "done": False,
        }

    monkeypatch.setattr(chat_route, "chat_complete", fake_chat_complete)
    client.captured = captured
    client.auth_headers = _auth_headers(client)
    return client


def test_chat_returns_assistant_message_and_updates(chat_client):
    res = chat_client.post(
        "/api/chat",
        headers=chat_client.auth_headers,
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
    assert body["selected_doc_id"] == "mutual-nda"
    assert body["mnda_updates"]["purpose"] == "Evaluating a partnership"
    assert body["field_updates"] == {}
    assert body["done"] is False

    # The route should have forwarded both history and state to the LLM layer.
    assert chat_client.captured["mnda_state"] == {"purpose": ""}
    assert chat_client.captured["messages"][0]["role"] == "user"


def test_chat_rejects_when_last_message_is_assistant(chat_client):
    res = chat_client.post(
        "/api/chat",
        headers=chat_client.auth_headers,
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
    res = chat_client.post(
        "/api/chat",
        headers=chat_client.auth_headers,
        json={"messages": [], "mnda_state": {}},
    )
    assert res.status_code == 422  # pydantic min_length=1


def test_chat_returns_502_when_llm_unavailable(client, monkeypatch):
    def boom(messages, mnda_state, doc_id=""):
        raise llm.LLMUnavailableError("OPENROUTER_API_KEY is not set.")

    monkeypatch.setattr(chat_route, "chat_complete", boom)

    res = client.post(
        "/api/chat",
        headers=_auth_headers(client),
        json={
            "messages": [{"role": "user", "content": "hello"}],
            "mnda_state": {},
        },
    )
    assert res.status_code == 502
    assert "OPENROUTER_API_KEY" in res.json()["detail"]


def test_chat_requires_auth(chat_client):
    """Anonymous callers must not be able to spend LLM credits."""
    res = chat_client.post(
        "/api/chat",
        json={
            "messages": [{"role": "user", "content": "hello"}],
            "mnda_state": {},
        },
    )
    assert res.status_code == 401
    # The LLM layer must never have been reached.
    assert "messages" not in chat_client.captured


def test_chat_forwards_doc_id_to_llm_layer(client, monkeypatch):
    captured: dict = {}

    def fake_chat_complete(messages, mnda_state, doc_id=""):
        captured["doc_id"] = doc_id
        return {
            "assistant_message": "Noted — what's the subscription period?",
            "selected_doc_id": "cloud-service-agreement",
            "mnda_updates": {},
            "field_updates": {},
            "done": False,
        }

    monkeypatch.setattr(chat_route, "chat_complete", fake_chat_complete)

    res = client.post(
        "/api/chat",
        headers=_auth_headers(client),
        json={
            "messages": [{"role": "user", "content": "hello"}],
            "mnda_state": {},
            "doc_id": "cloud-service-agreement",
        },
    )
    assert res.status_code == 200
    assert captured["doc_id"] == "cloud-service-agreement"

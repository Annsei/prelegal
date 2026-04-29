"""Tests for /api/documents — owner-scoped CRUD."""

from __future__ import annotations

import pytest


def _register(client, email: str, password: str = "secretpw1") -> str:
    res = client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )
    assert res.status_code == 201
    return res.json()["token"]


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def alice_token(client):
    return _register(client, "alice@example.com")


@pytest.fixture
def bob_token(client):
    return _register(client, "bob@example.com")


def test_list_starts_empty(client, alice_token):
    res = client.get("/api/documents", headers=_bearer(alice_token))
    assert res.status_code == 200
    assert res.json() == []


def test_unauthenticated_calls_are_401(client):
    assert client.get("/api/documents").status_code == 401
    assert (
        client.post("/api/documents", json={"doc_id": "mutual-nda"}).status_code
        == 401
    )


def test_create_then_read(client, alice_token):
    headers = _bearer(alice_token)
    create = client.post(
        "/api/documents",
        headers=headers,
        json={
            "doc_id": "mutual-nda",
            "title": "Acme × Globex MNDA",
            "state": {"purpose": "Evaluating a partnership"},
        },
    )
    assert create.status_code == 201
    body = create.json()
    assert body["doc_id"] == "mutual-nda"
    assert body["title"] == "Acme × Globex MNDA"
    assert body["state"] == {"purpose": "Evaluating a partnership"}

    fetched = client.get(f"/api/documents/{body['id']}", headers=headers).json()
    assert fetched == body


def test_list_orders_most_recent_first(client, alice_token):
    headers = _bearer(alice_token)
    a = client.post(
        "/api/documents",
        headers=headers,
        json={"doc_id": "mutual-nda", "title": "First"},
    ).json()
    b = client.post(
        "/api/documents",
        headers=headers,
        json={"doc_id": "cloud-service-agreement", "title": "Second"},
    ).json()

    ids = [row["id"] for row in client.get("/api/documents", headers=headers).json()]
    # Most recent (`b`) should come first; tie-break by id descending guards
    # the case where both rows share the same datetime('now') second.
    assert ids[0] == b["id"]
    assert ids[1] == a["id"]


def test_update_changes_state_and_bumps_updated_at(client, alice_token):
    headers = _bearer(alice_token)
    created = client.post(
        "/api/documents",
        headers=headers,
        json={"doc_id": "mutual-nda", "title": "Draft", "state": {"a": "1"}},
    ).json()

    res = client.put(
        f"/api/documents/{created['id']}",
        headers=headers,
        json={"state": {"a": "1", "b": "2"}, "title": "Renamed"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["state"] == {"a": "1", "b": "2"}
    assert body["title"] == "Renamed"
    # updated_at should be at or after created_at — sqlite's datetime('now')
    # has 1-second granularity, so we don't require strict inequality.
    assert body["updated_at"] >= body["created_at"]


def test_partial_update_leaves_other_fields_alone(client, alice_token):
    headers = _bearer(alice_token)
    created = client.post(
        "/api/documents",
        headers=headers,
        json={"doc_id": "mutual-nda", "title": "Keep me", "state": {"x": "y"}},
    ).json()

    # Only update state — title should stay.
    res = client.put(
        f"/api/documents/{created['id']}",
        headers=headers,
        json={"state": {"x": "z"}},
    ).json()
    assert res["title"] == "Keep me"
    assert res["state"] == {"x": "z"}


def test_delete_removes_the_row(client, alice_token):
    headers = _bearer(alice_token)
    created = client.post(
        "/api/documents",
        headers=headers,
        json={"doc_id": "mutual-nda"},
    ).json()
    assert (
        client.delete(f"/api/documents/{created['id']}", headers=headers).status_code
        == 204
    )
    assert (
        client.get(f"/api/documents/{created['id']}", headers=headers).status_code
        == 404
    )


def test_users_cannot_see_each_others_documents(client, alice_token, bob_token):
    alice = _bearer(alice_token)
    bob = _bearer(bob_token)

    alice_doc = client.post(
        "/api/documents",
        headers=alice,
        json={"doc_id": "mutual-nda", "title": "Alice's Draft"},
    ).json()

    # Bob cannot list it.
    bob_list = client.get("/api/documents", headers=bob).json()
    assert bob_list == []

    # Direct read returns 404 (not 403 — don't leak existence).
    assert (
        client.get(f"/api/documents/{alice_doc['id']}", headers=bob).status_code == 404
    )
    # Update + delete also 404.
    assert (
        client.put(
            f"/api/documents/{alice_doc['id']}", headers=bob, json={"title": "Hacked"},
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/documents/{alice_doc['id']}", headers=bob,
        ).status_code
        == 404
    )

    # Alice's row is unchanged.
    still_there = client.get(
        f"/api/documents/{alice_doc['id']}", headers=alice,
    ).json()
    assert still_there["title"] == "Alice's Draft"

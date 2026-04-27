"""Auth tests — real password auth (PL-7).

The fake-login flow from PL-4 is gone. Register requires a password,
login validates it, and both return a session token the frontend uses
on protected endpoints.
"""

from __future__ import annotations


def _register(client, email: str, password: str = "correct horse", name: str = "") -> dict:
    res = client.post(
        "/api/auth/register",
        json={"email": email, "name": name, "password": password},
    )
    assert res.status_code == 201, res.text
    return res.json()


def _login(client, email: str, password: str) -> dict:
    res = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    return res


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_register_creates_user_and_returns_token(client):
    body = _register(client, "alice@example.com", "secretpw1", name="Alice")
    assert body["user"]["email"] == "alice@example.com"
    assert body["user"]["name"] == "Alice"
    assert isinstance(body["user"]["id"], int)
    assert body["token"]
    # Returned token should authorize subsequent calls.
    me = client.get("/api/auth/me", headers=_bearer(body["token"]))
    assert me.status_code == 200
    assert me.json()["email"] == "alice@example.com"


def test_register_rejects_short_password(client):
    res = client.post(
        "/api/auth/register",
        json={"email": "x@example.com", "password": "short"},
    )
    assert res.status_code == 422


def test_register_duplicate_email_conflicts(client):
    _register(client, "bob@example.com", "secretpw1")
    res = client.post(
        "/api/auth/register",
        json={"email": "bob@example.com", "password": "secretpw2"},
    )
    assert res.status_code == 409


def test_register_rejects_invalid_email(client):
    res = client.post(
        "/api/auth/register",
        json={"email": "not-an-email", "password": "secretpw1"},
    )
    assert res.status_code == 422


def test_login_validates_password(client):
    _register(client, "carol@example.com", "rightpassword")

    good = _login(client, "carol@example.com", "rightpassword")
    assert good.status_code == 200
    assert good.json()["user"]["email"] == "carol@example.com"
    assert good.json()["token"]

    bad = _login(client, "carol@example.com", "wrongpassword")
    assert bad.status_code == 401


def test_login_rejects_unknown_email_with_401(client):
    """Same status as wrong password — don't leak whether the email exists."""
    res = _login(client, "ghost@example.com", "anything!")
    assert res.status_code == 401


def test_login_issues_distinct_tokens(client):
    _register(client, "dave@example.com", "secretpw1")
    a = _login(client, "dave@example.com", "secretpw1").json()["token"]
    b = _login(client, "dave@example.com", "secretpw1").json()["token"]
    assert a != b


def test_protected_endpoint_requires_bearer_token(client):
    # /me is a tiny endpoint that just exercises the dep — the documents
    # router would do too, but /me has no other moving parts.
    assert client.get("/api/auth/me").status_code == 401
    assert (
        client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer not-a-real-token"},
        ).status_code
        == 401
    )


def test_logout_invalidates_token(client):
    body = _register(client, "eve@example.com", "secretpw1")
    headers = _bearer(body["token"])

    assert client.get("/api/auth/me", headers=headers).status_code == 200
    assert client.post("/api/auth/logout", headers=headers).status_code == 204
    # Token should now be unrecognized.
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_database_resets_between_clients(client):
    _register(client, "frank@example.com", "secretpw1")

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as fresh:
        # Fresh lifespan run → DB reset → registering frank again should succeed.
        res = fresh.post(
            "/api/auth/register",
            json={"email": "frank@example.com", "password": "secretpw1"},
        )
        assert res.status_code == 201

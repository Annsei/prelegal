def test_register_creates_user(client):
    res = client.post(
        "/api/auth/register",
        json={"email": "alice@example.com", "name": "Alice"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["email"] == "alice@example.com"
    assert body["name"] == "Alice"
    assert isinstance(body["id"], int)
    assert body["created_at"]


def test_register_duplicate_email_conflicts(client):
    client.post("/api/auth/register", json={"email": "bob@example.com"})
    res = client.post("/api/auth/register", json={"email": "bob@example.com"})
    assert res.status_code == 409


def test_register_rejects_invalid_email(client):
    res = client.post("/api/auth/register", json={"email": "not-an-email"})
    assert res.status_code == 422


def test_login_finds_existing_user(client):
    created = client.post(
        "/api/auth/register",
        json={"email": "carol@example.com", "name": "Carol"},
    ).json()
    res = client.post("/api/auth/login", json={"email": "carol@example.com"})
    assert res.status_code == 200
    assert res.json()["id"] == created["id"]


def test_login_creates_user_when_missing(client):
    # Fake login: a brand-new email gets a fresh user. No password required.
    res = client.post("/api/auth/login", json={"email": "dave@example.com"})
    assert res.status_code == 200
    body = res.json()
    assert body["email"] == "dave@example.com"
    # Same email on a second call returns the same user (no duplicate).
    again = client.post("/api/auth/login", json={"email": "dave@example.com"})
    assert again.json()["id"] == body["id"]


def test_login_handles_concurrent_first_logins(client):
    # Register the email out-of-band, then call login. This simulates the
    # race where two concurrent logins both see "no row" and the second
    # INSERT loses the UNIQUE race — login should still succeed, returning
    # the now-existing user instead of bubbling up a 500.
    client.post("/api/auth/register", json={"email": "race@example.com"})
    res = client.post("/api/auth/login", json={"email": "race@example.com"})
    assert res.status_code == 200
    assert res.json()["email"] == "race@example.com"


def test_database_resets_between_clients(client):
    # The lifespan hook should wipe the DB on startup. Register a user, then
    # spin up a new TestClient against the same app and confirm the user is
    # gone — entering the TestClient context re-runs lifespan startup.
    client.post("/api/auth/register", json={"email": "eve@example.com"})
    assert (
        client.post(
            "/api/auth/register",
            json={"email": "eve@example.com"},
        ).status_code
        == 409
    )

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as fresh:
        # Fresh lifespan run → DB reset → registering eve again should succeed.
        res = fresh.post(
            "/api/auth/register",
            json={"email": "eve@example.com"},
        )
        assert res.status_code == 201

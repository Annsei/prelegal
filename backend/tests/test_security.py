"""Security hardening tests: rate limits, session TTL, payload caps.

The timing side-channel fix (dummy bcrypt verify for unknown emails)
isn't directly testable via wall-clock in unit tests; its observable
contract — identical 401 body for unknown email and wrong password —
is covered in test_auth.py. Here we cover the mechanisms that have
crisp pass/fail behavior.
"""

from __future__ import annotations

from app.db import get_conn


def _register(client, email="sec@example.com", password="hunter2hunter2"):
    res = client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "name": "Sec"},
    )
    assert res.status_code == 201
    return res.json()["token"]


# ---------------------------------------------------------------- rate limits


def test_login_rate_limited_per_ip(client):
    _register(client, email="victim@example.com")
    # LOGIN_LIMITER allows 10/min/IP; the registration itself doesn't count
    # against login. Burn the window with wrong passwords, then expect 429.
    for _ in range(10):
        res = client.post(
            "/api/auth/login",
            json={"email": "victim@example.com", "password": "wrong-password"},
        )
        assert res.status_code == 401
    res = client.post(
        "/api/auth/login",
        json={"email": "victim@example.com", "password": "wrong-password"},
    )
    assert res.status_code == 429
    assert "Too many requests" in res.json()["detail"]


def test_register_rate_limited_per_ip(client):
    for i in range(5):
        res = client.post(
            "/api/auth/register",
            json={
                "email": f"bulk{i}@example.com",
                "password": "hunter2hunter2",
                "name": "",
            },
        )
        assert res.status_code == 201
    res = client.post(
        "/api/auth/register",
        json={
            "email": "bulk-overflow@example.com",
            "password": "hunter2hunter2",
            "name": "",
        },
    )
    assert res.status_code == 429


def test_chat_rate_limited_per_user(client, monkeypatch):
    from app.routes import chat as chat_route

    monkeypatch.setattr(
        chat_route,
        "chat_complete",
        lambda messages, mnda_state: {
            "assistant_message": "Sure — what else?",
            "selected_doc_id": "",
            "mnda_updates": {},
            "field_updates": {},
            "done": False,
        },
    )
    headers = {"Authorization": f"Bearer {_register(client)}"}
    body = {
        "messages": [{"role": "user", "content": "hi"}],
        "mnda_state": {},
    }
    for _ in range(20):
        assert (
            client.post("/api/chat", headers=headers, json=body).status_code
            == 200
        )
    res = client.post("/api/chat", headers=headers, json=body)
    assert res.status_code == 429


def test_ratelimit_disabled_via_env(client, monkeypatch):
    monkeypatch.setenv("PRELEGAL_RATELIMIT_DISABLED", "1")
    _register(client, email="nolimit@example.com")
    for _ in range(15):
        res = client.post(
            "/api/auth/login",
            json={"email": "nolimit@example.com", "password": "wrong-password"},
        )
        assert res.status_code == 401  # never 429


# ---------------------------------------------------------------- session TTL


def _backdate_sessions(days: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions "
            "SET created_at = datetime('now', '-' || ? || ' days')",
            (days,),
        )


def test_expired_session_is_rejected(client):
    token = _register(client)
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/auth/me", headers=headers).status_code == 200

    _backdate_sessions(31)  # default TTL is 30 days
    res = client.get("/api/auth/me", headers=headers)
    assert res.status_code == 401


def test_session_ttl_zero_disables_expiry(client, monkeypatch):
    monkeypatch.setenv("PRELEGAL_SESSION_TTL_DAYS", "0")
    token = _register(client)
    headers = {"Authorization": f"Bearer {token}"}
    _backdate_sessions(3650)
    assert client.get("/api/auth/me", headers=headers).status_code == 200


def test_startup_purge_removes_expired_sessions(client):
    from app.auth import purge_expired_sessions

    _register(client)
    _backdate_sessions(31)
    purge_expired_sessions()
    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    assert count == 0


# ---------------------------------------------------------------- payload caps


def test_chat_rejects_oversized_state(client):
    headers = {"Authorization": f"Bearer {_register(client)}"}
    res = client.post(
        "/api/chat",
        headers=headers,
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "mnda_state": {"blob": "x" * (70 * 1024)},  # > 64KB cap
        },
    )
    assert res.status_code == 422
    assert "too large" in res.text


def test_document_rejects_oversized_state(client):
    headers = {"Authorization": f"Bearer {_register(client)}"}
    res = client.post(
        "/api/documents",
        headers=headers,
        json={
            "doc_id": "mutual-nda",
            "state": {"blob": "x" * (600 * 1024)},  # > 512KB cap
        },
    )
    assert res.status_code == 422
    assert "too large" in res.text


def test_oversized_body_rejected_early(client):
    # 3MB of raw junk — the middleware should 413 it before JSON parsing.
    res = client.post(
        "/api/chat",
        content=b"x" * (3 * 1024 * 1024),
        headers={"Content-Type": "application/json"},
    )
    assert res.status_code == 413

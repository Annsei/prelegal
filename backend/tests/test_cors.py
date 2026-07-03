"""CORS is off by default (Docker serves one origin) and opt-in via env
for the cross-origin local dev setup (Next on :3000 → API on :8000)."""

from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def _fresh_app(monkeypatch, tmp_path):
    monkeypatch.setenv("PRELEGAL_DB_PATH", str(tmp_path / "test.sqlite"))
    from app import db, main

    importlib.reload(db)
    importlib.reload(main)
    return main.create_app()


def test_cors_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("PRELEGAL_CORS_ORIGINS", raising=False)
    app = _fresh_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        res = client.get(
            "/api/health", headers={"Origin": "http://localhost:3000"}
        )
        assert res.status_code == 200
        assert "access-control-allow-origin" not in res.headers


def test_cors_enabled_via_env(monkeypatch, tmp_path):
    monkeypatch.setenv("PRELEGAL_CORS_ORIGINS", "http://localhost:3000")
    app = _fresh_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        # Preflight for a protected call carrying the Authorization header.
        res = client.options(
            "/api/documents",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        assert res.status_code == 200
        assert (
            res.headers["access-control-allow-origin"]
            == "http://localhost:3000"
        )

        # Origins not in the allowlist stay blocked.
        res = client.get(
            "/api/health", headers={"Origin": "https://evil.example"}
        )
        assert "access-control-allow-origin" not in res.headers

"""Static-fallback tests.

The backend serves the Next.js static export from `backend/static/`. Build a
fake static dir on the fly and assert that:
  - existing files are served,
  - path-traversal escapes are refused (return index.html, not /etc/*),
  - missing routes fall back to index.html so client-side routing works.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def static_client(tmp_path, monkeypatch):
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html>home</html>")
    (static_dir / "login.html").write_text("<html>login</html>")
    (static_dir / "_next").mkdir()
    (static_dir / "_next" / "asset.js").write_text("// js")

    secret = tmp_path / "secret.txt"
    secret.write_text("TOP SECRET")

    monkeypatch.setenv("PRELEGAL_DB_PATH", str(tmp_path / "test.sqlite"))

    from app.main import create_app

    with TestClient(create_app(static_dir=static_dir)) as c:
        yield c


def test_index_served_at_root(static_client):
    res = static_client.get("/")
    assert res.status_code == 200
    assert "home" in res.text


def test_login_html_served(static_client):
    res = static_client.get("/login")
    assert res.status_code == 200
    assert "login" in res.text


def test_unknown_route_falls_back_to_index(static_client):
    res = static_client.get("/some/spa/route")
    assert res.status_code == 200
    assert "home" in res.text


def test_path_traversal_is_refused(static_client):
    # Should NOT serve files outside the static dir. The fallback to
    # index.html is the safe behaviour.
    res = static_client.get("/../secret.txt")
    assert res.status_code in (200, 404)
    assert "TOP SECRET" not in res.text

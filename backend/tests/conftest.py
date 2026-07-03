from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    """Fresh app + fresh SQLite file per test."""
    monkeypatch.setenv("PRELEGAL_DB_PATH", str(tmp_path / "test.sqlite"))
    # Rate limiters are module-level and keyed by client IP, which is the
    # same ("testclient") for every test — reset them so counts don't leak
    # across tests. Tests that exercise the limits do so within one test.
    from app import ratelimit

    for limiter in ratelimit.ALL_LIMITERS:
        limiter.reset()
    # Import after env var is set so module-level defaults don't capture the
    # production path. We re-import here to be safe across tests.
    import importlib

    from app import db, main

    importlib.reload(db)
    importlib.reload(main)
    with TestClient(main.app) as c:
        yield c

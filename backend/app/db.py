"""SQLite bootstrap.

The DB is recreated from scratch on every process start — by design, per
PL-4. There is no migration story yet; the schema lives here.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DEFAULT_DB_PATH = "/tmp/prelegal.sqlite"


def db_path() -> str:
    return os.environ.get("PRELEGAL_DB_PATH", DEFAULT_DB_PATH)


SCHEMA = """
CREATE TABLE users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    email      TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def reset_database() -> None:
    """Delete the SQLite file (if any) and recreate the schema."""
    path = Path(db_path())
    if path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

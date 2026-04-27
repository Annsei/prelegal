"""SQLite bootstrap.

The DB is recreated from scratch on every process start — by design, per
PL-4 (and confirmed for PL-7). There is no migration story yet; the
schema lives here.
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
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Session tokens issued at login; the frontend sends them as
-- `Authorization: Bearer <token>` on protected endpoints. The whole
-- table goes away on every restart along with the rest of the DB, which
-- is the intended scope of PL-7's persistence.
CREATE TABLE sessions (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_sessions_user ON sessions(user_id);

-- One row per saved draft. `state_json` carries either MndaState (for
-- mutual-nda) or a free-form Record<string,string> of cover-page-level
-- key terms (for any other catalog doc).
CREATE TABLE documents (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    doc_id     TEXT NOT NULL,
    title      TEXT NOT NULL DEFAULT '',
    state_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_documents_user ON documents(user_id, updated_at DESC);
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
    # Enforce FK constraints — sqlite has them off by default and we rely
    # on cascade to clean up sessions/documents when a user is deleted.
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

"""SQLite bootstrap.

The DB file persists across server restarts so users don't lose their
account or saved drafts when the container is recreated. The Docker
image declares `/data` as a volume and the start scripts mount a host
directory there, so on `docker rm` the file lives on outside the
container. Tests run against a fresh tmp_path each time, which has the
same effect as the old "wipe on startup" mode.

There is no migration framework yet — schema changes need a manual
data-aware migration before this runs against existing volumes. For
v1 we just keep `CREATE TABLE IF NOT EXISTS` so first boot creates
the schema and subsequent boots are no-ops.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DEFAULT_DB_PATH = "/data/prelegal.sqlite"


def db_path() -> str:
    return os.environ.get("PRELEGAL_DB_PATH", DEFAULT_DB_PATH)


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Session tokens issued at login; the frontend sends them as
-- `Authorization: Bearer <token>` on protected endpoints. Tokens
-- persist across restarts (no expiry yet) so a stored token in
-- localStorage can keep working after a server bounce; explicit
-- logout still removes the row immediately. Adding TTL is a follow-up.
CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

-- One row per saved draft. `state_json` carries either MndaState (for
-- mutual-nda) or a free-form Record<string,string> of cover-page-level
-- key terms (for any other catalog doc).
CREATE TABLE IF NOT EXISTS documents (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    doc_id     TEXT NOT NULL,
    title      TEXT NOT NULL DEFAULT '',
    state_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_documents_user
    ON documents(user_id, updated_at DESC);
"""


def init_database() -> None:
    """Create the schema if it doesn't exist. Idempotent — safe to run
    on every process start without losing data."""
    path = Path(db_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)


def reset_database() -> None:
    """Delete the SQLite file and recreate the schema. Used by the test
    harness via tmp_path; production code should call `init_database`."""
    path = Path(db_path())
    if path.exists():
        path.unlink()
    init_database()


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

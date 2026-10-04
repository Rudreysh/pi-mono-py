"""SQLite v4-style session backend."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    cwd TEXT NOT NULL,
    created_at TEXT NOT NULL,
    parent_session TEXT
);
CREATE TABLE IF NOT EXISTS entries (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    payload TEXT NOT NULL
);
"""


class SqliteSessionRepo:
    def __init__(self, path: str) -> None:
        self._path = path
        self._conn = sqlite3.connect(path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def create_session(self, session: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO sessions(id, cwd, created_at, parent_session) VALUES (?, ?, ?, ?)",
            (
                session["id"],
                session.get("cwd") or "",
                session.get("timestamp") or "",
                session.get("parentSession"),
            ),
        )
        self._conn.commit()

    def append_entry(self, session_id: str, entry: dict[str, Any]) -> None:
        seq_row = self._conn.execute(
            "SELECT COALESCE(MAX(seq), 0) FROM entries WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        seq = int(seq_row[0]) + 1
        self._conn.execute(
            "INSERT INTO entries(id, session_id, seq, payload) VALUES (?, ?, ?, ?)",
            (entry.get("id") or f"{session_id}:{seq}", session_id, seq, json.dumps(entry)),
        )
        self._conn.commit()

    def load_entries(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT payload FROM entries WHERE session_id = ? ORDER BY seq",
            (session_id,),
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def close(self) -> None:
        self._conn.close()

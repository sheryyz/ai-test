"""SQLite sandbox for one case execution of the approval agent."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from targets.approval_agent.fixtures import ApprovalFixture

SCHEMA = """
CREATE TABLE requests (
    request_id TEXT PRIMARY KEY,
    applicant  TEXT NOT NULL,
    kind       TEXT NOT NULL,
    amount     INTEGER NOT NULL,
    title      TEXT NOT NULL,
    detail     TEXT NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected')),
    decided_at TEXT,
    decided_by TEXT,
    comment    TEXT
);
"""


class ApprovalSandbox:
    def __init__(self, path: Path, fixture: ApprovalFixture) -> None:
        self.path = path
        self.fixture = fixture
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row

    @classmethod
    def create(cls, path: Path, fixture: ApprovalFixture) -> ApprovalSandbox:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()
        box = cls(path, fixture)
        with box.conn:
            box.conn.executescript(SCHEMA)
            if fixture.requests:
                cols = list(fixture.requests[0])
                box.conn.executemany(
                    f"INSERT INTO requests ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                    [tuple(r[c] for c in cols) for r in fixture.requests],
                )
        return box

    def close(self) -> None:
        self.conn.close()

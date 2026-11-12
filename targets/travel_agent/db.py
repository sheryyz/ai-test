"""SQLite sandbox for one case execution of the travel agent."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from targets.travel_agent.fixtures import TravelFixture

SCHEMA = """
CREATE TABLE flights (
    flight_no    TEXT NOT NULL,
    date         TEXT NOT NULL,
    origin       TEXT NOT NULL,
    destination  TEXT NOT NULL,
    depart_time  TEXT NOT NULL,
    arrive_time  TEXT NOT NULL,
    duration_min INTEGER NOT NULL,
    PRIMARY KEY (flight_no, date)
);
CREATE TABLE fares (
    flight_no  TEXT NOT NULL,
    date       TEXT NOT NULL,
    cabin      TEXT NOT NULL CHECK (cabin IN ('economy', 'business')),
    price      INTEGER NOT NULL,
    seats_left INTEGER NOT NULL CHECK (seats_left >= 0),
    PRIMARY KEY (flight_no, date, cabin)
);
CREATE TABLE orders (
    order_id     TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    flight_no    TEXT NOT NULL,
    date         TEXT NOT NULL,
    origin       TEXT NOT NULL,
    destination  TEXT NOT NULL,
    cabin        TEXT NOT NULL,
    price        INTEGER NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('booked', 'cancelled')),
    created_at   TEXT NOT NULL,
    cancelled_at TEXT
);
"""


class TravelSandbox:
    def __init__(self, path: Path, fixture: TravelFixture) -> None:
        self.path = path
        self.fixture = fixture
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row

    @classmethod
    def create(cls, path: Path, fixture: TravelFixture) -> TravelSandbox:
        """Create a fresh database at `path` (replacing any old one) and seed it."""
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()
        box = cls(path, fixture)
        with box.conn:
            box.conn.executescript(SCHEMA)
            box._insert("flights", fixture.flights)
            box._insert("fares", fixture.fares)
            box._insert("orders", fixture.orders)
        return box

    def _insert(self, table: str, rows: list[dict]) -> None:
        if not rows:
            return
        cols = list(rows[0])
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
        self.conn.executemany(sql, [tuple(r[c] for c in cols) for r in rows])

    @property
    def now(self) -> str:
        return self.fixture.now

    @property
    def user_id(self) -> str:
        return self.fixture.user["user_id"]

    def next_order_id(self) -> str:
        """Sequential ids keep snapshots reproducible across runs."""
        row = self.conn.execute("SELECT MAX(CAST(SUBSTR(order_id, 5) AS INTEGER)) FROM orders").fetchone()
        return f"ORD-{(row[0] or 0) + 1:04d}"

    def close(self) -> None:
        self.conn.close()

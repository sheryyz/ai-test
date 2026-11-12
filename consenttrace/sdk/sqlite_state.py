"""Read-only, deterministic snapshots of any SQLite database.

Tables and primary keys are discovered from the schema, rows are ordered by primary
key, and the digest covers the canonical JSON form, so two databases with the same
content always produce the same snapshot regardless of insertion order.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from consenttrace.schemas import StateSnapshot, TableSnapshot


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def snapshot_sqlite(path: str | Path, tables: Iterable[str] | None = None, *, step: int | None = None) -> StateSnapshot:
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    try:
        names = (
            list(tables)
            if tables is not None
            else [
                r[0]
                for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
        )
        out: dict[str, TableSnapshot] = {}
        for name in names:
            info = con.execute(f"PRAGMA table_info({_quote(name)})").fetchall()
            if not info:
                raise ValueError(f"no such table: {name}")
            columns = [r["name"] for r in info]
            pk = [r["name"] for r in sorted((r for r in info if r["pk"]), key=lambda r: r["pk"])]
            order = ", ".join(_quote(c) for c in (pk or columns))
            rows = [dict(r) for r in con.execute(f"SELECT * FROM {_quote(name)} ORDER BY {order}")]
            out[name] = TableSnapshot(pk=pk, columns=columns, rows=rows)
    finally:
        con.close()
    return StateSnapshot(tables=out, digest=_digest(out), captured_at_step=step)


def _digest(tables: dict[str, TableSnapshot]) -> str:
    canonical: dict[str, Any] = {name: t.model_dump(mode="json") for name, t in sorted(tables.items())}
    blob = json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def describe_sqlite(path: str | Path) -> dict[str, dict[str, list[str]]]:
    """Tables, columns and primary keys of a SQLite database, without reading any rows."""
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    try:
        out: dict[str, dict[str, list[str]]] = {}
        for (name,) in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall():
            info = con.execute(f"PRAGMA table_info({_quote(name)})").fetchall()
            out[name] = {
                "columns": [r["name"] for r in info],
                "pk": [r["name"] for r in sorted((r for r in info if r["pk"]), key=lambda r: r["pk"])],
            }
        return out
    finally:
        con.close()

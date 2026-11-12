from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from consenttrace.sdk.sqlite_state import snapshot_sqlite

ROWS = [("b", 2, "x"), ("a", 2, "y"), ("a", 1, "z")]


def _make_db(path: Path, rows: list[tuple[str, int, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    with con:
        con.execute("CREATE TABLE pairs (a TEXT, b INTEGER, v TEXT, PRIMARY KEY (b, a))")
        con.execute("CREATE TABLE log (msg TEXT, n INTEGER)")
        con.executemany("INSERT INTO pairs VALUES (?, ?, ?)", rows)
        con.executemany("INSERT INTO log VALUES (?, ?)", [("z", 1), ("a", 2)])
    con.close()
    return path


def test_discovers_tables_and_composite_pk_in_declared_order(tmp_path: Path) -> None:
    snap = snapshot_sqlite(_make_db(tmp_path / "s.db", ROWS), step=7)

    assert list(snap.tables) == ["log", "pairs"]
    pairs = snap.tables["pairs"]
    assert pairs.pk == ["b", "a"] and pairs.columns == ["a", "b", "v"]
    assert [(r["b"], r["a"]) for r in pairs.rows] == [(1, "a"), (2, "a"), (2, "b")]
    assert snap.captured_at_step == 7


def test_table_without_pk_is_ordered_by_all_columns(tmp_path: Path) -> None:
    snap = snapshot_sqlite(_make_db(tmp_path / "s.db", ROWS))
    assert snap.tables["log"].pk == []
    assert [r["msg"] for r in snap.tables["log"].rows] == ["a", "z"]


def test_digest_ignores_insertion_order_but_not_content(tmp_path: Path) -> None:
    one = snapshot_sqlite(_make_db(tmp_path / "one.db", ROWS))
    two = snapshot_sqlite(_make_db(tmp_path / "two.db", list(reversed(ROWS))))
    changed = snapshot_sqlite(_make_db(tmp_path / "three.db", [*ROWS[:2], ("a", 1, "CHANGED")]))

    assert one.digest == two.digest
    assert one.digest != changed.digest


def test_can_limit_to_selected_tables_and_rejects_unknown(tmp_path: Path) -> None:
    db = _make_db(tmp_path / "s.db", ROWS)
    assert list(snapshot_sqlite(db, ["pairs"]).tables) == ["pairs"]
    with pytest.raises(ValueError, match="no such table"):
        snapshot_sqlite(db, ["ghost"])


def test_opens_read_only_and_never_creates_files(tmp_path: Path) -> None:
    missing = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        snapshot_sqlite(missing)
    assert not missing.exists()


def test_works_under_non_ascii_paths(tmp_path: Path) -> None:
    db = _make_db(tmp_path / "评测 目录" / "沙箱.db", ROWS)
    assert len(snapshot_sqlite(db).tables["pairs"].rows) == 3

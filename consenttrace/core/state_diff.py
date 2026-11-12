"""Row-level differences between two state snapshots, keyed by primary key."""

from __future__ import annotations

from typing import Any

from consenttrace.schemas import RowChange, StateDiff, StateSnapshot, TableDiff, TableSnapshot


def _keyed(table: TableSnapshot | None, key_cols: list[str]) -> dict[tuple, dict[str, Any]]:
    if table is None:
        return {}
    return {tuple(row.get(c) for c in key_cols): row for row in table.rows}


def diff_snapshots(before: StateSnapshot, after: StateSnapshot) -> StateDiff:
    tables: dict[str, TableDiff] = {}
    for name in sorted(set(before.tables) | set(after.tables)):
        b, a = before.tables.get(name), after.tables.get(name)
        ref = a or b
        assert ref is not None
        key_cols = ref.pk or ref.columns
        old, new = _keyed(b, key_cols), _keyed(a, key_cols)

        def pk(key: tuple, cols: list[str] = key_cols) -> dict[str, Any]:
            return dict(zip(cols, key, strict=True))

        inserted = [RowChange(pk=pk(k), after=new[k]) for k in sorted(new.keys() - old.keys(), key=repr)]
        deleted = [RowChange(pk=pk(k), before=old[k]) for k in sorted(old.keys() - new.keys(), key=repr)]
        updated = []
        for k in sorted(new.keys() & old.keys(), key=repr):
            if old[k] != new[k]:
                changed = [c for c in ref.columns if old[k].get(c) != new[k].get(c)]
                updated.append(RowChange(pk=pk(k), before=old[k], after=new[k], changed=changed))
        if inserted or deleted or updated:
            tables[name] = TableDiff(inserted=inserted, deleted=deleted, updated=updated)
    return StateDiff(tables=tables)

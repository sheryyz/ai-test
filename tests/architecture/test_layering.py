"""The platform must stay independent of the agents it tests (PRD §7.1)."""

from __future__ import annotations

import ast
from pathlib import Path

from tests.helpers import ROOT


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def test_consenttrace_never_imports_targets() -> None:
    offenders = {
        str(path.relative_to(ROOT)): sorted(m for m in _imports(path) if m == "targets" or m.startswith("targets."))
        for path in (ROOT / "consenttrace").rglob("*.py")
    }
    assert {p: m for p, m in offenders.items() if m} == {}


def test_targets_only_use_the_sdk_facing_parts_of_consenttrace() -> None:
    allowed = ("consenttrace.sdk", "consenttrace.llm", "consenttrace.schemas", "consenttrace.adapters", "consenttrace.config")
    offenders = {
        str(path.relative_to(ROOT)): sorted(
            m for m in _imports(path) if m.startswith("consenttrace") and not m.startswith(allowed)
        )
        for path in (ROOT / "targets").rglob("*.py")
    }
    assert {p: m for p, m in offenders.items() if m} == {}

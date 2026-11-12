"""Loads contracts (YAML) and case suites (JSONL) with errors that point at the exact spot."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from pydantic import ValidationError

from consenttrace.core.auth_state import AuthorizationLedger, CaseScriptError
from consenttrace.core.registry import TargetSpec
from consenttrace.schemas import TestCase, TestContract


class LoadError(ValueError):
    def __init__(self, source: str, problems: list[str]) -> None:
        self.source = source
        self.problems = problems
        super().__init__(f"{source}: " + "; ".join(problems))


def _describe(exc: ValidationError) -> list[str]:
    return [f"{'.'.join(str(p) for p in err['loc']) or '(root)'}: {err['msg']}" for err in exc.errors()]


def load_contract(path: str | Path) -> TestContract:
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise LoadError(str(path), [f"invalid YAML: {exc}"]) from exc
    try:
        return TestContract.model_validate(data)
    except ValidationError as exc:
        raise LoadError(str(path), _describe(exc)) from exc


def _raw_cases(path: Path) -> tuple[list[tuple[str, object]], list[str]]:
    """(location, raw case) pairs. YAML suites are for authoring; JSONL is the frozen form."""
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        try:
            data = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            return [], [f"invalid YAML: {exc}"]
        items = data.get("cases", []) if isinstance(data, dict) else data
        if not isinstance(items, list):
            return [], ["expected a list of cases (or a mapping with a 'cases' list)"]
        return [(f"case #{i}", item) for i, item in enumerate(items, start=1)], []
    raw, problems = [], []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("//"):
            continue
        try:
            raw.append((f"line {lineno}", json.loads(line)))
        except json.JSONDecodeError as exc:
            problems.append(f"line {lineno}: invalid JSON: {exc.msg}")
    return raw, problems


def load_cases(path: str | Path, contract: TestContract | None = None) -> list[TestCase]:
    """Parse a suite (.jsonl or .yaml). With a contract, also dry-run each case's events through the ledger."""
    path = Path(path)
    raw, problems = _raw_cases(path)
    cases: list[TestCase] = []
    seen: set[str] = set()
    for where, item in raw:
        try:
            case = TestCase.model_validate(item)
        except ValidationError as exc:
            problems.extend(f"{where}: {p}" for p in _describe(exc))
            continue
        if case.case_id in seen:
            problems.append(f"{where}: duplicate case_id {case.case_id}")
        seen.add(case.case_id)
        if contract is not None:
            problems.extend(f"{where} ({case.case_id}): {p}" for p in check_case_against_contract(case, contract))
        cases.append(case)
    if problems:
        raise LoadError(str(path), problems)
    return cases


def check_case_against_contract(case: TestCase, contract: TestContract) -> list[str]:
    problems = []
    if case.target != contract.adapter:
        problems.append(f"target {case.target!r} does not match contract adapter {contract.adapter!r}")
    ledger = AuthorizationLedger(a.action for a in contract.sensitive_actions)
    for turn_no, turn in enumerate(case.turns, start=1):
        for event in turn.events:
            try:
                ledger.apply(event, step=turn_no, turn=turn_no)
            except CaseScriptError as exc:
                problems.append(str(exc))
    return problems


def load_suite(spec: TargetSpec, suite: str, contract: TestContract | None = None) -> list[TestCase]:
    """The cases of one registered suite, honouring subset suites (see core/registry.py)."""
    cases = {c.case_id: c for c in load_cases(spec.suite(suite), contract)}
    return [cases[c] for c in spec.select(suite, list(cases))]

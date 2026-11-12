"""Offline re-judging of stored evidence, and the analysis numbers derived from it."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from rich.console import Console

from consenttrace import cli
from consenttrace.core.analysis import ratio, run_breakdown
from consenttrace.core.evidence import EvidenceStore, load_results
from consenttrace.core.loader import load_cases, load_contract
from consenttrace.core.reevaluate import reevaluate_run
from tests.helpers import ROOT, record_run

CONTRACT = load_contract(ROOT / "configs" / "travel_contract.yaml")
CASES = {c.case_id: c for c in load_cases(ROOT / "benchmarks" / "travel_smoke.yaml", CONTRACT)}


def digest_tree(path: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(p for p in path.rglob("*") if p.is_file()):
        h.update(str(f.relative_to(path)).encode())
        h.update(f.read_bytes())
    return h.hexdigest()


def test_same_oracle_gives_same_verdicts_and_never_touches_the_source(tmp_path: Path) -> None:
    source = record_run(tmp_path / "runs")
    before = digest_tree(source)
    reevaluate_run(source, EvidenceStore(tmp_path / "runs", "again"), contract=CONTRACT, cases=CASES)
    assert digest_tree(source) == before
    old = {(r.case_id, r.rep): r for r in load_results(source)}
    new = {(r.case_id, r.rep): r for r in load_results(tmp_path / "runs" / "again")}
    assert old.keys() == new.keys()
    for key in old:
        assert old[key].outcome is new[key].outcome
        assert [f.model_dump() for f in old[key].findings] == [f.model_dump() for f in new[key].findings]
        assert new[key].metrics["reevaluated_from"] == "recorded"


def test_a_changed_oracle_changes_only_what_it_should(tmp_path: Path) -> None:
    source = record_run(tmp_path / "runs")
    weaker = CONTRACT.model_copy(update={"rules": [r for r in CONTRACT.rules if r.id != "PARAMS_MATCH"]})
    changes = []
    reevaluate_run(
        source,
        EvidenceStore(tmp_path / "runs", "weaker"),
        contract=weaker,
        cases=CASES,
        on_result=lambda o, n: changes.append((o, n)),
    )
    stale = next(n for o, n in changes if o.case_id == "S02-confirm-then-change-destination")
    assert "PARAMS_MATCH" not in {f.rule_id for f in stale.findings}
    assert "AUTH_BEFORE_ACTION" in {f.rule_id for f in stale.findings}  # still caught by the other rule


def test_missing_case_or_capabilities_are_reported(tmp_path: Path) -> None:
    source = record_run(tmp_path / "runs")
    with pytest.raises(KeyError, match="no longer in the suite"):
        reevaluate_run(source, EvidenceStore(tmp_path / "runs", "x"), contract=CONTRACT, cases={})


def test_cli_reevaluate_lists_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setattr(cli, "console", Console(width=200, force_terminal=False, color_system=None))
    record_run(tmp_path / "runs")
    targets = str(ROOT / "configs" / "targets.yaml")
    code = cli.main(
        ["--targets", targets, "--runs-dir", str(tmp_path / "runs"), "reevaluate", "--run", "recorded", "--as", "re1"]
    )
    assert code == 1
    out = capsys.readouterr().out
    assert "判定发生变化的执行（0 / 3）" in out and "原始运行保持不变" in out
    assert cli.main(["--targets", targets, "--runs-dir", str(tmp_path / "runs"), "reevaluate", "--run", "ghost"]) == 2


def test_breakdown_numbers_carry_their_denominators(tmp_path: Path) -> None:
    source = record_run(tmp_path / "runs")
    b = run_breakdown(source, CASES)
    t = b["totals"]
    assert t["executions"] == 3 and t["outcomes"] == {"PASS": 1, "FAIL": 2}
    assert t["auth_violation"] == {"num": 2, "den": 3, "rate": 0.6667}
    assert t["side_effect"]["num"] == 2
    assert t["task_success"] == {"num": 1, "den": 3, "rate": 0.3333}
    assert t["attack_success"] == {"num": 1, "den": 1, "rate": 1.0}  # S07's timeout injection was followed by a duplicate
    assert t["pass_k"] == {"num": 1, "den": 3, "rate": 0.3333}
    assert b["categories"]["C2"]["auth_violation"]["num"] == 1
    assert ratio(0, 0) == {"num": 0, "den": 0, "rate": None}

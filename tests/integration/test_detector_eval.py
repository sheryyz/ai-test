"""Detector evaluation: the labelled defect corpus, every oracle on the same executions, and mutants."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from consenttrace.core.baselines import ORACLES
from consenttrace.core.detector_eval import (
    compare_on_run,
    load_corpus,
    run_corpus,
    score_corpus,
    score_table,
    write_score_csv,
)
from consenttrace.core.loader import load_cases, load_contract
from consenttrace.sdk.recorder import TraceRecorder
from consenttrace.sdk.toolbox import Toolbox
from targets.travel_agent.mutants import MUTANTS, apply_mutant
from tests.helpers import ROOT, record_run

TARGETS = ROOT / "configs" / "targets.yaml"
CONTRACT = load_contract(ROOT / "configs" / "travel_contract.yaml")
MAIN = {c.case_id: c for c in load_cases(ROOT / "benchmarks" / "travel_main.yaml", CONTRACT)}
SMOKE = {c.case_id: c for c in load_cases(ROOT / "benchmarks" / "travel_smoke.yaml", CONTRACT)}
CORPUS = load_corpus(ROOT / "benchmarks" / "travel_defects.py")


@pytest.fixture(scope="module")
def scored(tmp_path_factory: pytest.TempPathFactory) -> dict:
    run_dir = run_corpus(CORPUS, targets_path=TARGETS, runs_dir=tmp_path_factory.mktemp("runs"), run_id="corpus")
    return score_corpus(run_dir, CONTRACT, MAIN)


def rows_by_id(scored: dict) -> dict[str, dict]:
    return {r["execution"].split("--")[0]: r for r in scored["rows"]}


def test_corpus_entries_are_real_main_suite_cases_with_unique_ids() -> None:
    ids = [e.id for e in CORPUS.ENTRIES]
    assert len(ids) == len(set(ids))
    assert all(e.case_id in MAIN for e in CORPUS.ENTRIES)
    assert {e.mutant for e in CORPUS.ENTRIES if e.mutant} <= set(MUTANTS)
    # both defective and clean behaviours are present
    assert any(e.violation for e in CORPUS.ENTRIES) and any(not (e.violation or e.claim) for e in CORPUS.ENTRIES)


def test_every_execution_ran_and_is_judged_by_every_oracle(scored: dict) -> None:
    assert scored["executions"] == len(CORPUS.ENTRIES)
    assert scored["positives"] == sum(e.violation for e in CORPUS.ENTRIES)
    for row in scored["rows"]:
        assert set(row["verdicts"]) == set(ORACLES)
        if row["label"]["bad_call"]:
            assert row["expected_step"] is not None, f"{row['execution']}: labelled bad call never happened"


def test_consenttrace_agrees_with_every_label(scored: dict) -> None:
    """A regression guard on known truth: any disagreement is a detector change to review."""
    for row in scored["rows"]:
        ours, label = row["verdicts"]["ours"], row["label"]
        assert (ours["violation"], ours["side_effect"], ours["claim"]) == (
            label["violation"],
            label["side_effect"],
            label["claim"],
        ), row["execution"]
        if row["expected_step"] is not None:
            assert ours["first_bad_step"] == row["expected_step"], row["execution"]


def test_baselines_miss_what_their_evidence_cannot_show(scored: dict) -> None:
    rows = rows_by_id(scored)
    # a stale confirmation looks like "the user did confirm" to the naive flag
    assert not rows["D01"]["verdicts"]["trace_flag"]["violation"]
    # a blocked attempt leaves no success claim, so output-only sees nothing
    assert not rows["D16"]["verdicts"]["output_only"]["violation"]
    # without the state diff the receipt-less write is invisible
    assert not rows["D12"]["verdicts"]["no_diff"]["side_effect"]
    assert rows["D12"]["verdicts"]["no_ledger"]["side_effect"]
    # output-only has no step-level evidence to localize with
    assert scored["scores"]["output_only"]["localization"]["num"] == 0


def test_no_oracle_flags_the_clean_entries(scored: dict) -> None:
    for name, s in scored["scores"].items():
        assert s["violation"]["fp"] == 0, name


def test_score_table_and_csv(scored: dict, tmp_path: Path) -> None:
    rows = score_table(scored)
    assert len(rows) == 4 * len(ORACLES)
    path = tmp_path / "out" / "benchmark_comparison.csv"
    write_score_csv(rows, path)
    with path.open(encoding="utf-8") as f:
        read = list(csv.DictReader(f))
    ours = next(r for r in read if r["oracle"] == "ours" and r["dimension"] == "violation")
    assert int(ours["tp"]) + int(ours["fn"]) == scored["positives"]


def test_compare_on_a_real_run_agrees_with_itself(tmp_path: Path) -> None:
    run_dir = record_run(tmp_path / "runs")
    cmp = compare_on_run(run_dir, CONTRACT, SMOKE)
    assert cmp["executions"] > 0
    assert cmp["agreement_with_ours"]["ours"] == cmp["executions"]
    assert all(d["oracle"] != "ours" for d in cmp["disagreements"])


def test_unknown_and_misplaced_mutants_are_refused() -> None:
    box = Toolbox(TraceRecorder("r", "c"))
    with pytest.raises(ValueError, match="unknown mutant"):
        apply_mutant("M99", box, None)
    with pytest.raises(ValueError, match="V2 gate"):
        apply_mutant("M6_no_idempotency", box, None)


def test_corpus_module_must_expose_its_interface(tmp_path: Path) -> None:
    bad = tmp_path / "bad_corpus.py"
    bad.write_text("TARGET = 'travel'\n", encoding="utf-8")
    with pytest.raises(AttributeError, match="SUITE"):
        load_corpus(bad)

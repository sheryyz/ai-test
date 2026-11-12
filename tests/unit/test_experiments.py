"""The experiment-analysis view: mechanical run selection and each section read from evidence."""

from __future__ import annotations

import json
from pathlib import Path

from consenttrace.core.experiments import (
    detectors_section,
    drafts_section,
    experiment_summary,
    latest_live_runs,
    suites_section,
)
from consenttrace.core.loader import load_cases
from consenttrace.core.registry import load_targets
from tests.helpers import ROOT, record_run

TARGETS = load_targets(ROOT / "configs" / "targets.yaml")


def suite_cases(spec, suite):
    return {c.case_id: c for c in load_cases(spec.suites[suite])} if suite in spec.suites else {}


def as_live(run_dir: Path, version: str = "v1", finished: str | None = None) -> None:
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    summary.update(mode="live", agent_version=version)
    if finished:
        summary["finished_at"] = finished
    (run_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")


def test_only_live_runs_are_selected_and_the_latest_wins(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    scripted = record_run(runs, "scripted")
    assert latest_live_runs(runs) == {}
    old, new = record_run(runs, "old"), record_run(runs, "new")
    as_live(old, finished="2026-11-01T00:00:00Z")
    as_live(new, finished="2026-11-02T00:00:00Z")
    chosen = latest_live_runs(runs)
    assert list(chosen) == [("travel", "smoke", "v1")] and chosen[("travel", "smoke", "v1")][0].name == "new"
    assert scripted.name not in {p.name for p, _ in chosen.values()}


def test_suites_section_orders_versions_and_lists_steps(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    as_live(record_run(runs, "a"), "v2")
    as_live(record_run(runs, "b"), "v1")
    (smoke,) = suites_section(runs, TARGETS, suite_cases)
    assert [v["version"] for v in smoke["versions"]] == ["v1", "v2"]
    step = smoke["steps"][0]
    executed = smoke["versions"][0]["totals"]["cases"]
    assert (step["a"], step["b"]) == ("v1", "v2")
    assert step["changes"] == {"unchanged": executed}  # same scripted behaviour twice: every case classified once, unchanged
    assert smoke["versions"][0]["totals"]["executions"] > 0


def test_detector_and_draft_sections_read_the_newest_files(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    assert detectors_section(runs) is None and drafts_section(runs) == []
    det = runs / "detectors-x"
    det.mkdir(parents=True)
    scores = {"ours": {"violation": {"tp": 1, "fp": 0, "fn": 0, "tn": 1}}}
    (det / "detector_eval.json").write_text(json.dumps({"executions": 2, "positives": 1, "scores": scores}), encoding="utf-8")
    d = detectors_section(runs)
    assert d is not None and d["run_id"] == "detectors-x" and d["labels"]["ours"] == "ConsentTrace" and d["real_runs"] == []
    drafts = runs / "contract_drafts" / "draft-x"
    drafts.mkdir(parents=True)
    ev = {"target": "travel", "model": "m", "on_runs": [], "drafts": [{"draft": 1, "valid": False, "attempts": 3}]}
    (drafts / "evaluation.json").write_text(json.dumps(ev), encoding="utf-8")
    (row,) = drafts_section(runs)
    assert row["target"] == "travel" and row["drafts"][0] == {"draft": 1, "valid": False, "attempts": 3}


def test_summary_has_every_section(tmp_path: Path) -> None:
    out = experiment_summary(tmp_path, TARGETS, suite_cases)
    assert set(out) == {"suites", "phrasing", "detectors", "drafts"} and out["suites"] == []

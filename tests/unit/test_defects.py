"""Defects are merged from judgements still in force, and their fix status comes from re-tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from consenttrace.core.defects import collect_defects, defect_kinds, defect_summary, replay_sources, runs_in_force
from consenttrace.core.evidence import EvidenceStore
from consenttrace.core.registry import load_targets
from consenttrace.schemas import Finding, Outcome, RunResult, RunSummary, Severity, ViolationKind
from tests.helpers import ROOT

TARGETS = load_targets(ROOT / "configs" / "targets.yaml")
T0 = datetime(2026, 11, 12, 8, 0, tzinfo=UTC)


def finding(kind: ViolationKind, rule: str = "AUTH_BEFORE_ACTION", step: int = 7) -> Finding:
    return Finding(rule_id=rule, kind=kind, severity=Severity.CRITICAL, first_bad_step=step, reason="r")


def write_run(
    runs: Path,
    run_id: str,
    *,
    minutes: int,
    results: list[tuple[str, int, Outcome, list[Finding]]],
    target: str = "travel",
    version: str = "v1",
    mode: str = "live",
    suite: str = "main",
    extra: dict | None = None,
    reevaluated_from: str | None = None,
    cassettes: bool = False,
) -> None:
    store = EvidenceStore(runs, run_id)
    cases = sorted({c for c, *_ in results})
    config = {"run_id": run_id, "target": target, "suite": suite, "cases": cases, "extra": extra or {}, "transport": "http"}
    if reevaluated_from:
        config["reevaluated_from"] = reevaluated_from
    store.prepare(config)
    for case_id, rep, outcome, findings in results:
        result = RunResult(
            run_id=run_id,
            case_id=case_id,
            rep=rep,
            outcome=outcome,
            findings=findings,
            mode=mode,
            agent_version=version,  # type: ignore[arg-type]
        )
        case_dir = store.case_dir(case_id, rep)
        store.write_case(case_dir, events=[], files={}, result=result)
        if cassettes:
            (case_dir / "cassette.jsonl").write_text("{}\n", encoding="utf-8")
    store.write_summary(
        RunSummary(
            run_id=run_id,
            target=target,
            agent_version=version,
            mode=mode,  # type: ignore[arg-type]
            contract_id="c",
            suite=suite,
            reps=2,
            executions=len(results),
            counts={},
            started_at=T0 + timedelta(minutes=minutes),
            finished_at=T0 + timedelta(minutes=minutes, seconds=30),
        )
    )


def no_cases(_spec, _suite):
    return {}


def build(runs: Path) -> None:
    write_run(
        runs,
        "live-v1",
        minutes=0,
        results=[
            ("A", 0, Outcome.FAIL, [finding(ViolationKind.SIDE_EFFECT)]),
            ("A", 1, Outcome.PASS, []),
            ("B", 0, Outcome.FAIL, []),  # a task failure the detector later stops reporting
            ("C", 0, Outcome.ERROR, []),
        ],
    )
    write_run(
        runs,
        "live-v1-reeval",
        minutes=10,
        reevaluated_from="live-v1",
        cassettes=True,
        results=[
            (
                "A",
                0,
                Outcome.FAIL,
                [finding(ViolationKind.SIDE_EFFECT), finding(ViolationKind.SIDE_EFFECT, "NO_UNAUTHORIZED_WRITE")],
            ),
            ("A", 1, Outcome.PASS, []),
            ("B", 0, Outcome.PASS, []),
            ("C", 0, Outcome.ERROR, []),
        ],
    )
    write_run(runs, "corpus", minutes=5, mode="scripted", results=[("A", 0, Outcome.FAIL, [finding(ViolationKind.SIDE_EFFECT)])])
    write_run(
        runs,
        "approval-v1",
        minutes=20,
        target="approval",
        suite="core",
        results=[("X", 0, Outcome.FAIL, [finding(ViolationKind.ATTEMPT, "APPROVE_AUTH", 4)])],
    )


def test_only_judgements_in_force_count(tmp_path: Path) -> None:
    build(tmp_path)
    assert [r.run_id for r in runs_in_force(tmp_path)] == ["live-v1-reeval", "approval-v1"]
    defects = {d["id"]: d for d in collect_defects(tmp_path, TARGETS, no_cases)}
    # B was withdrawn by the re-evaluation, C only errored, and the scripted corpus is not an agent under test
    assert set(defects) == {"travel:v1:A", "approval:v1:X"}
    a = defects["travel:v1:A"]
    assert a["kind"] == "side_effect" and a["rules"] == ["AUTH_BEFORE_ACTION", "NO_UNAUTHORIZED_WRITE"]
    assert a["executions"] == {"live": 2, "live_fail": 1, "replay": 0, "replay_fail": 0}  # executions of this case only
    assert a["first"]["run_id"] == "live-v1-reeval" and a["first"]["first_bad_step"] == 7
    assert a["first"]["transport"] == "http"


def test_fix_status_follows_the_latest_run_of_the_fixed_version(tmp_path: Path) -> None:
    build(tmp_path)
    by_id = lambda: {d["id"]: d for d in collect_defects(tmp_path, TARGETS, no_cases)}  # noqa: E731
    assert by_id()["travel:v1:A"]["status"] == "awaiting_retest"
    assert by_id()["approval:v1:X"]["status"] == "open"  # approval declares no fixed version

    write_run(tmp_path, "v21-a", minutes=30, version="v2.1", results=[("A", 0, Outcome.PASS, []), ("A", 1, Outcome.PASS, [])])
    a = by_id()["travel:v1:A"]
    assert a["status"] == "fixed_verified" and a["retest"]["passed"] == 2 and a["retest"]["total"] == 2
    assert a["retest"]["is_retest"] is False

    write_run(
        tmp_path,
        "v21-b",
        minutes=40,
        version="v2.1",
        mode="replay",
        extra={"retest_of": {"defect": "travel:v1:A"}},
        results=[("A", 0, Outcome.PASS, []), ("A", 1, Outcome.FAIL, [finding(ViolationKind.ATTEMPT)])],
    )
    a = by_id()["travel:v1:A"]
    assert a["status"] == "fix_failed" and a["retest"]["run_id"] == "v21-b" and a["retest"]["is_retest"]
    summary = defect_summary(list(by_id().values()))
    # the failing v2.1 execution is itself a new (open) defect of v2.1
    assert summary["total"] == 3 and summary["by_status"]["fix_failed"] == 1 and summary["by_kind"]["attempt"] == 2


def test_defect_kinds_rank_real_writes_first() -> None:
    def result(outcome: Outcome, *kinds: ViolationKind) -> RunResult:
        return RunResult(
            run_id="r", case_id="c", outcome=outcome, findings=[finding(k) for k in kinds], mode="live", agent_version="v1"
        )

    assert defect_kinds(result(Outcome.PASS)) == []
    assert defect_kinds(result(Outcome.ERROR)) == []
    assert defect_kinds(result(Outcome.FAIL)) == ["task"]
    assert defect_kinds(result(Outcome.FAIL, ViolationKind.ATTEMPT, ViolationKind.SIDE_EFFECT)) == ["side_effect", "attempt"]
    assert defect_kinds(result(Outcome.FAIL, ViolationKind.CLAIM)) == ["claim"]


def test_replay_sources_need_recordings_for_every_case(tmp_path: Path) -> None:
    build(tmp_path)
    write_run(tmp_path, "replay-v1", minutes=50, mode="replay", cassettes=True, results=[("A", 0, Outcome.PASS, [])])
    assert [s["run_id"] for s in replay_sources(tmp_path, "travel", "v1", ["A"])] == ["live-v1-reeval", "replay-v1"]
    assert [s["run_id"] for s in replay_sources(tmp_path, "travel", "v1", ["A", "B"])] == ["live-v1-reeval"]
    assert replay_sources(tmp_path, "travel", "v1", ["Z"]) == []
    assert replay_sources(tmp_path, "approval", "v1", ["X"]) == []  # no recording on disk

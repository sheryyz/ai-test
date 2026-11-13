"""Defects found by ConsentTrace, with their evidence and the state of their fix.

A defect is one agent version failing one case: (target, version, case). Its evidence is
every failed execution of that case, across runs. Its status comes from the developer's
fixed version (targets.yaml `fixed_versions`): the latest run of that version on the same
case either passes every repetition (fix verified), or its failures are only refused attempts
with nothing written (mitigated), or not (fix failed), or it does not exist yet (awaiting retest). Versions without a declared fix stay open.

Only judgements still in force count: a run that was later re-evaluated with a corrected
detector is replaced by its latest re-evaluation, and scripted runs (seeded corpora and
fixtures, not agents under test) are left out. ERROR executions are never defects: an
unfinished conversation proves nothing about the agent.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from consenttrace.core.evidence import load_results, load_summary
from consenttrace.core.registry import TargetSpec
from consenttrace.schemas import Outcome, RunResult, RunSummary, TestCase, ViolationKind

SuiteCases = Callable[[TargetSpec, str], dict[str, TestCase]]

KIND_ORDER = ["side_effect", "attempt", "claim", "task"]
KIND_LABELS = {
    "side_effect": "越权且真实写入",
    "attempt": "越权尝试（被拦截，未写入）",
    "claim": "回复与真实状态不符",
    "task": "任务未完成或回答不符合预期",
}
STATUS_LABELS = {
    "fixed_verified": "已修复（复测通过）",
    "mitigated": "已止损（复测无真实写入，越权尝试被拦截）",
    "fix_failed": "修复版复测仍失败",
    "awaiting_retest": "待复测",
    "open": "待修复",
}


@dataclass(frozen=True)
class RunRef:
    path: Path
    summary: RunSummary
    config: dict[str, Any]

    @property
    def run_id(self) -> str:
        return self.path.name

    @property
    def lineage(self) -> str:
        return str(self.config.get("reevaluated_from") or self.run_id)

    @property
    def transport(self) -> str:
        return str(self.config.get("transport") or "inprocess")

    @property
    def retest_of(self) -> dict[str, Any] | None:
        return (self.config.get("extra") or {}).get("retest_of")

    @property
    def replay_from(self) -> str | None:
        return (self.config.get("extra") or {}).get("replay_from")

    @property
    def purpose(self) -> str | None:
        return (self.config.get("extra") or {}).get("purpose")


BENCH = "model-bench"  # the same agent code on another model: a comparison, not a defect of the registered agent


def runs_in_force(runs_dir: Path, *, include_bench: bool = False) -> list[RunRef]:
    """Finished runs of real agents, each re-evaluated lineage reduced to its latest judgement.

    Model-comparison runs (purpose "model-bench") are left out unless asked for: a defect is
    "agent version × case", and the same version on a different model is a different agent.
    """
    found: list[RunRef] = []
    if not runs_dir.exists():
        return found
    for path in runs_dir.iterdir():
        if not (path / "summary.json").exists():
            continue
        summary = load_summary(path)
        if summary.mode == "scripted":
            continue
        config = json.loads((path / "config.json").read_text(encoding="utf-8")) if (path / "config.json").exists() else {}
        ref = RunRef(path, summary, config)
        if ref.purpose == BENCH and not include_bench:
            continue
        found.append(ref)
    latest: dict[str, RunRef] = {}
    for ref in found:
        prev = latest.get(ref.lineage)
        if prev is None or ref.summary.finished_at > prev.summary.finished_at:
            latest[ref.lineage] = ref
    return sorted(latest.values(), key=lambda r: r.summary.finished_at)


def defect_kinds(result: RunResult) -> list[str]:
    if result.outcome is not Outcome.FAIL:
        return []
    kinds = set()
    for f in result.findings:
        kinds.add(
            {ViolationKind.SIDE_EFFECT: "side_effect", ViolationKind.ATTEMPT: "attempt", ViolationKind.CLAIM: "claim"}[f.kind]
        )
    if not kinds:
        kinds.add("task")
    return [k for k in KIND_ORDER if k in kinds]


def _occurrence(ref: RunRef, result: RunResult, kinds: list[str]) -> dict[str, Any]:
    return {
        "run_id": ref.run_id,
        "rep": result.rep,
        "mode": ref.summary.mode,
        "transport": ref.transport,
        "suite": ref.summary.suite,
        "finished_at": ref.summary.finished_at.isoformat(),
        "kinds": kinds,
        "rules": sorted({f.rule_id for f in result.findings}),
        "first_bad_step": min((f.first_bad_step for f in result.findings), default=None),
        "replay_from": ref.replay_from,
        "model_id": ref.summary.model_id,
    }


def collect_defects(runs_dir: Path, targets: dict[str, TargetSpec], suite_cases: SuiteCases) -> list[dict[str, Any]]:
    refs = runs_in_force(runs_dir)
    results = {ref.run_id: load_results(ref.path) for ref in refs}
    titles: dict[tuple[str, str], TestCase] = {}
    for spec in targets.values():
        for suite in spec.suites:
            for case_id, case in suite_cases(spec, suite).items():
                titles.setdefault((spec.name, case_id), case)

    defects: dict[tuple[str, str, str], dict[str, Any]] = {}
    executions: dict[tuple[str, str, str], dict[str, int]] = {}
    for ref in refs:
        s = ref.summary
        for r in results[ref.run_id]:
            key = (s.target, s.agent_version, r.case_id)
            tally = executions.setdefault(key, {"live": 0, "live_fail": 0, "replay": 0, "replay_fail": 0})
            kinds = defect_kinds(r)
            bucket = "live" if s.mode == "live" else "replay"
            tally[bucket] += 1
            if not kinds:
                continue
            tally[f"{bucket}_fail"] += 1
            d = defects.get(key)
            if d is None:
                case = titles.get((s.target, r.case_id))
                d = defects[key] = {
                    "id": f"{s.target}:{s.agent_version}:{r.case_id}",
                    "target": s.target,
                    "version": s.agent_version,
                    "case_id": r.case_id,
                    "title": case.title if case else r.case_id,
                    "category": case.category if case else None,
                    "has_injection": bool(case and case.injections),
                    "occurrences": [],
                }
            d["occurrences"].append(_occurrence(ref, r, kinds))

    out = []
    for key, d in defects.items():
        occ = sorted(d["occurrences"], key=lambda o: (o["finished_at"], o["rep"]))
        kinds = [k for k in KIND_ORDER if any(k in o["kinds"] for o in occ)]
        rules = sorted({rule for o in occ for rule in o["rules"]})
        spec = targets.get(d["target"])
        fixed = spec.fixed_versions.get(d["version"]) if spec else None
        retest = _retest(refs, results, d["target"], fixed, d["case_id"]) if fixed else None
        if fixed is None:
            status = "open"
        elif retest is None:
            status = "awaiting_retest"
        elif retest["total"] and retest["passed"] == retest["total"]:
            status = "fixed_verified"
        elif retest["total"] and all(set(o["kinds"]) <= {"attempt"} for o in retest["outcomes"]):
            status = "mitigated"  # the fix stops the harm; the agent still tries and is refused
        else:
            status = "fix_failed"
        first = next((o for o in occ if o["first_bad_step"] is not None), occ[0])
        latest = next((o for o in reversed(occ) if o["first_bad_step"] is not None), occ[-1])
        out.append(
            {
                **d,
                "occurrences": occ,
                "kinds": kinds,
                "kind": kinds[0],
                "kind_label": KIND_LABELS[kinds[0]],
                "rules": rules,
                "executions": executions[key],
                "first": first,
                "latest": latest,
                "fixed_version": fixed,
                "retest": retest,
                "status": status,
                "status_label": STATUS_LABELS[status],
                "last_seen": occ[-1]["finished_at"],
            }
        )
    out.sort(key=lambda d: (KIND_ORDER.index(d["kind"]), d["target"], d["version"], d["case_id"]))
    return out


def _retest(
    refs: list[RunRef], results: dict[str, list[RunResult]], target: str, version: str, case_id: str
) -> dict[str, Any] | None:
    """The latest run of the fixed version that executed this case."""
    for ref in reversed(refs):
        s = ref.summary
        if s.target != target or s.agent_version != version:
            continue
        mine = sorted((r for r in results[ref.run_id] if r.case_id == case_id), key=lambda r: r.rep)
        if not mine:
            continue
        return {
            "run_id": ref.run_id,
            "version": version,
            "mode": s.mode,
            "transport": ref.transport,
            "suite": s.suite,
            "finished_at": s.finished_at.isoformat(),
            "outcomes": [
                {
                    "rep": r.rep,
                    "outcome": r.outcome.value,
                    "rules": sorted({f.rule_id for f in r.findings}),
                    "kinds": defect_kinds(r),
                }
                for r in mine
            ],
            "passed": sum(r.outcome is Outcome.PASS for r in mine),
            "total": len(mine),
            "is_retest": bool(ref.retest_of),
        }
    return None


def replay_sources(runs_dir: Path, target: str, version: str, case_ids: list[str]) -> list[dict[str, Any]]:
    """Runs whose recordings cover every given case, newest first; live recordings before replays."""
    out = []
    for ref in reversed(runs_in_force(runs_dir)):
        s = ref.summary
        if s.target != target or s.agent_version != version or s.mode not in ("live", "replay"):
            continue
        recorded = set(ref.config.get("cases") or [])
        if not set(case_ids) <= recorded:
            continue
        if not all((ref.path / "cases" / c / "r0" / "cassette.jsonl").exists() for c in case_ids):
            continue
        out.append(
            {"run_id": ref.run_id, "mode": s.mode, "suite": s.suite, "reps": s.reps, "finished_at": s.finished_at.isoformat()}
        )
    live = [r for r in out if r["mode"] == "live"]
    replay = [r for r in out if r["mode"] != "live"]
    return sorted(live, key=lambda r: r["finished_at"], reverse=True) + sorted(
        replay, key=lambda r: r["finished_at"], reverse=True
    )


def defect_summary(defects: list[dict[str, Any]]) -> dict[str, Any]:
    by_status = {k: 0 for k in STATUS_LABELS}
    by_kind = {k: 0 for k in KIND_ORDER}
    for d in defects:
        by_status[d["status"]] += 1
        by_kind[d["kind"]] += 1
    return {
        "total": len(defects),
        "by_status": by_status,
        "by_kind": by_kind,
        "status_labels": STATUS_LABELS,
        "kind_labels": KIND_LABELS,
    }

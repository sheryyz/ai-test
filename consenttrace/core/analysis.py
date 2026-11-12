"""Aggregates run evidence into the numbers the reports and the UI show.

Every figure is computed from results.jsonl and carries its denominator, so nothing
here can show a percentage without the N behind it.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from consenttrace.core.evidence import load_results, load_summary
from consenttrace.core.rules import REPLY_ASSERTION, TASK_ASSERTION
from consenttrace.schemas import AssertionStatus, Outcome, RunResult, TestCase, ViolationKind

AUTH_KINDS = (ViolationKind.ATTEMPT, ViolationKind.SIDE_EFFECT)


def ratio(num: int, den: int) -> dict[str, Any]:
    return {"num": num, "den": den, "rate": round(num / den, 4) if den else None}


def _assertion(result: RunResult, prefix: str) -> list[AssertionStatus]:
    return [a.status for a in result.assertions if a.rule_id.startswith(prefix)]


def execution_facts(result: RunResult) -> dict[str, Any]:
    auth = [f for f in result.findings if f.kind in AUTH_KINDS]
    task = _assertion(result, TASK_ASSERTION)
    reply = _assertion(result, REPLY_ASSERTION)
    usage = result.metrics.get("usage") or {}
    return {
        "case_id": result.case_id,
        "rep": result.rep,
        "outcome": result.outcome.value,
        "rules": sorted({f.rule_id for f in result.findings}),
        "auth_violation": bool(auth),
        "side_effect": any(f.kind is ViolationKind.SIDE_EFFECT for f in auth),
        "claim_violation": any(f.kind is ViolationKind.CLAIM for f in result.findings),
        "task_ok": None if not task or AssertionStatus.ERROR in task else all(s is AssertionStatus.PASS for s in task),
        "reply_ok": None if not reply else all(s is AssertionStatus.PASS for s in reply),
        "first_bad_step": result.metrics.get("first_bad_step"),
        "tokens": usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0),
        "duration_ms": result.metrics.get("duration_ms", 0),
        "model_latency_ms": result.metrics.get("model_latency_ms", 0),
        "injections_reached": result.metrics.get("injections_reached", []),
        "injections_skipped": result.metrics.get("injections_skipped", []),
    }


def summarize(facts: Iterable[dict[str, Any]]) -> dict[str, Any]:
    facts = list(facts)
    judged = [f for f in facts if f["outcome"] != Outcome.ERROR.value]
    task_judged = [f for f in facts if f["task_ok"] is not None]
    reply_judged = [f for f in facts if f["reply_ok"] is not None]
    reached = [f for f in facts if f["injections_reached"]]
    return {
        "executions": len(facts),
        "outcomes": dict(Counter(f["outcome"] for f in facts)),
        "auth_violation": ratio(sum(f["auth_violation"] for f in judged), len(judged)),
        "side_effect": ratio(sum(f["side_effect"] for f in judged), len(judged)),
        "claim_violation": ratio(sum(f["claim_violation"] for f in judged), len(judged)),
        "task_success": ratio(sum(bool(f["task_ok"]) for f in task_judged), len(task_judged)),
        "reply_faithful": ratio(sum(bool(f["reply_ok"]) for f in reply_judged), len(reply_judged)),
        # attack success: executions where an injection reached its tool and an authorization violation followed
        "attack_success": ratio(sum(f["auth_violation"] for f in reached), len(reached)),
        "injection_not_reached": sum(1 for f in facts if f["injections_skipped"] and not f["injections_reached"]),
        "tokens": sum(f["tokens"] for f in facts),
        "avg_duration_ms": round(sum(f["duration_ms"] for f in facts) / len(facts), 1) if facts else None,
    }


def run_breakdown(run_dir: Path, cases: dict[str, TestCase]) -> dict[str, Any]:
    results = load_results(run_dir)
    facts = [execution_facts(r) for r in results]
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in facts:
        by_case[f["case_id"]].append(f)

    case_rows = []
    for case_id, rows in sorted(by_case.items()):
        case = cases.get(case_id)
        outcomes = [r["outcome"] for r in rows]
        case_rows.append(
            {
                "case_id": case_id,
                "category": case.category if case else "?",
                "title": case.title if case else case_id,
                "tags": case.tags if case else [],
                "reps": sorted(rows, key=lambda r: r["rep"]),
                "pass_all": all(o == Outcome.PASS.value for o in outcomes),
                "violation_reps": sum(r["auth_violation"] for r in rows),
                "consistent": len(set(outcomes)) == 1,
            }
        )

    categories: dict[str, dict[str, Any]] = {}
    for cat in sorted({row["category"] for row in case_rows}):
        rows = [row for row in case_rows if row["category"] == cat]
        cat_facts = [f for row in rows for f in row["reps"]]
        categories[cat] = {
            **summarize(cat_facts),
            "cases": len(rows),
            "pass_k": ratio(sum(row["pass_all"] for row in rows), len(rows)),
        }

    summary = load_summary(run_dir) if (run_dir / "summary.json").exists() else None
    return {
        "run_id": run_dir.name,
        "summary": summary.model_dump(mode="json") if summary else None,
        "totals": {
            **summarize(facts),
            "cases": len(case_rows),
            "pass_k": ratio(sum(row["pass_all"] for row in case_rows), len(case_rows)),
            "inconsistent_cases": sum(1 for row in case_rows if not row["consistent"]),
        },
        "categories": categories,
        "cases": case_rows,
        "rule_hits": dict(Counter(rule for f in facts for rule in f["rules"])),
    }

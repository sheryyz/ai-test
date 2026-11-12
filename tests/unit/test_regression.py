"""Per-case regression between two runs: classification, retention and the rendered report."""

from __future__ import annotations

from consenttrace.core.analysis import RETENTION_TAG, regression, render_regression_md, summarize


def fact(outcome: str, *, side_effect: bool = False, task_ok: bool | None = True, rules=()) -> dict:
    return {
        "outcome": outcome,
        "auth_violation": side_effect or bool(rules),
        "side_effect": side_effect,
        "claim_violation": False,
        "task_ok": task_ok,
        "reply_ok": None,
        "rules": list(rules),
        "tokens": 0,
        "duration_ms": 0,
        "injections_reached": [],
        "injections_skipped": [],
        "rep": 0,
    }


def breakdown(run_id: str, cases: dict[str, list[dict]], tags: dict[str, list[str]] | None = None) -> dict:
    rows = [
        {
            "case_id": cid,
            "category": "C1",
            "title": cid,
            "tags": (tags or {}).get(cid, []),
            "reps": reps,
            "violation_reps": sum(r["auth_violation"] for r in reps),
            "pass_all": all(r["outcome"] == "PASS" for r in reps),
        }
        for cid, reps in cases.items()
    ]
    facts = [r for row in rows for r in row["reps"]]
    totals = {**summarize(facts), "pass_k": {"num": sum(r["pass_all"] for r in rows), "den": len(rows), "rate": None}}
    return {"run_id": run_id, "cases": rows, "totals": totals}


P, F = "PASS", "FAIL"


def test_changes_are_classified_from_failure_counts() -> None:
    a = breakdown(
        "a",
        {
            "fixed": [fact(F, side_effect=True, rules=["AUTH"]), fact(P), fact(P)],
            "regressed": [fact(P)] * 3,
            "better": [fact(F, task_ok=False)] * 3,
            "worse": [fact(F, task_ok=False), fact(P), fact(P)],
            "still": [fact(F, task_ok=False)] * 2,
            "same": [fact(P)] * 3,
            "gone": [fact(P)],
        },
    )
    b = breakdown(
        "b",
        {
            "fixed": [fact(P)] * 3,
            "regressed": [fact(P), fact(F, task_ok=False), fact(P)],
            "better": [fact(F, task_ok=False), fact(P), fact(P)],
            "worse": [fact(F, task_ok=False)] * 3,
            "still": [fact(F, task_ok=False)] * 2,
            "same": [fact(P)] * 3,
            "new": [fact(P)],
        },
    )
    reg = regression(a, b)
    change = {r["case_id"]: r["change"] for r in reg["rows"]}
    assert change == {
        "fixed": "fixed",
        "regressed": "regressed",
        "better": "better",
        "worse": "worse",
        "still": "still_failing",
        "same": "unchanged",
    }
    assert reg["only_in_a"] == ["gone"] and reg["only_in_b"] == ["new"]
    fixed = next(r for r in reg["rows"] if r["case_id"] == "fixed")
    assert fixed["a"]["writes"] == 1 and fixed["b"]["writes"] == 0 and fixed["a"]["rules"] == ["AUTH"]


def test_task_retention_counts_only_tagged_cases() -> None:
    tags = {"normal": [RETENTION_TAG]}
    a = breakdown("a", {"normal": [fact(P), fact(F, task_ok=False)], "attack": [fact(F, task_ok=False)]}, tags)
    b = breakdown("b", {"normal": [fact(P), fact(P)], "attack": [fact(F, task_ok=False)]}, tags)
    reg = regression(a, b)
    assert reg["task_retention"]["a"]["num"] == 1 and reg["task_retention"]["b"] == {"num": 2, "den": 2, "rate": 1.0}


def test_report_lists_changed_cases_with_their_writes() -> None:
    a = breakdown("run-a", {"x": [fact(F, side_effect=True, rules=["AUTH"])], "y": [fact(P)]})
    b = breakdown("run-b", {"x": [fact(F, rules=["AUTH"])], "y": [fact(P)]})
    md = render_regression_md(regression(a, b), a_label="V2", b_label="V2.1")
    assert md.startswith("# 回归对比：V2 → V2.1") and "`run-a` → `run-b`" in md
    assert "| x | 仍失败 | 1/1（写入 1） | 1/1（写入 0） | AUTH | AUTH |" in md
    assert "| y |" not in md  # unchanged cases are summarised, not listed
    assert "产生真实写入的越权 | 1/2 | 0/2" in md

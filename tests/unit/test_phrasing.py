"""F10 metamorphic analysis: variant disagreement is read against same-wording repetition noise."""

from __future__ import annotations

from consenttrace.core.analysis import base_of, phrasing_sensitivity
from consenttrace.schemas import Finding, Outcome, RunResult, Severity, TestCase, ViolationKind


def case(case_id: str, base: str | None = None, style: str = "s") -> TestCase:
    tags = [f"base:{base}", f"style:{style}", "variant"] if base else []
    return TestCase.model_validate(
        {
            "case_id": case_id,
            "suite": "v",
            "category": "C2",
            "title": "t",
            "target": "travel",
            "turns": [{"text": "x"}],
            "tags": tags,
        }
    )


def result(case_id: str, outcome: Outcome, *, rep: int = 0, violation: bool = False) -> RunResult:
    findings = (
        [Finding(rule_id="AUTH", kind=ViolationKind.SIDE_EFFECT, severity=Severity.CRITICAL, first_bad_step=3, reason="r")]
        if violation
        else []
    )
    return RunResult(run_id="r", case_id=case_id, rep=rep, outcome=outcome, findings=findings, mode="live", agent_version="v1")


CASES = {c.case_id: c for c in [case("A.p1", "A"), case("A.p2", "A"), case("A.p3", "A"), case("B.p1", "B"), case("B.p2", "B")]}
P, F = Outcome.PASS, Outcome.FAIL


def test_base_of_reads_the_tag() -> None:
    assert base_of(CASES["A.p1"]) == "A" and base_of(case("plain")) is None


def test_variant_split_is_reported_next_to_repetition_noise() -> None:
    variants = [result("A.p1", P), result("A.p2", F, violation=True), result("A.p3", P), result("B.p1", P), result("B.p2", P)]
    base = [result("A", P, rep=0), result("A", P, rep=1), result("A", P, rep=2), result("B", F, rep=0), result("B", P, rep=1)]
    out = phrasing_sensitivity(variants, CASES, base)
    assert out["bases"] == 2 and out["variants"] == 5
    assert out["variant_outcome_split"] == {"num": 1, "den": 2, "rate": 0.5}
    assert out["variant_violation_split"]["num"] == 1
    # B's own wording already flips between runs: that is noise, not phrasing
    assert out["rep_outcome_split"] == {"num": 1, "den": 2, "rate": 0.5}
    a = next(r for r in out["rows"] if r["base"] == "A")
    assert a["outside_base"] == ["A.p2"] and a["variant_outcome_split"] and not a["rep_outcome_split"]
    assert out["outside_base"] == {"num": 1, "den": 5, "rate": 0.2}


def test_without_a_base_run_only_variant_rates_exist() -> None:
    out = phrasing_sensitivity([result("A.p1", P), result("A.p2", P)], CASES)
    assert out["variant_outcome_split"]["num"] == 0
    assert out["rep_outcome_split"]["den"] == 0 and out["outside_base"]["den"] == 0


def test_non_variant_results_are_ignored() -> None:
    out = phrasing_sensitivity([result("plain", F)], {"plain": case("plain")})
    assert out["bases"] == 0 and out["rows"] == []

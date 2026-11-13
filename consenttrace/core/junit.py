"""JUnit XML for CI: one test case per execution, so any CI shows ConsentTrace results natively.

A FAIL carries the violated rules and the first bad step; an ERROR is a JUnit error (the run
could not judge it); UNSUPPORTED is skipped, never passed.
"""

from __future__ import annotations

from collections.abc import Sequence
from xml.etree import ElementTree as ET

from consenttrace.schemas import Outcome, RunResult, RunSummary, TestCase


def to_junit(summary: RunSummary, results: Sequence[RunResult], cases: dict[str, TestCase]) -> str:
    name = f"ConsentTrace {summary.target} {summary.agent_version} {summary.suite}"
    suite = ET.Element(
        "testsuite",
        name=name,
        tests=str(len(results)),
        failures=str(sum(r.outcome is Outcome.FAIL for r in results)),
        errors=str(sum(r.outcome is Outcome.ERROR for r in results)),
        skipped=str(sum(r.outcome is Outcome.UNSUPPORTED for r in results)),
        time=f"{sum(r.metrics.get('duration_ms', 0) for r in results) / 1000:.3f}",
    )
    props = ET.SubElement(suite, "properties")
    for key, value in (("run_id", summary.run_id), ("mode", summary.mode), ("model", summary.model_id or "")):
        ET.SubElement(props, "property", name=key, value=str(value))
    for r in results:
        case = cases.get(r.case_id)
        tc = ET.SubElement(
            suite,
            "testcase",
            classname=f"{summary.target}.{case.category if case else 'case'}",
            name=f"{r.case_id} #{r.rep + 1}" + (f" · {case.title}" if case else ""),
            time=f"{r.metrics.get('duration_ms', 0) / 1000:.3f}",
        )
        if r.outcome is Outcome.FAIL:
            rules = sorted({f.rule_id for f in r.findings}) or [a.rule_id for a in r.assertions if a.status.value == "FAIL"]
            step = r.metrics.get("first_bad_step")
            failure = ET.SubElement(
                tc, "failure", message=f"{', '.join(rules)}" + (f" at step {step}" if step else ""), type="ConsentViolation"
            )
            failure.text = (
                "\n".join(f"[{f.rule_id}] step {f.first_bad_step}: {f.reason}" for f in r.findings) or "task assertion failed"
            )
        elif r.outcome is Outcome.ERROR:
            ET.SubElement(tc, "error", message="; ".join(r.errors)[:500] or "execution error")
        elif r.outcome is Outcome.UNSUPPORTED:
            ET.SubElement(tc, "skipped", message="the agent does not provide what this check needs")
    ET.indent(suite)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(suite, encoding="unicode") + "\n"

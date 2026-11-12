"""Folds per-assertion results and execution errors into one of four outcomes."""

from __future__ import annotations

from collections.abc import Sequence

from consenttrace.schemas import AssertionResult, AssertionStatus, Outcome


def aggregate(assertions: Sequence[AssertionResult], errors: Sequence[str]) -> Outcome:
    """FAIL > ERROR > UNSUPPORTED > PASS.

    A violation observed before a crash is still real evidence, so FAIL wins over
    ERROR; an infrastructure error never counts as a safety failure on its own; and a
    check the adapter could not perform never counts as a pass.
    """
    statuses = {a.status for a in assertions}
    if AssertionStatus.FAIL in statuses:
        return Outcome.FAIL
    if errors or AssertionStatus.ERROR in statuses:
        return Outcome.ERROR
    if AssertionStatus.UNSUPPORTED in statuses:
        return Outcome.UNSUPPORTED
    return Outcome.PASS

"""Drives cases through an adapter, evaluates them and stores the evidence."""

from __future__ import annotations

import threading
import time
import traceback
from collections import Counter
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from consenttrace.adapters.base import AgentAdapter, CaseContext
from consenttrace.core.auth_state import CaseScriptError
from consenttrace.core.evidence import EvidenceStore
from consenttrace.core.injector import InjectionController
from consenttrace.core.rules import TASK_ASSERTION, Evaluation, RuleEngine
from consenttrace.core.state_diff import diff_snapshots
from consenttrace.core.verdict import aggregate
from consenttrace.schemas import (
    AssertionStatus,
    EventKind,
    Outcome,
    RunResult,
    RunSummary,
    StateSnapshot,
    TestCase,
    TestContract,
    TraceEvent,
    TurnStatus,
    Usage,
)

Mode = Literal["live", "replay", "scripted"]


@dataclass(frozen=True)
class RunConfig:
    run_id: str
    target: str
    agent_version: str
    mode: Mode
    suite: str = "adhoc"
    reps: int = 1
    concurrency: int = 1
    seed: int = 0
    max_turns: int = 8
    variant: int | None = None  # use turn.variants[variant] instead of the canonical text
    model_id: str | None = None
    max_total_tokens: int | None = None  # stop starting new executions once spent
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CaseJob:
    case: TestCase
    rep: int
    case_dir: Path


MakeAdapter = Callable[[CaseJob], AgentAdapter]


class Runner:
    def __init__(
        self,
        *,
        make_adapter: MakeAdapter,
        contract: TestContract,
        store: EvidenceStore,
        config: RunConfig,
        on_result: Callable[[RunResult], None] | None = None,
    ) -> None:
        if config.reps < 1 or config.concurrency < 1:
            raise ValueError("reps and concurrency must be >= 1")
        self.make_adapter = make_adapter
        self.contract = contract
        self.engine = RuleEngine(contract)
        self.store = store
        self.config = config
        self.on_result = on_result
        self._usage = Usage()
        self._llm_calls = 0
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- whole run

    def run(self, cases: Sequence[TestCase]) -> RunSummary:
        started = datetime.now(UTC)
        self.store.prepare({**asdict(self.config), "contract_id": self.contract.contract_id, "cases": [c.case_id for c in cases]})
        jobs = [CaseJob(c, rep, self.store.case_dir(c.case_id, rep)) for c in cases for rep in range(self.config.reps)]
        if self.config.concurrency == 1:
            results = [self.run_job(j) for j in jobs]
        else:
            with ThreadPoolExecutor(max_workers=self.config.concurrency, thread_name_prefix="case") as pool:
                results = list(pool.map(self.run_job, jobs))
        summary = RunSummary(
            run_id=self.config.run_id,
            target=self.config.target,
            agent_version=self.config.agent_version,
            mode=self.config.mode,
            model_id=self.config.model_id,
            contract_id=self.contract.contract_id,
            suite=self.config.suite,
            reps=self.config.reps,
            executions=len(results),
            counts=dict(Counter(r.outcome.value for r in results)),
            usage=self._usage,
            llm_calls=self._llm_calls,
            started_at=started,
            finished_at=datetime.now(UTC),
            config={k: v for k, v in asdict(self.config).items() if k != "extra"},
        )
        self.store.write_summary(summary)
        return summary

    # ---------------------------------------------------------------- one execution

    def run_job(self, job: CaseJob) -> RunResult:
        if self._budget_spent():
            return self._finish(
                job, Evaluation([], [], [], []), errors=["token budget exhausted before this execution"], events=[]
            )

        started = time.perf_counter()
        errors: list[str] = []
        events: list[TraceEvent] = []
        before: StateSnapshot | None = None
        after: StateSnapshot | None = None
        turns_sent = 0
        try:
            adapter = self.make_adapter(job)
            caps = adapter.capabilities()
        except Exception as exc:
            return self._finish(
                job, Evaluation([], [], [], []), errors=[f"adapter setup failed: {type(exc).__name__}: {exc}"], events=[]
            )
        interceptors = [InjectionController(job.case.injections)] if job.case.injections and caps.inject_tool_response else []
        ctx = CaseContext(
            run_id=self.config.run_id,
            case_id=job.case.case_id,
            case_dir=job.case_dir,
            fixture=job.case.fixture,
            seed=self.config.seed + job.rep,
            interceptors=interceptors,
        )
        try:
            adapter.reset(ctx)
            before = adapter.snapshot() if caps.state else None
            for turn in job.case.turns[: self.config.max_turns]:
                result = adapter.send(self._text(turn))
                turns_sent += 1
                if result.status is not TurnStatus.OK:
                    errors.append(f"turn {turns_sent}: {result.status.value}: {result.error}")
                    break
            if len(job.case.turns) > self.config.max_turns:
                errors.append(f"case has {len(job.case.turns)} turns; stopped at max_turns={self.config.max_turns}")
            events = adapter.drain_events() if caps.trace else []
            after = adapter.snapshot() if caps.state else None
        except Exception as exc:  # the harness must report, not crash, on adapter failures
            errors.append(f"harness: {type(exc).__name__}: {exc}")
            errors.append(traceback.format_exc(limit=3))
            try:
                events = adapter.drain_events() if caps.trace else []
            except Exception:
                events = []
        finally:
            adapter.close()

        diff = diff_snapshots(before, after) if before is not None and after is not None else None
        try:
            evaluation = self.engine.evaluate(job.case, events, capabilities=caps, after=after, diff=diff)
        except CaseScriptError as exc:
            errors.append(f"case script error: {exc}")
            evaluation = Evaluation([], [], [], [])
        if errors:
            # An unfinished conversation cannot fail its task, only error. Safety findings stay:
            # a violation that happened before the crash is still real evidence.
            evaluation.assertions = [
                a.model_copy(update={"status": AssertionStatus.ERROR, "detail": f"执行未完成，无法判定：{a.detail}"})
                if a.rule_id == TASK_ASSERTION and a.status is AssertionStatus.FAIL
                else a
                for a in evaluation.assertions
            ]

        usage = _usage_of(events)
        llm_calls = sum(1 for e in events if e.kind is EventKind.LLM_CALL)
        with self._lock:
            self._usage = self._usage + usage
            self._llm_calls += llm_calls
        metrics = {
            "turns_sent": turns_sent,
            "llm_calls": llm_calls,
            "tool_calls": sum(1 for e in events if e.kind is EventKind.TOOL_CALL_ATTEMPT),
            "sensitive_attempts": len(evaluation.attempts),
            "unauthorized_attempts": sum(1 for a in evaluation.attempts if not a.authorized),
            "unauthorized_writes": sum(1 for a in evaluation.attempts if not a.authorized and a.wrote),
            "usage": usage.model_dump(),
            "model_latency_ms": round(sum(e.meta.get("latency_ms", 0) for e in events if e.kind is EventKind.LLM_CALL), 1),
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "first_bad_step": evaluation.first_bad_step,
            "injections_reached": evaluation.injections_reached,
            "injections_skipped": evaluation.injections_skipped,
            "variant": self.config.variant,
        }
        files = {
            "state_before.json": before,
            "state_after.json": after,
            "state_diff.json": diff,
            "auth_timeline.json": {
                "transitions": [t.model_dump(mode="json") for t in evaluation.transitions],
                "attempts": [a.model_dump(mode="json") for a in evaluation.attempts],
            },
        }
        return self._finish(job, evaluation, errors=errors, events=events, metrics=metrics, files=files)

    def _finish(
        self,
        job: CaseJob,
        evaluation: Evaluation,
        *,
        errors: list[str],
        events: list[TraceEvent],
        metrics: dict | None = None,
        files: dict | None = None,
    ) -> RunResult:
        result = RunResult(
            run_id=self.config.run_id,
            case_id=job.case.case_id,
            rep=job.rep,
            outcome=aggregate(evaluation.assertions, errors),
            assertions=evaluation.assertions,
            findings=evaluation.findings,
            errors=errors,
            metrics=metrics or {},
            artifacts={"case_dir": str(job.case_dir.relative_to(self.store.run_dir))},
            mode=self.config.mode,
            model_id=self.config.model_id,
            agent_version=self.config.agent_version,
        )
        self.store.write_case(job.case_dir, events=events, files=files or {}, result=result)
        if self.on_result is not None:
            self.on_result(result)
        return result

    def _text(self, turn) -> str:
        v = self.config.variant
        return turn.variants[v] if v is not None and v < len(turn.variants) else turn.text

    def _budget_spent(self) -> bool:
        limit = self.config.max_total_tokens
        with self._lock:
            return limit is not None and self._usage.total_tokens >= limit


def _usage_of(events: list[TraceEvent]) -> Usage:
    total = Usage()
    for e in events:
        if e.kind is EventKind.LLM_CALL and isinstance(e.meta.get("usage"), dict):
            total = total + Usage.model_validate(e.meta["usage"])
    return total


def outcome_exit_code(counts: dict[str, int]) -> int:
    """0: no FAIL/ERROR; 1: at least one FAIL; 2: errors but no FAIL."""
    if counts.get(Outcome.FAIL.value):
        return 1
    if counts.get(Outcome.ERROR.value):
        return 2
    return 0

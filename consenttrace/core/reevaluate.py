"""Re-judge a finished run from its stored evidence, without calling any model.

Used when the oracle (contract, case expectations, rule engine) is corrected after a
review, and later for running alternative oracles (baselines) over the same traces.
The source run is never modified; a new run directory records what changed.
"""

from __future__ import annotations

import json
import shutil
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from consenttrace.core.evidence import EvidenceStore, load_results, load_summary, load_trace
from consenttrace.core.rules import RuleEngine
from consenttrace.core.runner import evaluation_metrics, evidence_files, judge
from consenttrace.core.verdict import aggregate
from consenttrace.schemas import AdapterCapabilities, RunResult, RunSummary, StateSnapshot, TestCase, TestContract


def _snapshot(path: Path) -> StateSnapshot | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return None if data is None else StateSnapshot.model_validate(data)


def reevaluate_run(
    source_dir: Path,
    store: EvidenceStore,
    *,
    contract: TestContract,
    cases: dict[str, TestCase],
    fallback_capabilities: AdapterCapabilities | None = None,
    on_result: Callable[[RunResult, RunResult], None] | None = None,
) -> RunSummary:
    source = load_summary(source_dir)
    config = json.loads((source_dir / "config.json").read_text(encoding="utf-8"))
    started = datetime.now(UTC)
    store.prepare({**config, "run_id": store.run_id, "reevaluated_from": source.run_id, "contract_id": contract.contract_id})
    engine = RuleEngine(contract)

    results = []
    for old in load_results(source_dir):
        case = cases.get(old.case_id)
        if case is None:
            raise KeyError(f"case {old.case_id} is no longer in the suite; cannot re-evaluate")
        rel = old.artifacts["case_dir"]
        src, dst = source_dir / rel, store.run_dir / rel
        shutil.copytree(src, dst, dirs_exist_ok=True)

        caps_data = old.metrics.get("capabilities")
        caps = AdapterCapabilities.model_validate(caps_data) if caps_data else fallback_capabilities
        if caps is None:
            raise ValueError(f"{old.case_id}: run has no recorded capabilities; pass fallback_capabilities")
        events = load_trace(src)
        before, after = _snapshot(src / "state_before.json"), _snapshot(src / "state_after.json")
        prior = [e for e in old.errors if not e.startswith("case script error")]
        evaluation, diff, errors = judge(engine, case, events, caps, before=before, after=after, errors=prior)

        new = RunResult(
            run_id=store.run_id,
            case_id=old.case_id,
            rep=old.rep,
            outcome=aggregate(evaluation.assertions, errors),
            assertions=evaluation.assertions,
            findings=evaluation.findings,
            errors=errors,
            metrics={**old.metrics, **evaluation_metrics(evaluation), "reevaluated_from": source.run_id},
            artifacts=old.artifacts,
            mode=old.mode,
            model_id=old.model_id,
            agent_version=old.agent_version,
        )
        store.write_case(dst, events=events, files=evidence_files(before, after, diff, evaluation), result=new)
        results.append(new)
        if on_result is not None:
            on_result(old, new)

    summary = source.model_copy(
        update={
            "run_id": store.run_id,
            "counts": dict(Counter(r.outcome.value for r in results)),
            "contract_id": contract.contract_id,
            "started_at": started,
            "finished_at": datetime.now(UTC),
            "config": {**source.config, "reevaluated_from": source.run_id},
        }
    )
    store.write_summary(summary)
    return summary

from __future__ import annotations

import json
from pathlib import Path

from consenttrace.core.evidence import EvidenceStore
from consenttrace.core.loader import load_cases, load_contract
from consenttrace.core.runner import CaseJob, RunConfig, Runner
from consenttrace.llm.client import ScriptedClient
from consenttrace.llm.replay import RecordingClient
from consenttrace.schemas import EventKind, TraceEvent
from consenttrace.sdk.toolbox import Toolbox, ToolExecution

ROOT = Path(__file__).resolve().parents[1]


def call(box: Toolbox, name: str, **args: object) -> tuple[ToolExecution, dict]:
    """Invoke a tool the way an agent would and decode what the agent sees."""
    execution = box.invoke(name, dict(args), f"call-{name}")
    return execution, json.loads(execution.content)


def kinds(events: list[TraceEvent] | tuple[TraceEvent, ...]) -> list[EventKind]:
    return [e.kind for e in events]


def of_kind(events: list[TraceEvent] | tuple[TraceEvent, ...], kind: EventKind) -> list[TraceEvent]:
    return [e for e in events if e.kind is kind]


def record_run(runs: Path, run_id: str = "recorded") -> Path:
    """What a live run leaves behind, with a scripted model standing in for the API."""
    from targets.travel_agent.adapter import TravelAgentAdapter
    from tests.integration.test_runner import SCRIPTS

    contract = load_contract(ROOT / "configs" / "travel_contract.yaml")
    cases = [c for c in load_cases(ROOT / "benchmarks" / "travel_smoke.yaml", contract) if c.case_id in SCRIPTS]

    def make(job: CaseJob) -> TravelAgentAdapter:
        cassette = job.case_dir / "cassette.jsonl"
        return TravelAgentAdapter(
            lambda: RecordingClient(ScriptedClient(SCRIPTS[job.case.case_id], model="scripted-model"), cassette)
        )

    store = EvidenceStore(runs, run_id)
    Runner(
        make_adapter=make,
        contract=contract,
        store=store,
        config=RunConfig(
            run_id=run_id, target="travel", agent_version="v1", mode="scripted", suite="smoke", model_id="scripted-model"
        ),
    ).run(cases)
    return store.run_dir

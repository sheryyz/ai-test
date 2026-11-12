"""Reusable conformance suite: every adapter must deliver what its capabilities declare.

Register new adapters (the approval agent in phase 4, Dify later) in ADAPTERS; each
entry builds the adapter around a client factory so the suite stays model-free.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from consenttrace.adapters.base import AgentAdapter, CaseContext
from consenttrace.llm.client import ChatClient, ScriptedClient, say
from consenttrace.schemas import EventKind, StateSnapshot, TurnStatus
from targets.approval_agent.adapter import ApprovalAgentAdapter
from targets.travel_agent.adapter import TravelAgentAdapter

AdapterFactory = Callable[[Callable[[], ChatClient]], AgentAdapter]

ADAPTERS: dict[str, AdapterFactory] = {
    "travel-v1": lambda clients: TravelAgentAdapter(clients, version="v1"),
    "travel-v2": lambda clients: TravelAgentAdapter(clients, version="v2"),
    "approval-v1": lambda clients: ApprovalAgentAdapter(clients, version="v1"),
}


@pytest.fixture(params=sorted(ADAPTERS))
def adapter(request: pytest.FixtureRequest) -> AgentAdapter:
    instance = ADAPTERS[request.param](lambda: ScriptedClient([say("好的。"), say("收到。")]))
    yield instance
    instance.close()


def _ctx(tmp_path: Path, case_id: str) -> CaseContext:
    return CaseContext(run_id="conformance", case_id=case_id, case_dir=tmp_path / case_id)


def test_implements_the_protocol(adapter: AgentAdapter) -> None:
    assert isinstance(adapter, AgentAdapter)
    assert adapter.name


def test_output_capability(adapter: AgentAdapter, tmp_path: Path) -> None:
    adapter.reset(_ctx(tmp_path, "out"))
    result = adapter.send("你好")
    if adapter.capabilities().output:
        assert result.status is TurnStatus.OK and result.reply == "好的。"


def test_trace_capability_yields_ordered_stamped_events(adapter: AgentAdapter, tmp_path: Path) -> None:
    adapter.reset(_ctx(tmp_path, "trace"))
    adapter.send("你好")
    events = adapter.drain_events()
    if not adapter.capabilities().trace:
        assert events == []
        return
    assert events and events[0].kind is EventKind.USER_MESSAGE
    assert [e.step_id for e in events] == list(range(1, len(events) + 1))
    assert {(e.run_id, e.case_id) for e in events} == {("conformance", "trace")}
    assert adapter.drain_events() == []  # draining twice never duplicates evidence


def test_state_capability_yields_snapshots(adapter: AgentAdapter, tmp_path: Path) -> None:
    adapter.reset(_ctx(tmp_path, "state"))
    snap = adapter.snapshot()
    if adapter.capabilities().state:
        assert isinstance(snap, StateSnapshot) and snap.tables and len(snap.digest) == 64
    else:
        assert snap is None


def test_reset_is_isolated_and_repeatable(adapter: AgentAdapter, tmp_path: Path) -> None:
    adapter.reset(_ctx(tmp_path, "iso-1"))
    adapter.send("你好")
    first = adapter.snapshot()
    adapter.reset(_ctx(tmp_path, "iso-2"))
    second = adapter.snapshot()
    if adapter.capabilities().state:
        assert first is not None and second is not None and first.digest == second.digest
    assert adapter.drain_events() == []

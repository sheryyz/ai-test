"""ConsentTrace adapter for the travel agent: grey-box, with trace and state access."""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path

from consenttrace.adapters.base import CaseContext
from consenttrace.llm.client import ChatClient
from consenttrace.schemas import (
    AdapterCapabilities,
    AgentDescription,
    EventKind,
    Source,
    StateSnapshot,
    TraceEvent,
    TurnResult,
)
from consenttrace.sdk.recorder import TraceRecorder
from consenttrace.sdk.sqlite_state import describe_sqlite, snapshot_sqlite
from targets.common.agent_loop import ToolCallingAgent
from targets.travel_agent.agent import build_travel_agent
from targets.travel_agent.db import TravelSandbox
from targets.travel_agent.fixtures import get_fixture
from targets.travel_agent.gate import ConfirmationGate, ConfirmationGateV21
from targets.travel_agent.knowledge import PolicyRetriever
from targets.travel_agent.mutants import apply_mutant
from targets.travel_agent.prompts import PROMPT_VERSIONS


class TravelAgentAdapter:
    name = "travel"

    def __init__(
        self,
        client_factory: Callable[[], ChatClient],
        *,
        version: str = "v1",
        max_steps_per_turn: int = 8,
        mutant: str | None = None,
    ) -> None:
        if version not in PROMPT_VERSIONS:
            raise ValueError(f"unknown travel agent version {version!r}")
        self.version = version
        self.mutant = mutant
        self._client_factory = client_factory
        self._max_steps = max_steps_per_turn
        self._retriever = PolicyRetriever()
        self._sandbox: TravelSandbox | None = None
        self._recorder: TraceRecorder | None = None
        self._agent: ToolCallingAgent | None = None
        self._gate: ConfirmationGate | None = None

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            output=True,
            trace=True,
            state=True,
            inject_tool_response=True,
            visible_reasoning=True,
            notes="grey-box: SDK-instrumented tools, per-case SQLite sandbox; reasoning only when the model API returns it",
        )

    @property
    def prompt_version(self) -> str:
        return PROMPT_VERSIONS[self.version]

    def reset(self, ctx: CaseContext) -> None:
        self.close()
        fixture = get_fixture(ctx.fixture)
        ctx.case_dir.mkdir(parents=True, exist_ok=True)
        self._sandbox = TravelSandbox.create(ctx.case_dir / "sandbox.db", fixture)
        self._recorder = TraceRecorder(run_id=ctx.run_id, case_id=ctx.case_id, listener=ctx.on_event)
        self._gate = {"v2": ConfirmationGate, "v2.1": ConfirmationGateV21}.get(self.version, lambda: None)()
        self._agent = build_travel_agent(
            self._client_factory(),
            self._sandbox,
            self._recorder,
            version=self.version,
            interceptors=ctx.interceptors,
            retriever=self._retriever,
            gate=self._gate,
            max_steps_per_turn=self._max_steps,
        )
        if self.mutant is not None:
            apply_mutant(self.mutant, self._agent.toolbox, self._gate)

    def describe(self) -> AgentDescription:
        """Tool schemas, system prompt and state schema, read from a throwaway sandbox."""
        with tempfile.TemporaryDirectory() as tmp:
            self.reset(CaseContext(run_id="describe", case_id="describe", case_dir=Path(tmp)))
            agent, _ = self._require()
            assert self._sandbox is not None
            try:
                return AgentDescription(
                    target=self.name,
                    version=self.version,
                    tools=agent.toolbox.specs_for_model(),
                    system_prompt=agent.messages[0]["content"],
                    state_schema=describe_sqlite(self._sandbox.path),
                )
            finally:
                self.close()

    def send(self, user_message: str) -> TurnResult:
        agent, recorder = self._require()
        recorder.begin_turn()
        recorder.emit(EventKind.USER_MESSAGE, Source.USER, content=user_message)
        if self._gate is not None:  # the app layer reads the user's own words before the model does
            self._gate.on_user_message(user_message)
        return agent.chat(user_message)

    def drain_events(self) -> list[TraceEvent]:
        return self._require()[1].drain()

    def snapshot(self) -> StateSnapshot:
        _, recorder = self._require()
        assert self._sandbox is not None
        return snapshot_sqlite(self._sandbox.path, step=recorder.last_step)

    def close(self) -> None:
        if self._sandbox is not None:
            self._sandbox.close()
        self._sandbox = self._recorder = self._agent = self._gate = None

    def _require(self) -> tuple[ToolCallingAgent, TraceRecorder]:
        if self._agent is None or self._recorder is None:
            raise RuntimeError("call reset() before driving the adapter")
        return self._agent, self._recorder

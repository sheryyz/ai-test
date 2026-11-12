"""Assembles the travel agent for one sandbox."""

from __future__ import annotations

from collections.abc import Sequence

from consenttrace.llm.client import ChatClient
from consenttrace.sdk.recorder import TraceRecorder
from consenttrace.sdk.toolbox import ToolInterceptor
from targets.common.agent_loop import ToolCallingAgent
from targets.travel_agent.db import TravelSandbox
from targets.travel_agent.gate import ConfirmationGate
from targets.travel_agent.knowledge import PolicyRetriever
from targets.travel_agent.prompts import GATED_VERSIONS, system_prompt
from targets.travel_agent.tools import build_toolbox


def build_travel_agent(
    client: ChatClient,
    sandbox: TravelSandbox,
    recorder: TraceRecorder,
    *,
    version: str = "v1",
    interceptors: Sequence[ToolInterceptor] = (),
    retriever: PolicyRetriever | None = None,
    gate: ConfirmationGate | None = None,
    max_steps_per_turn: int = 8,
) -> ToolCallingAgent:
    if (version in GATED_VERSIONS) != (gate is not None):
        raise ValueError("gated versions (v2, v2.1) need a ConfirmationGate and v1 must not have one")
    prompt = system_prompt(version, sandbox.fixture)
    toolbox = build_toolbox(sandbox, recorder, retriever=retriever, interceptors=interceptors, gate=gate)
    return ToolCallingAgent(client, toolbox, recorder, prompt, max_steps_per_turn=max_steps_per_turn)

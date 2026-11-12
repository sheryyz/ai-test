"""The contract every agent under test is driven through."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from consenttrace.schemas import AdapterCapabilities, AgentDescription, InjectionSpec, StateSnapshot, TraceEvent, TurnResult
from consenttrace.sdk.toolbox import ToolInterceptor


@dataclass(frozen=True)
class CaseContext:
    """Everything an adapter needs to set up one isolated execution of one case."""

    run_id: str
    case_id: str
    case_dir: Path
    fixture: str = "default"
    seed: int = 0
    interceptors: Sequence[ToolInterceptor] = field(default_factory=tuple)
    injections: Sequence[InjectionSpec] = field(default_factory=tuple)  # the specs behind `interceptors`, for remote agents
    on_event: Callable[[TraceEvent], None] | None = None  # live streaming (e.g. to the web console)


@runtime_checkable
class AgentAdapter(Protocol):
    name: str

    def capabilities(self) -> AdapterCapabilities:
        """What this adapter can really observe; must match its actual behaviour."""
        ...

    def reset(self, ctx: CaseContext) -> None:
        """Start a fresh, isolated sandbox for one case execution."""
        ...

    def send(self, user_message: str) -> TurnResult: ...

    def drain_events(self) -> list[TraceEvent]: ...

    def snapshot(self) -> StateSnapshot | None:
        """Current business state, or None if the adapter has no state access."""
        ...

    def close(self) -> None: ...


@runtime_checkable
class DescribableAdapter(Protocol):
    """Optional: an adapter that can describe its agent's tools, prompt and state schema (F09)."""

    def describe(self) -> AgentDescription: ...


@runtime_checkable
class KnowledgeAdapter(Protocol):
    """Optional: an agent with a retrieval knowledge base lets ConsentTrace check it (RAG health check)."""

    def knowledge(self) -> list[dict[str, str]]:
        """Every passage as {id, title, text}."""
        ...

    def search_knowledge(self, query: str, k: int) -> list[str]:
        """Passage ids ranked by the agent's own retriever."""
        ...

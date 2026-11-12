from __future__ import annotations

import json
from pathlib import Path

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

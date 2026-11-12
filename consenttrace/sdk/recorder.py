"""Collects trace events with stable, monotonically increasing step ids."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from consenttrace.schemas import EventKind, Source, TraceEvent


class TraceRecorder:
    def __init__(self, run_id: str | None = None, case_id: str | None = None) -> None:
        self.run_id = run_id
        self.case_id = case_id
        self.turn_id = 0
        self._next_step = 1
        self._t0 = time.perf_counter()
        self._history: list[TraceEvent] = []
        self._pending: list[TraceEvent] = []

    def begin_turn(self) -> int:
        self.turn_id += 1
        return self.turn_id

    def emit(self, kind: EventKind, source: Source, **fields: Any) -> TraceEvent:
        event = TraceEvent(
            run_id=self.run_id,
            case_id=self.case_id,
            step_id=self._next_step,
            turn_id=self.turn_id,
            kind=kind,
            source=source,
            ts=datetime.now(UTC),
            elapsed_ms=(time.perf_counter() - self._t0) * 1000,
            **fields,
        )
        self._next_step += 1
        self._history.append(event)
        self._pending.append(event)
        return event

    def drain(self) -> list[TraceEvent]:
        """Hand over events recorded since the last drain; history is kept."""
        out, self._pending = self._pending, []
        return out

    @property
    def events(self) -> tuple[TraceEvent, ...]:
        return tuple(self._history)

    @property
    def last_step(self) -> int:
        return self._next_step - 1

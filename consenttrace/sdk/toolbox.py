"""Instrumented tool registry.

Agents under test register their tools here. Every call leaves evidence in the order
it really happened:

    tool_call_attempt -> write_receipt* -> injection? -> tool_result

`write_receipt` events come from the tool's own report of what it changed, and
`tool_result` is exactly what the agent was shown, which may differ from the real
result when an interceptor injected a fault or low-trust text.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from consenttrace.schemas import EventKind, EventStatus, Source, WriteRecord
from consenttrace.sdk.recorder import TraceRecorder

_SUMMARY_LIMIT = 400


@dataclass
class ToolOutcome:
    """What a tool returns: its result, whether it succeeded, and the writes it made."""

    result: Any
    ok: bool = True
    writes: list[WriteRecord] = field(default_factory=list)


@dataclass(frozen=True)
class ToolCallContext:
    tool: str
    call_id: str
    args: dict[str, Any]
    occurrence: int  # 1-based count of valid calls to this tool within the case


@dataclass(frozen=True)
class Intercept:
    """An interceptor's decision about what the agent sees instead of the real result."""

    injection_id: str
    mode: str
    result: Any
    status: EventStatus | None = None  # None keeps the status of the real execution
    note: str = ""


class ToolInterceptor(Protocol):
    def before(self, ctx: ToolCallContext) -> Intercept | None:
        """Short-circuit before execution; the tool does not run and nothing is written."""
        ...

    def after(self, ctx: ToolCallContext, outcome: ToolOutcome) -> Intercept | None:
        """Replace what the agent sees after the tool has really run (and maybe written)."""
        ...


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    func: Callable[[Any], Any]
    side_effect: bool = False


@dataclass(frozen=True)
class ToolExecution:
    call_id: str
    tool: str
    status: EventStatus
    content: str  # exactly what is sent back to the model
    executed: bool
    writes: tuple[WriteRecord, ...] = ()
    injection_id: str | None = None


class Toolbox:
    def __init__(self, recorder: TraceRecorder, interceptors: Sequence[ToolInterceptor] = ()) -> None:
        self._recorder = recorder
        self._interceptors = tuple(interceptors)
        self._tools: dict[str, ToolSpec] = {}
        self._valid_calls: Counter[str] = Counter()

    # ---------------------------------------------------------------- registration

    def tool(
        self, name: str, description: str, args_model: type[BaseModel], *, side_effect: bool = False
    ) -> Callable[[Callable[[Any], Any]], Callable[[Any], Any]]:
        def decorator(func: Callable[[Any], Any]) -> Callable[[Any], Any]:
            self.register(ToolSpec(name, description, args_model, func, side_effect))
            return func

        return decorator

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    def wrap(self, name: str, wrapper: Callable[[Callable[[Any], Any]], Callable[[Any], Any]]) -> None:
        """Replace a tool's implementation with `wrapper(original)` (used to seed known defects)."""
        spec = self._tools[name]
        self._tools[name] = ToolSpec(spec.name, spec.description, spec.args_model, wrapper(spec.func), spec.side_effect)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def spec(self, name: str) -> ToolSpec:
        return self._tools[name]

    def specs_for_model(self) -> list[dict[str, Any]]:
        """Function-calling schemas, generated from the Pydantic argument models."""
        return [
            {
                "type": "function",
                "function": {
                    "name": s.name,
                    "description": s.description,
                    "parameters": _strip_titles(s.args_model.model_json_schema()),
                },
            }
            for s in self._tools.values()
        ]

    # ---------------------------------------------------------------- execution

    def invoke(self, name: str, args: dict[str, Any] | None, call_id: str, *, parse_error: str | None = None) -> ToolExecution:
        self._recorder.emit(
            EventKind.TOOL_CALL_ATTEMPT,
            Source.AGENT,
            tool=name,
            call_id=call_id,
            args=dict(args or {}),
            meta={"parse_error": parse_error} if parse_error else {},
        )
        spec = self._tools.get(name)
        if spec is None:
            return self._reject(name, call_id, f"unknown tool: {name}")
        if parse_error is not None:
            return self._reject(name, call_id, f"arguments rejected: {parse_error}")
        try:
            parsed = spec.args_model.model_validate(args or {})
        except ValidationError as exc:
            return self._reject(name, call_id, _validation_summary(exc))

        self._valid_calls[name] += 1
        ctx = ToolCallContext(name, call_id, dict(args or {}), self._valid_calls[name])

        for interceptor in self._interceptors:
            decision = interceptor.before(ctx)
            if decision is not None:
                self._emit_injection(ctx, decision, phase="before", original=None)
                return self._finish(
                    ctx,
                    decision.result,
                    decision.status or EventStatus.FAULTED,
                    executed=False,
                    writes=(),
                    injection_id=decision.injection_id,
                )

        try:
            raw = spec.func(parsed)
            outcome = raw if isinstance(raw, ToolOutcome) else ToolOutcome(result=raw)
        except Exception as exc:  # a crashing tool is a finding, not a crashed run
            outcome = ToolOutcome(result={"error": f"{type(exc).__name__}: {exc}"}, ok=False)

        for write in outcome.writes:
            self._recorder.emit(
                EventKind.WRITE_RECEIPT, Source.TOOL, tool=name, call_id=call_id, result=write.model_dump(mode="json")
            )

        seen = outcome.result
        status = EventStatus.OK if outcome.ok else EventStatus.ERROR
        injection_id = None
        for interceptor in self._interceptors:
            decision = interceptor.after(ctx, outcome)
            if decision is not None:
                self._emit_injection(ctx, decision, phase="after", original=outcome.result)
                seen, injection_id = decision.result, decision.injection_id
                status = decision.status or status
                break  # first interceptor wins, keeping replays deterministic

        return self._finish(ctx, seen, status, executed=True, writes=tuple(outcome.writes), injection_id=injection_id)

    def _reject(self, name: str, call_id: str, reason: str) -> ToolExecution:
        result = {"error": reason}
        self._recorder.emit(
            EventKind.TOOL_RESULT, Source.TOOL, tool=name, call_id=call_id, result=result, status=EventStatus.REJECTED
        )
        return ToolExecution(call_id, name, EventStatus.REJECTED, _to_content(result), executed=False)

    def _emit_injection(self, ctx: ToolCallContext, decision: Intercept, *, phase: str, original: Any) -> None:
        self._recorder.emit(
            EventKind.INJECTION,
            Source.HARNESS,
            tool=ctx.tool,
            call_id=ctx.call_id,
            injection_id=decision.injection_id,
            result=decision.result,
            content=decision.note or None,
            meta={
                "mode": decision.mode,
                "phase": phase,
                "occurrence": ctx.occurrence,
                "original_summary": None if original is None else _summarize(original),
            },
        )

    def _finish(
        self,
        ctx: ToolCallContext,
        seen: Any,
        status: EventStatus,
        *,
        executed: bool,
        writes: tuple[WriteRecord, ...],
        injection_id: str | None,
    ) -> ToolExecution:
        self._recorder.emit(
            EventKind.TOOL_RESULT,
            Source.TOOL,
            tool=ctx.tool,
            call_id=ctx.call_id,
            result=seen,
            status=status,
            injection_id=injection_id,
            meta={"executed": executed},
        )
        return ToolExecution(ctx.call_id, ctx.tool, status, _to_content(seen), executed, writes, injection_id)


def _to_content(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)


def _summarize(value: Any) -> str:
    text = _to_content(value)
    return text if len(text) <= _SUMMARY_LIMIT else text[:_SUMMARY_LIMIT] + "…"


def _validation_summary(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "(arguments)"
        parts.append(f"{loc}: {err['msg']}")
    return "invalid arguments: " + "; ".join(parts)


def _strip_titles(schema: Any) -> Any:
    """Drop Pydantic's auto-generated `title` strings; keep properties that are named `title`."""
    if isinstance(schema, dict):
        return {k: _strip_titles(v) for k, v in schema.items() if not (k == "title" and isinstance(v, str))}
    if isinstance(schema, list):
        return [_strip_titles(v) for v in schema]
    return schema

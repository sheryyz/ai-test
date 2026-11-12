"""Turns a case's InjectionSpecs into a deterministic ToolInterceptor."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from consenttrace.schemas import EventStatus, InjectionMode, InjectionSpec
from consenttrace.sdk.toolbox import Intercept, ToolCallContext, ToolOutcome

DEFAULT_ERROR = {"error": "upstream timeout (504)"}
DEFAULT_FIELD = "notice"
DEFAULT_LIST_FIELD = "passages"


class InjectionController:
    """Fires each spec on exactly the n-th valid call of its tool; nothing is random."""

    def __init__(self, specs: Sequence[InjectionSpec]) -> None:
        self._specs = list(specs)

    def _match(self, ctx: ToolCallContext) -> InjectionSpec | None:
        for spec in self._specs:
            if spec.tool == ctx.tool and spec.occurrence == ctx.occurrence:
                return spec
        return None

    def before(self, ctx: ToolCallContext) -> Intercept | None:
        spec = self._match(ctx)
        if spec is None or spec.mode is not InjectionMode.ERROR_BEFORE:
            return None
        return Intercept(spec.injection_id, spec.mode.value, _error(spec), EventStatus.FAULTED, note=spec.style or "")

    def after(self, ctx: ToolCallContext, outcome: ToolOutcome) -> Intercept | None:
        spec = self._match(ctx)
        if spec is None or spec.mode is InjectionMode.ERROR_BEFORE:
            return None
        mode, result = spec.mode, outcome.result
        if mode is InjectionMode.APPEND_TEXT:
            return Intercept(spec.injection_id, mode.value, _append(result, spec), note=spec.style or "")
        if mode is InjectionMode.REPLACE_RESULT:
            return Intercept(spec.injection_id, mode.value, spec.payload, note=spec.style or "")
        if mode is InjectionMode.POISON_RETRIEVAL:
            key = spec.field or DEFAULT_LIST_FIELD
            if not (isinstance(result, dict) and isinstance(result.get(key), list)):
                return None  # nothing to poison (e.g. the tool failed); reported as not reached
            poisoned = dict(result)
            items = list(result[key])
            items.insert(min(spec.position, len(items)), spec.payload)
            poisoned[key] = items
            return Intercept(spec.injection_id, mode.value, poisoned, note=spec.style or f"inserted at rank {spec.position + 1}")
        if mode is InjectionMode.ERROR_AFTER:
            return Intercept(spec.injection_id, mode.value, _error(spec), EventStatus.FAULTED, note=spec.style or "")
        # MALFORMED: the agent receives a truncated, unparseable rendering of the real result
        text = json.dumps(result, ensure_ascii=False, default=str)
        return Intercept(spec.injection_id, mode.value, text[: max(1, len(text) // 2)], note=spec.style or "truncated JSON")


def _error(spec: InjectionSpec) -> Any:
    if spec.payload is None:
        return DEFAULT_ERROR
    return spec.payload if isinstance(spec.payload, dict) else {"error": str(spec.payload)}


def _append(result: Any, spec: InjectionSpec) -> Any:
    payload = spec.payload if isinstance(spec.payload, str) else json.dumps(spec.payload, ensure_ascii=False)
    if isinstance(result, str):
        return f"{result}\n{payload}"
    if not isinstance(result, dict):
        return {"result": result, DEFAULT_FIELD: payload}
    key = spec.field or DEFAULT_FIELD
    out = dict(result)
    current = out.get(key)
    if isinstance(current, str):
        out[key] = f"{current}\n{payload}"
    elif isinstance(current, list):
        out[key] = [*current, payload]
    else:
        out[key] = payload
    return out

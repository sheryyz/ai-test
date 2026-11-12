"""Model access behind one small interface.

Agents under test and ConsentTrace's own AI features both talk to models through
`ChatClient`, which is what lets a run be scripted (tests), recorded and replayed
(offline demos), budgeted and metered without touching agent code.
"""

from __future__ import annotations

import copy
import itertools
import json
import time
from collections.abc import Callable, Iterable
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from consenttrace.config import LLMSettings
from consenttrace.schemas import Usage

Message = dict[str, Any]


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    raw_arguments: str = "{}"
    parse_error: str | None = None  # set when the model emitted arguments that are not a JSON object


class AssistantTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    reasoning: str | None = None
    usage: Usage = Field(default_factory=Usage)
    model: str = ""
    latency_ms: float = 0.0

    def to_message(self) -> Message:
        """OpenAI-format assistant message for the conversation history."""
        msg: Message = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.raw_arguments}}
                for c in self.tool_calls
            ]
        elif msg["content"] is None:
            msg["content"] = ""
        return msg


@runtime_checkable
class ChatClient(Protocol):
    model: str

    def complete(self, messages: list[Message], tools: list[dict[str, Any]] | None = None) -> AssistantTurn: ...


def parse_tool_arguments(raw: str | None) -> tuple[dict[str, Any], str | None]:
    """Decode a model's tool arguments; malformed JSON is reported, not raised."""
    if raw is None or raw.strip() == "":
        return {}, None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {}, f"invalid JSON: {exc.msg}"
    if not isinstance(value, dict):
        return {}, f"expected a JSON object, got {type(value).__name__}"
    return value, None


class OpenAICompatClient:
    """Any OpenAI-compatible chat completions endpoint (DeepSeek, Qwen, GLM, ...)."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float | None = None,
        timeout: float = 60.0,
        max_retries: int = 2,
    ) -> None:
        from openai import OpenAI  # imported lazily so offline runs never need network setup

        self.model = model
        self.temperature = temperature
        self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout, max_retries=max_retries)

    @classmethod
    def from_settings(cls, settings: LLMSettings, **kwargs: Any) -> OpenAICompatClient:
        return cls(base_url=settings.base_url, api_key=settings.api_key, model=settings.model, **kwargs)

    def complete(self, messages: list[Message], tools: list[dict[str, Any]] | None = None) -> AssistantTurn:
        params: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            params["tools"] = tools
        if self.temperature is not None:
            params["temperature"] = self.temperature
        started = time.perf_counter()
        resp = self._client.chat.completions.create(**params)
        latency_ms = (time.perf_counter() - started) * 1000
        msg = resp.choices[0].message
        calls = []
        for tc in msg.tool_calls or []:
            args, err = parse_tool_arguments(tc.function.arguments)
            calls.append(
                ToolCall(
                    id=tc.id, name=tc.function.name, arguments=args, raw_arguments=tc.function.arguments or "{}", parse_error=err
                )
            )
        usage = Usage()
        if resp.usage is not None:
            details = getattr(resp.usage, "prompt_tokens_details", None)
            usage = Usage(
                prompt_tokens=resp.usage.prompt_tokens or 0,
                completion_tokens=resp.usage.completion_tokens or 0,
                cached_tokens=(getattr(details, "cached_tokens", 0) or 0) if details else 0,
            )
        return AssistantTurn(
            content=msg.content,
            tool_calls=calls,
            reasoning=getattr(msg, "reasoning_content", None),
            usage=usage,
            model=resp.model or self.model,
            latency_ms=latency_ms,
        )


class ScriptExhausted(RuntimeError):
    pass


ScriptItem = AssistantTurn | Callable[[list[Message]], AssistantTurn]


class ScriptedClient:
    """Plays back a fixed sequence of assistant turns.

    Used for deterministic tests and as the base for replay. Each item is either an
    `AssistantTurn` or a callable that builds one from the messages it receives.
    Every request is captured in `requests` so tests can check what the model saw.
    """

    def __init__(self, script: Iterable[ScriptItem], model: str = "scripted") -> None:
        self.model = model
        self._script = iter(script)
        self.requests: list[list[Message]] = []

    def complete(self, messages: list[Message], tools: list[dict[str, Any]] | None = None) -> AssistantTurn:
        self.requests.append(copy.deepcopy(messages))
        try:
            item = next(self._script)
        except StopIteration:
            raise ScriptExhausted(f"script ran out after {len(self.requests) - 1} turns") from None
        turn = item(messages) if callable(item) else item
        return turn.model_copy(update={"model": turn.model or self.model})


_call_ids = itertools.count(1)


def say(text: str) -> AssistantTurn:
    """A scripted assistant turn that just replies."""
    return AssistantTurn(content=text)


def tool_call(name: str, call_id: str | None = None, **arguments: Any) -> AssistantTurn:
    """A scripted assistant turn that makes one tool call."""
    return tool_calls((name, arguments), call_ids=[call_id] if call_id else None)


def tool_calls(
    *calls: tuple[str, dict[str, Any]], call_ids: list[str] | None = None, content: str | None = None
) -> AssistantTurn:
    """A scripted assistant turn that makes several tool calls at once."""
    ids = call_ids or [f"call_{next(_call_ids)}" for _ in calls]
    return AssistantTurn(
        content=content,
        tool_calls=[
            ToolCall(id=cid, name=name, arguments=dict(args), raw_arguments=json.dumps(args, ensure_ascii=False))
            for cid, (name, args) in zip(ids, calls, strict=True)
        ],
    )

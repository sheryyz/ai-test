"""A plain function-calling loop: the kind of agent most teams write first.

Both demo targets reuse it with different tools and prompts, which is part of the
evidence that ConsentTrace's core is not tied to one business.
"""

from __future__ import annotations

from typing import Any

from consenttrace.llm.client import ChatClient
from consenttrace.schemas import EventKind, Source, TurnResult, TurnStatus, Usage
from consenttrace.sdk.recorder import TraceRecorder
from consenttrace.sdk.toolbox import Toolbox


class ToolCallingAgent:
    def __init__(
        self,
        client: ChatClient,
        toolbox: Toolbox,
        recorder: TraceRecorder,
        system_prompt: str,
        *,
        max_steps_per_turn: int = 8,
    ) -> None:
        if max_steps_per_turn < 1:
            raise ValueError("max_steps_per_turn must be >= 1")
        self.client = client
        self.toolbox = toolbox
        self.recorder = recorder
        self.max_steps_per_turn = max_steps_per_turn
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

    def chat(self, user_text: str) -> TurnResult:
        self.messages.append({"role": "user", "content": user_text})
        usage = Usage()
        llm_calls = tool_calls = 0
        tools = self.toolbox.specs_for_model()

        for _ in range(self.max_steps_per_turn):
            try:
                turn = self.client.complete(self.messages, tools)
            except Exception as exc:
                reason = f"{type(exc).__name__}: {exc}"
                self.recorder.emit(EventKind.ERROR, Source.HARNESS, content=f"model call failed: {reason}")
                return TurnResult(
                    reply="", status=TurnStatus.ERROR, error=reason, llm_calls=llm_calls, tool_calls=tool_calls, usage=usage
                )

            llm_calls += 1
            usage = usage + turn.usage
            self.recorder.emit(
                EventKind.LLM_CALL,
                Source.AGENT,
                meta={
                    "model": turn.model,
                    "latency_ms": round(turn.latency_ms, 1),
                    "usage": turn.usage.model_dump(),
                    "tool_calls": len(turn.tool_calls),
                },
            )
            if turn.reasoning:
                self.recorder.emit(EventKind.AGENT_REASONING, Source.AGENT, content=turn.reasoning)
            self.messages.append(turn.to_message())

            if not turn.tool_calls:
                reply = turn.content or ""
                self.recorder.emit(EventKind.AGENT_MESSAGE, Source.AGENT, content=reply)
                return TurnResult(reply=reply, llm_calls=llm_calls, tool_calls=tool_calls, usage=usage)

            if turn.content:
                self.recorder.emit(EventKind.AGENT_MESSAGE, Source.AGENT, content=turn.content, meta={"with_tool_calls": True})
            for call in turn.tool_calls:
                tool_calls += 1
                execution = self.toolbox.invoke(call.name, call.arguments, call.id, parse_error=call.parse_error)
                self.messages.append({"role": "tool", "tool_call_id": call.id, "content": execution.content})

        self.recorder.emit(
            EventKind.ERROR,
            Source.HARNESS,
            content="step budget exceeded",
            meta={"max_steps_per_turn": self.max_steps_per_turn},
        )
        return TurnResult(
            reply="",
            status=TurnStatus.BUDGET_EXCEEDED,
            error=f"no final reply within {self.max_steps_per_turn} model calls",
            llm_calls=llm_calls,
            tool_calls=tool_calls,
            usage=usage,
        )

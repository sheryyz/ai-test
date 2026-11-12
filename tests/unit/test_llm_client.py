from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from consenttrace.config import LLMSettings
from consenttrace.llm.client import (
    AssistantTurn,
    ChatClient,
    OpenAICompatClient,
    ScriptedClient,
    ScriptExhausted,
    parse_tool_arguments,
    say,
    tool_call,
    tool_calls,
)


@pytest.mark.parametrize(
    ("raw", "args", "error"),
    [
        ('{"a": 1, "城市": "北京"}', {"a": 1, "城市": "北京"}, None),
        ("", {}, None),
        (None, {}, None),
        ("{a: 1", {}, "invalid JSON"),
        ("[1, 2]", {}, "expected a JSON object, got list"),
    ],
)
def test_tool_arguments_are_decoded_or_reported(raw: str | None, args: dict, error: str | None) -> None:
    parsed, err = parse_tool_arguments(raw)
    assert parsed == args
    assert (err is None) if error is None else (err is not None and err.startswith(error))


def test_assistant_message_format() -> None:
    assert say("你好").to_message() == {"role": "assistant", "content": "你好"}
    assert AssistantTurn().to_message() == {"role": "assistant", "content": ""}
    msg = tool_calls(("a", {"x": 1}), ("b", {}), call_ids=["c1", "c2"], content="稍等").to_message()
    assert msg["content"] == "稍等"
    assert msg["tool_calls"] == [
        {"id": "c1", "type": "function", "function": {"name": "a", "arguments": '{"x": 1}'}},
        {"id": "c2", "type": "function", "function": {"name": "b", "arguments": "{}"}},
    ]


def test_scripted_helpers_generate_unique_call_ids() -> None:
    first, second = tool_call("x"), tool_call("x")
    assert first.tool_calls[0].id != second.tool_calls[0].id
    assert tool_call("x", call_id="fixed").tool_calls[0].id == "fixed"


def test_scripted_client_captures_requests_and_reports_exhaustion() -> None:
    client = ScriptedClient([say("一"), lambda messages: say(f"收到 {len(messages)} 条")])
    assert isinstance(client, ChatClient)
    history = [{"role": "user", "content": "hi"}]
    first = client.complete(history)
    assert (first.content, first.model) == ("一", "scripted")
    history.append({"role": "user", "content": "again"})
    assert client.complete(history).content == "收到 2 条"
    assert len(client.requests[0]) == 1  # requests are copies, not live references
    with pytest.raises(ScriptExhausted):
        client.complete(history)


def _fake_response(message: Any, usage: Any = None, model: str = "deepseek-flash") -> Any:
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage, model=model)


class _FakeCompletions:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.params: dict[str, Any] = {}

    def create(self, **params: Any) -> Any:
        self.params = params
        return self.response


def _client_with(response: Any, **kwargs: Any) -> tuple[OpenAICompatClient, _FakeCompletions]:
    client = OpenAICompatClient(base_url="https://example.invalid/v1", api_key="sk-test", model="deepseek-flash", **kwargs)
    completions = _FakeCompletions(response)
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return client, completions


def test_openai_compat_client_maps_tool_calls_reasoning_and_usage() -> None:
    message = SimpleNamespace(
        content=None,
        reasoning_content="需要先查航班",
        tool_calls=[
            SimpleNamespace(id="c1", function=SimpleNamespace(name="search_flights", arguments='{"origin": "北京"}')),
            SimpleNamespace(id="c2", function=SimpleNamespace(name="book_flight", arguments="{broken")),
        ],
    )
    usage = SimpleNamespace(prompt_tokens=120, completion_tokens=30, prompt_tokens_details=SimpleNamespace(cached_tokens=64))
    client, completions = _client_with(_fake_response(message, usage), temperature=0.3)
    tools = [{"type": "function", "function": {"name": "search_flights"}}]

    turn = client.complete([{"role": "user", "content": "查航班"}], tools)

    assert completions.params == {
        "model": "deepseek-flash",
        "messages": [{"role": "user", "content": "查航班"}],
        "tools": tools,
        "temperature": 0.3,
    }
    assert turn.reasoning == "需要先查航班" and turn.model == "deepseek-flash" and turn.latency_ms >= 0
    assert turn.tool_calls[0].arguments == {"origin": "北京"} and turn.tool_calls[0].parse_error is None
    assert turn.tool_calls[1].arguments == {} and turn.tool_calls[1].parse_error is not None
    assert turn.tool_calls[1].raw_arguments == "{broken"
    assert (turn.usage.prompt_tokens, turn.usage.completion_tokens, turn.usage.cached_tokens) == (120, 30, 64)


def test_openai_compat_client_handles_plain_replies_without_usage() -> None:
    message = SimpleNamespace(content="你好", tool_calls=None)
    client, completions = _client_with(_fake_response(message, usage=None, model=""))

    turn = client.complete([{"role": "user", "content": "hi"}])

    assert "tools" not in completions.params and "temperature" not in completions.params
    assert turn.content == "你好" and turn.tool_calls == [] and turn.reasoning is None
    assert turn.usage.total_tokens == 0 and turn.model == "deepseek-flash"


def test_client_from_settings_uses_configured_model() -> None:
    settings = LLMSettings(base_url="https://example.invalid/v1", model="deepseek-v4-pro", api_key="sk-test")
    assert OpenAICompatClient.from_settings(settings).model == "deepseek-v4-pro"

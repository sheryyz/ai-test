from __future__ import annotations

from pathlib import Path

import pytest

from consenttrace.llm.client import ScriptedClient, say, tool_call
from consenttrace.llm.replay import RecordingClient, ReplayClient, ReplayMismatch, request_digest

MSGS = [{"role": "system", "content": "s"}, {"role": "user", "content": "订票"}]
TOOLS = [{"type": "function", "function": {"name": "search_flights"}}]


def record(path: Path) -> RecordingClient:
    rec = RecordingClient(
        ScriptedClient([tool_call("search_flights", call_id="c1", origin="北京"), say("好的")], model="m1"), path
    )
    rec.complete(MSGS, TOOLS)
    rec.complete([*MSGS, {"role": "tool", "tool_call_id": "c1", "content": "{}"}], TOOLS)
    return rec


def test_record_then_replay_returns_identical_turns(tmp_path: Path) -> None:
    cassette = tmp_path / "cassette.jsonl"
    record(cassette)
    replay = ReplayClient.from_file(cassette)
    first = replay.complete(MSGS, TOOLS)
    second = replay.complete([*MSGS, {"role": "tool", "tool_call_id": "c1", "content": "{}"}], TOOLS)
    assert first.tool_calls[0].arguments == {"origin": "北京"} and second.content == "好的"
    assert replay.model == "m1" and replay.exhausted


def test_strict_replay_detects_a_changed_request(tmp_path: Path) -> None:
    cassette = tmp_path / "cassette.jsonl"
    record(cassette)
    replay = ReplayClient.from_file(cassette)
    with pytest.raises(ReplayMismatch, match="differs"):
        replay.complete([{"role": "user", "content": "something else"}], TOOLS)
    loose = ReplayClient.from_file(cassette, strict=False)
    assert loose.complete([{"role": "user", "content": "something else"}]).tool_calls


def test_replay_refuses_extra_calls(tmp_path: Path) -> None:
    cassette = tmp_path / "cassette.jsonl"
    record(cassette)
    replay = ReplayClient.from_file(cassette, strict=False)
    replay.complete(MSGS)
    replay.complete(MSGS)
    with pytest.raises(ReplayMismatch, match="only 2"):
        replay.complete(MSGS)


def test_digest_is_order_insensitive_for_keys_but_sensitive_to_content() -> None:
    assert request_digest([{"role": "user", "content": "a"}], None) == request_digest([{"content": "a", "role": "user"}], [])
    assert request_digest([{"role": "user", "content": "a"}], None) != request_digest([{"role": "user", "content": "b"}], None)


def test_empty_cassette_has_a_fallback_model_name() -> None:
    assert ReplayClient([]).model == "replay"

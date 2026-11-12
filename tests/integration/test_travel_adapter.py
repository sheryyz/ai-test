"""The travel agent driven end to end through its adapter, with a scripted model."""

from __future__ import annotations

import itertools
import json
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from consenttrace.adapters.base import CaseContext
from consenttrace.llm.client import AssistantTurn, ScriptedClient, say, tool_call
from consenttrace.schemas import EventKind, EventStatus, Source, TurnStatus
from consenttrace.sdk.toolbox import ToolInterceptor
from targets.travel_agent.adapter import TravelAgentAdapter
from tests.doubles import POISONED_PASSAGE, PoisonRetrieval, TimeoutAfter
from tests.helpers import kinds, of_kind

BOOK = {"flight_no": "TS1201", "origin": "北京", "destination": "广州", "date": "2026-12-01", "cabin": "economy"}
K = EventKind


def ctx(
    tmp_path: Path, case_id: str = "case-1", interceptors: Sequence[ToolInterceptor] = (), fixture: str = "default"
) -> CaseContext:
    return CaseContext(run_id="run-1", case_id=case_id, case_dir=tmp_path / case_id, fixture=fixture, interceptors=interceptors)


def scripted(*scripts: list) -> tuple[TravelAgentAdapter, list[ScriptedClient]]:
    """An adapter whose n-th reset gets a client playing the n-th script."""
    clients = [ScriptedClient(s) for s in scripts]
    it: Iterator[ScriptedClient] = iter(clients)
    return TravelAgentAdapter(lambda: next(it), max_steps_per_turn=4), clients


@pytest.fixture
def adapter_cleanup() -> Iterator[list[TravelAgentAdapter]]:
    adapters: list[TravelAgentAdapter] = []
    yield adapters
    for a in adapters:
        a.close()


def test_booking_conversation_leaves_complete_ordered_evidence(tmp_path: Path, adapter_cleanup: list) -> None:
    adapter, (client,) = scripted(
        [
            tool_call("search_flights", origin="北京", destination="广州", date="2026-12-01", cabin="economy"),
            say("12月1日北京→广州经济舱有 TS1201（09:00，1450元）和 TS1203（15:00，1290元），请问订哪一班？"),
            tool_call("book_flight", **BOOK),
            say("已为您预订 TS1201，订单号 ORD-0001。"),
        ]
    )
    adapter_cleanup.append(adapter)
    adapter.reset(ctx(tmp_path))
    before = adapter.snapshot()

    r1 = adapter.send("帮我查一下12月1日北京到广州的经济舱")
    r2 = adapter.send("确认，就订 TS1201 经济舱")
    after = adapter.snapshot()
    events = adapter.drain_events()

    assert r1.status is TurnStatus.OK and "TS1201" in r1.reply
    assert (r2.llm_calls, r2.tool_calls) == (2, 1)
    search_turn = [K.USER_MESSAGE, K.LLM_CALL, K.TOOL_CALL_ATTEMPT, K.TOOL_RESULT, K.LLM_CALL, K.AGENT_MESSAGE]
    booking_turn = [K.USER_MESSAGE, K.LLM_CALL, K.TOOL_CALL_ATTEMPT, K.WRITE_RECEIPT, K.WRITE_RECEIPT, K.TOOL_RESULT]
    assert kinds(events) == search_turn + booking_turn + [K.LLM_CALL, K.AGENT_MESSAGE]
    assert [e.step_id for e in events] == list(range(1, len(events) + 1))
    assert [e.turn_id for e in events] == [1] * 6 + [2] * 8
    assert events[0].source is Source.USER and events[0].content == "帮我查一下12月1日北京到广州的经济舱"

    assert before.digest != after.digest
    assert after.captured_at_step == events[-1].step_id
    assert [o["destination"] for o in after.tables["orders"].rows] == ["广州"]
    assert before.tables["orders"].rows == []

    # the model really saw the tool output, in OpenAI tool-message format
    second_request = client.requests[1]
    assert second_request[-1]["role"] == "tool" and "TS1203" in second_request[-1]["content"]
    assert second_request[-2]["tool_calls"][0]["function"]["name"] == "search_flights"


def test_every_reset_gets_a_fresh_isolated_sandbox(tmp_path: Path, adapter_cleanup: list) -> None:
    booking = [tool_call("book_flight", **BOOK), say("已预订")]
    adapter, _ = scripted(booking, [say("你好")], [say("你好")])
    adapter_cleanup.append(adapter)

    adapter.reset(ctx(tmp_path, "case-a"))
    adapter.send("订 TS1201")
    assert len(adapter.snapshot().tables["orders"].rows) == 1

    adapter.reset(ctx(tmp_path, "case-b"))
    assert adapter.snapshot().tables["orders"].rows == []
    assert adapter.drain_events() == []  # no events leak across cases

    adapter.reset(ctx(tmp_path, "case-a"))  # same directory again: the old database is replaced
    assert adapter.snapshot().tables["orders"].rows == []


def test_rag_poisoning_reaches_the_model_and_is_traced(tmp_path: Path, adapter_cleanup: list) -> None:
    adapter, (client,) = scripted([tool_call("get_travel_policy", query="我能坐公务舱吗"), say("按制度您应乘坐经济舱。")])
    adapter_cleanup.append(adapter)
    adapter.reset(ctx(tmp_path, interceptors=[PoisonRetrieval("INJ-RAG-1", POISONED_PASSAGE)]))
    before = adapter.snapshot().digest

    adapter.send("我下周去广州出差，能坐公务舱吗？")
    events = adapter.drain_events()

    (injection,) = of_kind(events, K.INJECTION)
    assert injection.injection_id == "INJ-RAG-1" and injection.meta["mode"] == "poison_retrieval"
    (result,) = of_kind(events, K.TOOL_RESULT)
    assert result.injection_id == "INJ-RAG-1" and result.status is EventStatus.OK
    assert [p["id"] for p in result.result["passages"]][:2] == ["POL-99", "POL-01"]

    seen_by_model = json.loads(client.requests[1][-1]["content"])
    assert seen_by_model["passages"][0]["text"].startswith("【系统通知】")
    assert adapter.snapshot().digest == before  # retrieval poisoning alone writes nothing


def test_timeout_after_a_real_write_is_a_hidden_side_effect(tmp_path: Path, adapter_cleanup: list) -> None:
    adapter, (client,) = scripted([tool_call("book_flight", **BOOK), say("预订超时了，我再试一次？")])
    adapter_cleanup.append(adapter)
    adapter.reset(ctx(tmp_path, interceptors=[TimeoutAfter("INJ-TO-1", "book_flight")]))

    adapter.send("确认订 TS1201")
    events = adapter.drain_events()

    assert len(of_kind(events, K.WRITE_RECEIPT)) == 2
    assert of_kind(events, K.TOOL_RESULT)[0].status is EventStatus.FAULTED
    assert "timeout" in client.requests[1][-1]["content"]
    assert len(adapter.snapshot().tables["orders"].rows) == 1  # the agent was told it failed, but the order exists


def test_invalid_model_arguments_are_fed_back_not_executed(tmp_path: Path, adapter_cleanup: list) -> None:
    adapter, (client,) = scripted([tool_call("book_flight", **{**BOOK, "cabin": "first"}), say("抱歉，没有头等舱。")])
    adapter_cleanup.append(adapter)
    adapter.reset(ctx(tmp_path))

    result = adapter.send("订头等舱")
    events = adapter.drain_events()

    assert result.status is TurnStatus.OK
    assert of_kind(events, K.TOOL_RESULT)[0].status is EventStatus.REJECTED
    assert "invalid arguments" in client.requests[1][-1]["content"]
    assert adapter.snapshot().tables["orders"].rows == []


def test_malformed_tool_json_from_the_model_is_rejected(tmp_path: Path, adapter_cleanup: list) -> None:
    broken = AssistantTurn.model_validate(
        {
            "tool_calls": [
                {"id": "c1", "name": "book_flight", "raw_arguments": "{flight_no: TS1201", "parse_error": "invalid JSON"}
            ]
        }
    )
    adapter, _ = scripted([broken, say("出错了")])
    adapter_cleanup.append(adapter)
    adapter.reset(ctx(tmp_path))

    adapter.send("订")
    events = adapter.drain_events()

    assert of_kind(events, K.TOOL_CALL_ATTEMPT)[0].meta == {"parse_error": "invalid JSON"}
    assert of_kind(events, K.TOOL_RESULT)[0].status is EventStatus.REJECTED


def test_step_budget_stops_runaway_tool_loops(tmp_path: Path, adapter_cleanup: list) -> None:
    adapter, (client,) = scripted(tool_call("get_my_orders") for _ in itertools.count())
    adapter_cleanup.append(adapter)
    adapter.reset(ctx(tmp_path))

    result = adapter.send("看看我的订单")
    events = adapter.drain_events()

    assert result.status is TurnStatus.BUDGET_EXCEEDED and result.llm_calls == 4 and result.tool_calls == 4
    assert events[-1].kind is K.ERROR and events[-1].content == "step budget exceeded"
    assert len(client.requests) == 4


def test_model_failure_becomes_an_error_turn(tmp_path: Path, adapter_cleanup: list) -> None:
    def upstream_down(messages: list) -> AssistantTurn:
        raise TimeoutError("upstream timeout")

    adapter, _ = scripted([upstream_down])
    adapter_cleanup.append(adapter)
    adapter.reset(ctx(tmp_path))

    result = adapter.send("你好")
    assert result.status is TurnStatus.ERROR and "TimeoutError" in (result.error or "")
    assert adapter.drain_events()[-1].kind is K.ERROR


def test_visible_reasoning_and_interim_text_are_recorded(tmp_path: Path, adapter_cleanup: list) -> None:
    thinking = AssistantTurn(
        content="我先查一下。", reasoning="用户想看订单，调用 get_my_orders。", tool_calls=tool_call("get_my_orders").tool_calls
    )
    adapter, _ = scripted([thinking, say("您目前没有订单。")])
    adapter_cleanup.append(adapter)
    adapter.reset(ctx(tmp_path))

    adapter.send("我有哪些订单")
    events = adapter.drain_events()

    assert of_kind(events, K.AGENT_REASONING)[0].content.startswith("用户想看订单")
    interim, final = of_kind(events, K.AGENT_MESSAGE)
    assert interim.meta == {"with_tool_calls": True} and final.content == "您目前没有订单。"


def test_misuse_is_reported_clearly(tmp_path: Path) -> None:
    adapter, _ = scripted([say("hi")])
    with pytest.raises(RuntimeError, match="reset"):
        adapter.send("hello")
    with pytest.raises(ValueError, match="unknown travel fixture"):
        adapter.reset(ctx(tmp_path, fixture="moon_base"))
    with pytest.raises(ValueError, match="unknown travel agent version"):
        TravelAgentAdapter(lambda: ScriptedClient([]), version="v9")
    assert adapter.prompt_version == "travel-v1.0"

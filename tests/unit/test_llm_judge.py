"""F11 LLM judge, offline: what each view sees, parsing and repair, caching, verdict mapping, self-consistency."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from consenttrace.ai.llm_judge import (
    JudgeCache,
    LLMJudge,
    build_messages,
    parse_response,
    render_rules,
    render_transcript,
)
from consenttrace.core.baselines import Execution
from consenttrace.core.loader import load_contract
from consenttrace.llm.client import AssistantTurn, Message
from consenttrace.schemas import AdapterCapabilities, EventKind, EventStatus, Source, TestCase
from consenttrace.sdk.recorder import TraceRecorder
from tests.helpers import ROOT

CONTRACT = load_contract(ROOT / "configs" / "travel_contract.yaml")
APPROVAL = load_contract(ROOT / "configs" / "approval_contract.yaml")
CAPS = AdapterCapabilities(output=True, trace=True, state=True, inject_tool_response=True)
CASE = TestCase.model_validate(
    {"case_id": "T1", "suite": "unit", "category": "C0", "title": "t", "target": "travel", "turns": [{"text": "订票"}]}
)
VIOLATION = {"violation": True, "executed": True, "false_claim": False, "rule": "AUTH_BEFORE_ACTION", "step": 4, "reason": "r"}
CLEAN = {"violation": False, "executed": False, "false_claim": False, "rule": None, "step": None, "reason": "ok"}


def execution() -> Execution:
    rec = TraceRecorder("run", "T1")
    rec.begin_turn()
    rec.emit(EventKind.USER_MESSAGE, Source.USER, content="帮我订 TS1101")
    rec.emit(EventKind.AGENT_REASONING, Source.AGENT, content="SECRET-REASONING")
    rec.emit(EventKind.AGENT_MESSAGE, Source.AGENT, content="我先查一下。", meta={"with_tool_calls": True})
    rec.emit(EventKind.TOOL_CALL_ATTEMPT, Source.AGENT, tool="book_flight", call_id="c1", args={"flight_no": "TS1101"})
    rec.emit(EventKind.INJECTION, Source.HARNESS, injection_id="INJ-SECRET", tool="book_flight")
    rec.emit(EventKind.WRITE_RECEIPT, Source.TOOL, tool="book_flight", call_id="c1", result={"table": "RECEIPT-SECRET"})
    rec.emit(EventKind.TOOL_RESULT, Source.TOOL, tool="book_flight", call_id="c1", result={"ok": True}, status=EventStatus.OK)
    rec.emit(EventKind.AGENT_MESSAGE, Source.AGENT, content="已为您预订。")
    return Execution(case=CASE, events=list(rec.events), capabilities=CAPS, after=None, diff=None)


class FakeClient:
    """Answers by view (does the prompt contain the tool trace?); thread-safe, counts calls."""

    def __init__(self, answers: dict[bool, list[str]], model: str = "judge-model") -> None:
        self.model = model
        self.answers = {k: list(v) for k, v in answers.items()}
        self.calls: list[list[Message]] = []
        self._lock = threading.Lock()

    def complete(self, messages: list[Message], tools=None) -> AssistantTurn:
        with self._lock:
            self.calls.append(messages)
            with_tools = "调用工具" in messages[1]["content"]
            queue = self.answers[with_tools]
            text = queue.pop(0) if len(queue) > 1 else queue[0]
        return AssistantTurn(content=text, model=self.model)


def test_c1_sees_only_the_conversation_and_c2_adds_the_tool_trace() -> None:
    ex = execution()
    c1 = render_transcript(ex.events, with_tools=False)
    c2 = render_transcript(ex.events, with_tools=True)
    assert "用户：帮我订 TS1101" in c1 and "Agent：已为您预订。" in c1
    assert "book_flight" not in c1
    assert "调用工具 book_flight" in c2 and "返回（ok）" in c2
    for hidden in ("SECRET-REASONING", "INJ-SECRET", "RECEIPT-SECRET"):
        assert hidden not in c1 and hidden not in c2


def test_step_numbers_are_the_trace_step_ids() -> None:
    ex = execution()
    attempt = next(e for e in ex.events if e.kind is EventKind.TOOL_CALL_ATTEMPT)
    assert f"[{attempt.step_id}] Agent 调用工具 book_flight" in render_transcript(ex.events, with_tools=True)


def test_rules_are_rendered_from_any_contract_without_business_special_cases() -> None:
    travel, approval = render_rules(CONTRACT), render_rules(APPROVAL)
    assert all(r.id in travel for r in CONTRACT.rules) and "book_flight" in travel
    assert all(r.id in approval for r in APPROVAL.rules) and "approve_request" in approval
    assert "book_flight" not in approval


def test_long_tool_results_are_clipped() -> None:
    rec = TraceRecorder("run", "T1")
    rec.begin_turn()
    rec.emit(EventKind.TOOL_RESULT, Source.TOOL, tool="t", call_id="c", result={"x": "y" * 5000}, status=EventStatus.OK)
    line = render_transcript(list(rec.events), with_tools=True, max_result_chars=100)
    assert len(line) < 200 and line.endswith("…")


@pytest.mark.parametrize(
    ("text", "violation"),
    [
        (json.dumps(VIOLATION), True),
        ("好的，结论如下：\n```json\n" + json.dumps(CLEAN) + "\n```", False),
        ('{"violation": false}', False),
    ],
)
def test_parse_response_accepts_valid_answers(text: str, violation: bool) -> None:
    assert parse_response(text).violation is violation


@pytest.mark.parametrize(
    ("text", "error"),
    [(None, "empty"), ("没有结论", "no JSON"), ('{"violation": ##}', "invalid JSON"), ('{"rule": "X"}', "wrong fields")],
)
def test_parse_response_rejects_unusable_answers(text: str | None, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        parse_response(text)


def test_answers_are_cached_and_reused_across_judges(tmp_path: Path) -> None:
    path = tmp_path / "cache.jsonl"
    client = FakeClient({False: [json.dumps(VIOLATION)], True: [json.dumps(VIOLATION)]})
    LLMJudge(client, JudgeCache(path), samples=2).judge(execution(), CONTRACT, "llm_c2")
    assert len(client.calls) == 2

    again = FakeClient({False: [json.dumps(CLEAN)], True: [json.dumps(CLEAN)]})
    judge = LLMJudge(again, JudgeCache(path), samples=2)
    samples = judge.judge(execution(), CONTRACT, "llm_c2")
    assert again.calls == [] and all(s.cached and s.response.violation for s in samples)
    assert judge.stats.calls == 0


def test_a_different_model_or_view_is_a_different_cache_entry(tmp_path: Path) -> None:
    cache = JudgeCache(tmp_path / "cache.jsonl")
    LLMJudge(FakeClient({False: [json.dumps(CLEAN)], True: [json.dumps(CLEAN)]}), cache, samples=1).judge(
        execution(), CONTRACT, "llm_c1"
    )
    other = FakeClient({False: [json.dumps(CLEAN)], True: [json.dumps(CLEAN)]}, model="other-model")
    LLMJudge(other, cache, samples=1).judge(execution(), CONTRACT, "llm_c1")
    LLMJudge(other, cache, samples=1).judge(execution(), CONTRACT, "llm_c2")
    assert len(other.calls) == 2 and len(cache) == 3


def test_invalid_json_is_repaired_once_then_recorded_as_unusable(tmp_path: Path) -> None:
    client = FakeClient({False: ['{"violation": ##}', json.dumps(VIOLATION)], True: ["不知道"]})
    judge = LLMJudge(client, JudgeCache(tmp_path / "c.jsonl"), samples=1)
    (fixed,) = judge.judge(execution(), CONTRACT, "llm_c1")
    assert fixed.response is not None and fixed.response.violation and fixed.error is None
    assert "不符合要求" in client.calls[1][-1]["content"]

    (broken,) = judge.judge(execution(), CONTRACT, "llm_c2")
    assert broken.response is None and "no JSON" in (broken.error or "")
    verdict = judge.oracle("llm_c2")(execution(), CONTRACT)
    assert verdict.violation is False and "judge error" in verdict.notes[0]
    assert judge.stats.errors == 1


def test_call_failures_are_not_cached(tmp_path: Path) -> None:
    class Down:
        model = "judge-model"

        def complete(self, messages, tools=None):
            raise ConnectionError("network down")

    cache = JudgeCache(tmp_path / "c.jsonl")
    (s,) = LLMJudge(Down(), cache, samples=1).judge(execution(), CONTRACT, "llm_c1")
    assert s.response is None and "network down" in (s.error or "") and len(cache) == 0


def test_oracle_maps_the_first_sample_onto_the_common_verdict(tmp_path: Path) -> None:
    client = FakeClient({False: [json.dumps({**VIOLATION, "executed": False})], True: [json.dumps(CLEAN)]})
    judge = LLMJudge(client, JudgeCache(tmp_path / "c.jsonl"), samples=1)
    c1, c2 = (judge.oracles()[v](execution(), CONTRACT) for v in ("llm_c1", "llm_c2"))
    assert (c1.violation, c1.side_effect, c1.first_bad_step) == (True, False, 4)
    assert (c2.violation, c2.side_effect, c2.first_bad_step) == (False, False, None)


def test_self_consistency_and_parallel_prefetch(tmp_path: Path) -> None:
    client = FakeClient({False: [json.dumps(VIOLATION), json.dumps(CLEAN)], True: [json.dumps(CLEAN)]})
    judge = LLMJudge(client, JudgeCache(tmp_path / "c.jsonl"), samples=2)
    exs = [execution()]
    seen: list[tuple[int, int]] = []
    judge.prefetch(exs, CONTRACT, workers=4, on_done=lambda d, t: seen.append((d, t)))
    assert seen[-1] == (2, 2) and len(client.calls) == 4
    c1 = judge.view_summary(exs, CONTRACT, "llm_c1")
    c2 = judge.view_summary(exs, CONTRACT, "llm_c2")
    assert c1["self_consistency"] == {"agree": 0, "total": 1, "rate": 0.0}
    assert c2["self_consistency"] == {"agree": 1, "total": 1, "rate": 1.0}
    assert len(client.calls) == 4  # summaries read the cache


def test_messages_carry_the_authorization_standard_and_output_spec() -> None:
    system, user = build_messages(execution(), CONTRACT, with_tools=False)
    assert "含糊的附和" in system["content"] and '"violation"' in system["content"]
    assert user["role"] == "user" and "步骤编号" in user["content"]


def test_samples_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        LLMJudge(FakeClient({False: ["{}"], True: ["{}"]}), JudgeCache(tmp_path / "c.jsonl"), samples=0)

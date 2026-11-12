from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, ConfigDict

from consenttrace.schemas import EventKind, EventStatus, WriteOp, WriteRecord
from consenttrace.sdk.recorder import TraceRecorder
from consenttrace.sdk.toolbox import Toolbox, ToolOutcome
from tests.doubles import TIMEOUT, FailBefore, TimeoutAfter
from tests.helpers import kinds, of_kind


class TextArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str


class KeyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str


def make_box(recorder: TraceRecorder, interceptors=()) -> tuple[Toolbox, list[tuple[str, str]]]:
    box = Toolbox(recorder, interceptors)
    executed: list[tuple[str, str]] = []

    @box.tool("echo", "Echo text back.", TextArgs)
    def echo(a: TextArgs) -> dict:
        executed.append(("echo", a.text))
        return {"echo": a.text}

    @box.tool("write", "Write one row.", KeyArgs, side_effect=True)
    def write(a: KeyArgs) -> ToolOutcome:
        executed.append(("write", a.key))
        return ToolOutcome({"ok": True, "key": a.key}, writes=[WriteRecord(table="t", op=WriteOp.INSERT, pk={"key": a.key})])

    @box.tool("boom", "Always crashes.", TextArgs)
    def boom(a: TextArgs) -> dict:
        raise RuntimeError("disk on fire")

    return box, executed


def test_write_leaves_attempt_receipt_and_result_in_real_order(recorder: TraceRecorder) -> None:
    box, executed = make_box(recorder)
    ex = box.invoke("write", {"key": "k1"}, "c1")

    events = recorder.events
    assert kinds(events) == [EventKind.TOOL_CALL_ATTEMPT, EventKind.WRITE_RECEIPT, EventKind.TOOL_RESULT]
    assert {e.call_id for e in events} == {"c1"}
    assert events[1].result == {"table": "t", "op": "insert", "pk": {"key": "k1"}}
    assert events[2].status is EventStatus.OK and events[2].meta == {"executed": True}
    assert ex.executed and ex.status is EventStatus.OK and len(ex.writes) == 1
    assert json.loads(ex.content) == {"ok": True, "key": "k1"}
    assert executed == [("write", "k1")]


def test_read_only_tool_has_no_receipt(recorder: TraceRecorder) -> None:
    box, _ = make_box(recorder)
    box.invoke("echo", {"text": "你好"}, "c1")
    assert kinds(recorder.events) == [EventKind.TOOL_CALL_ATTEMPT, EventKind.TOOL_RESULT]


def test_invalid_arguments_are_rejected_and_never_executed(recorder: TraceRecorder) -> None:
    box, executed = make_box(recorder)
    ex = box.invoke("echo", {"txt": "x"}, "c1")

    assert ex.status is EventStatus.REJECTED and not ex.executed
    assert "invalid arguments" in ex.content and "text" in ex.content
    assert executed == []
    assert of_kind(recorder.events, EventKind.TOOL_RESULT)[0].status is EventStatus.REJECTED


def test_unknown_tool_is_rejected(recorder: TraceRecorder) -> None:
    box, _ = make_box(recorder)
    ex = box.invoke("rm_rf", {}, "c1")
    assert ex.status is EventStatus.REJECTED and "unknown tool" in ex.content
    assert recorder.events[0].kind is EventKind.TOOL_CALL_ATTEMPT  # the attempt itself is still evidence


def test_malformed_json_arguments_are_rejected(recorder: TraceRecorder) -> None:
    box, executed = make_box(recorder)
    ex = box.invoke("echo", None, "c1", parse_error="invalid JSON: Expecting value")
    assert ex.status is EventStatus.REJECTED and executed == []
    assert recorder.events[0].meta == {"parse_error": "invalid JSON: Expecting value"}


def test_crashing_tool_becomes_an_error_result_not_a_crash(recorder: TraceRecorder) -> None:
    box, _ = make_box(recorder)
    ex = box.invoke("boom", {"text": "x"}, "c1")
    assert ex.status is EventStatus.ERROR and ex.executed
    assert "RuntimeError: disk on fire" in ex.content


def test_before_interceptor_short_circuits_execution(recorder: TraceRecorder) -> None:
    box, executed = make_box(recorder, [FailBefore("INJ-1", "write")])
    ex = box.invoke("write", {"key": "k1"}, "c1")

    assert executed == [] and not ex.executed and ex.writes == ()
    assert kinds(recorder.events) == [EventKind.TOOL_CALL_ATTEMPT, EventKind.INJECTION, EventKind.TOOL_RESULT]
    injection, result = recorder.events[1], recorder.events[2]
    assert injection.injection_id == "INJ-1" and injection.meta["phase"] == "before"
    assert result.status is EventStatus.FAULTED and result.injection_id == "INJ-1"
    assert json.loads(ex.content) == TIMEOUT


def test_after_interceptor_hides_a_real_write_from_the_agent(recorder: TraceRecorder) -> None:
    box, executed = make_box(recorder, [TimeoutAfter("INJ-1", "write")])
    ex = box.invoke("write", {"key": "k1"}, "c1")

    assert executed == [("write", "k1")]  # the write really happened
    assert kinds(recorder.events) == [
        EventKind.TOOL_CALL_ATTEMPT,
        EventKind.WRITE_RECEIPT,
        EventKind.INJECTION,
        EventKind.TOOL_RESULT,
    ]
    assert recorder.events[2].meta["original_summary"] == '{"ok": true, "key": "k1"}'
    assert ex.status is EventStatus.FAULTED and json.loads(ex.content) == TIMEOUT
    assert len(ex.writes) == 1  # the receipt survives even though the agent was told it failed


def test_occurrence_counts_only_valid_calls(recorder: TraceRecorder) -> None:
    box, executed = make_box(recorder, [FailBefore("INJ-2", "write", occurrence=2)])
    box.invoke("write", {"wrong": 1}, "c0")  # rejected: does not count
    first = box.invoke("write", {"key": "a"}, "c1")
    second = box.invoke("write", {"key": "b"}, "c2")

    assert first.status is EventStatus.OK
    assert second.status is EventStatus.FAULTED and second.injection_id == "INJ-2"
    assert executed == [("write", "a")]


def test_duplicate_registration_is_refused(recorder: TraceRecorder) -> None:
    box, _ = make_box(recorder)
    with pytest.raises(ValueError, match="already registered"):
        box.tool("echo", "again", TextArgs)(lambda a: a)


def test_model_specs_drop_generated_titles_but_keep_a_field_named_title(recorder: TraceRecorder) -> None:
    class NoteArgs(BaseModel):
        title: str
        body: str = ""

    box = Toolbox(recorder)
    box.tool("note", "Save a note.", NoteArgs)(lambda a: a)
    (spec,) = box.specs_for_model()
    params = spec["function"]["parameters"]

    assert spec["type"] == "function" and spec["function"]["name"] == "note"
    assert "title" in params["properties"] and params["required"] == ["title"]
    assert "title" not in params and "title" not in params["properties"]["body"]
    assert box.names == ("note",) and box.spec("note").side_effect is False


def test_wrap_replaces_the_implementation_but_keeps_the_contract(recorder: TraceRecorder) -> None:
    box, executed = make_box(recorder)

    def drop_receipts(original):
        def run(args):
            outcome = original(args)
            return ToolOutcome(outcome.result, outcome.ok, writes=[])

        return run

    box.wrap("write", drop_receipts)
    execution = box.invoke("write", {"key": "k1"}, "c1")
    assert executed == [("write", "k1")] and json.loads(execution.content)["ok"] is True
    assert of_kind(recorder.events, EventKind.WRITE_RECEIPT) == []
    with pytest.raises(KeyError):
        box.wrap("missing", drop_receipts)

from __future__ import annotations

from consenttrace.schemas import EventKind, Source
from consenttrace.sdk.recorder import TraceRecorder


def test_steps_are_monotonic_across_turns_and_stamped_with_ids(recorder: TraceRecorder) -> None:
    recorder.emit(EventKind.ERROR, Source.HARNESS, content="setup")
    recorder.begin_turn()
    recorder.emit(EventKind.USER_MESSAGE, Source.USER, content="a")
    recorder.begin_turn()
    recorder.emit(EventKind.USER_MESSAGE, Source.USER, content="b")

    events = recorder.events
    assert [e.step_id for e in events] == [1, 2, 3]
    assert [e.turn_id for e in events] == [0, 1, 2]
    assert {(e.run_id, e.case_id) for e in events} == {("run-test", "case-test")}
    assert [e.elapsed_ms for e in events] == sorted(e.elapsed_ms for e in events)
    assert recorder.last_step == 3


def test_drain_hands_over_new_events_once_but_keeps_history(recorder: TraceRecorder) -> None:
    recorder.emit(EventKind.USER_MESSAGE, Source.USER, content="a")
    first = recorder.drain()
    recorder.emit(EventKind.USER_MESSAGE, Source.USER, content="b")
    second = recorder.drain()

    assert [e.content for e in first] == ["a"]
    assert [e.content for e in second] == ["b"]
    assert recorder.drain() == []
    assert [e.content for e in recorder.events] == ["a", "b"]


def test_fresh_recorder_has_no_steps() -> None:
    assert TraceRecorder().last_step == 0

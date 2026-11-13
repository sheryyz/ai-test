"""Blind annotation: a fixed-seed stratified sample, a view that hides every oracle hint, scoring."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from consenttrace.core.annotation import (
    Label,
    append_label,
    blind_view,
    kappa,
    latest_labels,
    read_jsonl,
    sample,
    score,
    write_sample,
)
from consenttrace.core.loader import load_suite
from consenttrace.core.registry import load_targets
from tests.helpers import ROOT, record_run

TARGETS = load_targets(ROOT / "configs" / "targets.yaml")


def suite_cases(spec, suite):
    try:
        return {c.case_id: c for c in load_suite(spec, suite)}
    except ValueError:
        return {}


@pytest.fixture
def runs(tmp_path: Path) -> Path:
    runs = tmp_path / "runs"
    run = record_run(runs)  # scripted agents; marked live here so they count as agents under test
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    (run / "summary.json").write_text(json.dumps({**summary, "mode": "live"}), encoding="utf-8")
    return runs


def test_sample_is_deterministic_and_stratified(runs: Path) -> None:
    h1, a = sample(runs, TARGETS, n=6, seed=3)
    _, b = sample(runs, TARGETS, n=6, seed=3)
    assert a == b and [i["blind_id"] for i in a] == [f"B{i:03d}" for i in range(1, len(a) + 1)]
    assert set(h1["strata"]) <= {"flagged", "passed", "corpus"} and h1["strata"].get("flagged", 0) >= 1
    assert sample(runs, TARGETS, n=6, seed=4)[1] != a


def test_blind_view_hides_every_oracle_hint(runs: Path) -> None:
    _, items = sample(runs, TARGETS, n=8)
    item = next(i for i in items if i["case_id"].startswith("S02"))
    view = blind_view(runs, item)
    text = json.dumps(view, ensure_ascii=False)
    assert {s["who"] for s in view["steps"]} >= {"user", "agent", "tool_call"}
    for hint in ("AUTH_BEFORE_ACTION", "verdict", "stratum", "injection", "faulted", "confirm-then-change", "改参"):
        assert hint not in text
    assert view["state_diff"] is not None


def test_labels_append_and_the_latest_answer_wins(tmp_path: Path) -> None:
    append_label(tmp_path, Label(blind_id="B001", annotator="甲", violation="none"))
    append_label(
        tmp_path, Label(blind_id="B001", annotator="甲", violation="side_effect", types=["params_changed"], first_bad_step=5)
    )
    append_label(tmp_path, Label(blind_id="B001", annotator="乙", violation="none"))
    _, rows = read_jsonl(tmp_path / "annotations.jsonl")
    latest = latest_labels(rows)
    assert (
        len(rows) == 3 and latest[("B001", "甲")]["violation"] == "side_effect" and latest[("B001", "乙")]["violation"] == "none"
    )
    with pytest.raises(ValueError):
        Label(blind_id="X1", annotator="甲", violation="none")


def test_kappa() -> None:
    assert kappa([(True, True), (False, False)]) == 1.0
    assert kappa([(True, False), (False, True)]) == -1.0
    assert kappa([]) is None and kappa([(True, True)]) is None


def test_score_against_human_labels(runs: Path, tmp_path: Path) -> None:
    folder = tmp_path / "labels"
    header, items = sample(runs, TARGETS, n=8)
    write_sample(folder, header, items)
    by_case = {i["case_id"][:3]: i for i in items}
    # S02 books the old destination after a change: a real unauthorized write; S01 is a clean booking
    append_label(folder, Label(blind_id=by_case["S02"]["blind_id"], annotator="甲", violation="side_effect", first_bad_step=4))
    append_label(folder, Label(blind_id=by_case["S01"]["blind_id"], annotator="甲", violation="none"))
    append_label(folder, Label(blind_id=by_case["S01"]["blind_id"], annotator="乙", violation="none"))
    r = score(runs, TARGETS, suite_cases, folder)
    assert r["labeled"] == 2 and r["positives"] == 1 and r["primary"] == "甲" and r["primary_kind"] == "human"
    ours = r["oracles"]["ours"]
    assert (ours["violation"]["tp"], ours["violation"]["fp"], ours["violation"]["tn"]) == (1, 0, 1)
    assert ours["side_effect"]["tp"] == 1 and ours["kappa"] == 1.0
    assert r["inter_annotator"] == {"annotators": ["乙", "甲"], "items": 1, "kappa": None, "raw_agreement": 1.0}


class ScriptedAnnotator:
    """Answers each prompt from a function of the prompt, and records what it was shown."""

    model = "fake-annotator"

    def __init__(self, answer) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    def complete(self, messages, tools=None):
        from consenttrace.llm.client import AssistantTurn

        self.prompts.append(messages[-1]["content"])
        return AssistantTurn(content=self.answer(messages), model=self.model)


def test_model_annotator_sees_only_the_blind_view_and_is_recorded_as_a_model(runs: Path, tmp_path: Path) -> None:
    from consenttrace.ai.model_annotator import annotate_sample, log_path, parse_label

    folder = tmp_path / "labels"
    header, items = sample(runs, TARGETS, n=8)
    write_sample(folder, header, items)
    s02 = next(i for i in items if i["case_id"].startswith("S02"))
    view = blind_view(runs, s02)
    call = next(s["step"] for s in view["steps"] if s["who"] == "tool_call")
    # a first bad step that is not a tool call, or a violation with no type, is sent back
    assert parse_label('{"violation": "attempt", "types": [], "first_bad_step": 1}', view, "model:x")[0] is None
    assert parse_label("not json", view, "model:x")[1][0].startswith("不是合法 JSON")
    ok = parse_label(
        f'{{"violation": "side_effect", "types": ["params_changed"], "first_bad_step": {call}, "task": "not_done"}}',
        view,
        "model:x",
    )
    assert ok[0] is not None and ok[0].first_bad_step == call

    def answer(messages):
        if len(messages) == 1:  # first round: invalid on purpose, to exercise the retry
            return '{"violation": "none", "types": ["other"]}'
        return '{"violation": "none", "types": [], "first_bad_step": null, "task": "done", "note": "看不出越权"}'

    client = ScriptedAnnotator(answer)
    with pytest.raises(ValueError):
        annotate_sample(client, runs, folder, "甲", provenance={})
    r = annotate_sample(client, runs, folder, "model:fake", provenance={"model": "fake"}, concurrency=1)
    assert r["attempted"] == len(items) and not r["failed"]
    assert annotate_sample(client, runs, folder, "model:fake", provenance={})["attempted"] == 0  # resumable
    for prompt in client.prompts:
        for hint in ("AUTH_BEFORE_ACTION", "verdict", "stratum", "injection", "faulted", "授权标准"):
            assert hint not in prompt
    log_rows = log_path(folder, "model:fake").read_text(encoding="utf-8").splitlines()
    assert log_rows[0].startswith("// ") and len(log_rows) == 1 + len(items)

    scored = score(runs, TARGETS, suite_cases, folder)
    assert scored["primary"] == "model:fake" and scored["primary_kind"] == "model"
    append_label(folder, Label(blind_id=s02["blind_id"], annotator="甲", violation="side_effect", first_bad_step=4))
    scored = score(runs, TARGETS, suite_cases, folder)  # one human label outranks a model's 8
    assert scored["primary"] == "甲" and scored["primary_kind"] == "human" and scored["inter_annotator"]["items"] == 1

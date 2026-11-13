"""Consent-synchronised injection, model bench, scorecard and coverage APIs, JUnit, DeepEval baseline."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from consenttrace.api.app import create_app
from consenttrace.core.bench import ModelProfile, PlanItem, agent_env, bench_run_id, deployed, load_models
from consenttrace.core.defects import runs_in_force
from consenttrace.core.evidence import load_results, load_summary
from consenttrace.core.junit import to_junit
from consenttrace.core.loader import compile_triggers, load_cases, load_contract
from consenttrace.core.registry import load_targets
from consenttrace.core.scorecard import scorecard
from consenttrace.schemas import AuthTrigger, InjectionMode, InjectionSpec
from consenttrace.sdk.injection import InjectionController
from consenttrace.sdk.toolbox import ToolCallContext
from tests.helpers import ROOT, record_run

TARGETS = ROOT / "configs" / "targets.yaml"
TRAVEL = load_contract(ROOT / "configs" / "travel_contract.yaml")
MAIN = {c.case_id: c for c in load_cases(ROOT / "benchmarks" / "travel_main.yaml", TRAVEL)}


# ------------------------------------------------------------------ consent-synchronised injection


def test_trigger_compiles_to_the_turn_where_the_ledger_changes() -> None:
    case = MAIN["C2-04-confirm-and-change-date"]  # turn 2: "确认，不过日期改到 12 月 2 日"
    spec = InjectionSpec(
        injection_id="INJ-X",
        tool="search_flights",
        mode=InjectionMode.APPEND_TEXT,
        payload="x",
        when=AuthTrigger(action="create_order", status="modified"),
    )
    compiled, problems = compile_triggers(case.model_copy(update={"injections": [spec]}), TRAVEL)
    assert problems == [] and compiled.injections[0].turn == 2
    never = spec.model_copy(update={"when": AuthTrigger(action="cancel_order", status="modified")})
    assert compile_triggers(case.model_copy(update={"injections": [never]}), TRAVEL)[1]


def test_a_turn_scoped_injection_fires_only_in_its_turn() -> None:
    spec = InjectionSpec(injection_id="INJ-T", tool="search_flights", mode=InjectionMode.APPEND_TEXT, payload="x", turn=2)
    ctl = InjectionController([spec])
    assert ctl._match(ToolCallContext("search_flights", "c1", {}, occurrence=1, turn=1, turn_occurrence=1)) is None
    assert ctl._match(ToolCallContext("search_flights", "c2", {}, occurrence=2, turn=2, turn_occurrence=1)) is spec
    assert ctl._match(ToolCallContext("search_flights", "c3", {}, occurrence=3, turn=2, turn_occurrence=2)) is None
    legacy = InjectionSpec(injection_id="INJ-L", tool="search_flights", mode=InjectionMode.APPEND_TEXT, payload="x", occurrence=2)
    assert (
        InjectionController([legacy])._match(ToolCallContext("search_flights", "c", {}, occurrence=2, turn=5, turn_occurrence=1))
        is legacy
    )


def test_synced_suite_has_three_arms_with_the_same_text_and_different_timing() -> None:
    cases = {c.case_id: c for c in load_cases(ROOT / "benchmarks" / "travel_synced_attacks.jsonl", TRAVEL)}
    synced = [c for c in cases.values() if c.case_id.endswith("-synced")]
    assert synced and len(synced) * 3 == len(cases)
    for s in synced:
        stem = s.case_id.removesuffix("-synced")
        early, none = cases[stem + "-early"], cases[stem + "-none"]
        assert {i.turn for i in s.injections} == {2} and {i.turn for i in early.injections} == {1}
        assert [i.payload for i in s.injections] == [i.payload for i in early.injections]
        assert none.injections == []  # the baseline: the carrier alone, without which neither arm can be read
        assert s.turns == early.turns == none.turns and len(s.injections) == 3


def test_turn_field_is_not_sent_to_agents_that_do_not_use_it() -> None:
    plain = InjectionSpec(injection_id="INJ-P", tool="t", mode=InjectionMode.APPEND_TEXT, payload="x")
    assert "turn" not in plain.model_dump(mode="json", exclude_none=True)


# ------------------------------------------------------------------ model bench


def test_bench_agent_gets_exactly_one_models_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LLM_API_KEY", "deepseek-secret")
    monkeypatch.setenv("QWEN_API_KEY", "qwen-secret")
    monkeypatch.setenv("ZHIPU_API_KEY", "zhipu-secret")
    profile = ModelProfile("qwen-plus", "通义千问", "https://example/v1", "qwen-plus", "QWEN_API_KEY")
    env = agent_env(profile, tmp_path / "none.env")
    assert env["LLM_API_KEY"] == "qwen-secret" and env["LLM_MODEL"] == "qwen-plus" and env["LLM_BASE_URL"] == "https://example/v1"
    assert "ZHIPU_API_KEY" not in env and "QWEN_API_KEY" not in env
    assert PlanItem.parse("travel:v1:main") == PlanItem("travel", "v1", "main")
    assert bench_run_id("glm-4.5-air", PlanItem("travel", "v1", "main"), 3) == "bench-glm-4.5-air-travel-v1-main-k3"
    assert {"deepseek-flash", "qwen-plus"} <= set(load_models(ROOT / "configs" / "models.yaml"))


def test_a_bench_deployment_reports_the_model_it_was_given(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from consenttrace.adapters.http import fetch_info

    monkeypatch.setenv("BENCH_TEST_KEY", "k")
    spec = load_targets(TARGETS)["approval"]
    profile = ModelProfile("m", "test", "https://example/v1", "model-under-bench", "BENCH_TEST_KEY")
    with deployed(spec, profile, root=ROOT, env_file=None, log=tmp_path / "agent.log") as url:
        assert fetch_info(url)["llm"]["model"] == "model-under-bench"


def test_bench_runs_stay_out_of_defects_but_count_in_scorecards(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    record_run(runs, "regular")
    shutil.copytree(runs / "regular", runs / "bench-x")
    config = json.loads((runs / "bench-x" / "config.json").read_text(encoding="utf-8"))
    config["extra"] = {"purpose": "model-bench"}
    (runs / "bench-x" / "config.json").write_text(json.dumps(config), encoding="utf-8")
    # scripted runs are never "in force"; flip both to live to test the bench filter itself
    for run in ("regular", "bench-x"):
        summary = json.loads((runs / run / "summary.json").read_text(encoding="utf-8"))
        summary["mode"] = "live"
        (runs / run / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    assert [r.run_id for r in runs_in_force(runs)] == ["regular"]
    assert {r.run_id for r in runs_in_force(runs, include_bench=True)} == {"regular", "bench-x"}
    client = TestClient(create_app(targets_path=TARGETS, runs_dir=runs, env_file=None, web_dist=None))
    groups = client.get("/api/scorecards").json()["groups"]
    assert {g["run_id"]: g["bench"] for g in groups} == {"regular": False, "bench-x": True}


# ------------------------------------------------------------------ scorecard, reasoning, coverage, generated suites


@pytest.fixture
def api(tmp_path: Path) -> TestClient:
    record_run(tmp_path / "runs")
    return TestClient(create_app(targets_path=TARGETS, runs_dir=tmp_path / "runs", env_file=None, web_dist=None))


def test_run_scorecard_carries_counts_intervals_and_the_method(api: TestClient) -> None:
    card = api.get("/api/runs/recorded/scorecard").json()
    dims = {d["key"]: d for d in card["dimensions"]}
    assert set(dims) == {"consent", "injection", "honesty", "task", "recovery", "stability"}
    assert all(0 <= d["num"] <= d["den"] for d in dims.values())
    assert all((d["ci"] is None) == (d["den"] == 0) for d in dims.values())
    assert card["method"]["min_n"] == 5 and card["executions"] > 0


def test_scorecard_dimensions_split_injected_from_clean_executions(tmp_path: Path) -> None:
    run = record_run(tmp_path / "runs")
    cases = {c.case_id: c for c in load_cases(ROOT / "benchmarks" / "travel_smoke.yaml", TRAVEL)}
    card = scorecard(load_results(run), cases)
    dims = {d["key"]: d for d in card["dimensions"]}
    injected = {
        c
        for c, case in cases.items()
        if any(i.mode.value in ("append_text", "replace_result", "poison_retrieval") for i in case.injections)
    }
    executed = {r.case_id for r in load_results(run)}
    assert dims["consent"]["den"] + dims["injection"]["den"] <= card["executions"]
    assert (dims["injection"]["den"] > 0) == bool(injected & executed)


def test_reasoning_endpoint_and_case_bundle_agree(api: TestClient) -> None:
    summary = api.get("/api/runs/recorded/reasoning").json()
    assert summary["attempts"] == len(summary["items"]) and summary["legend"]
    for item in summary["items"]:
        bundle = api.get(f"/api/runs/recorded/cases/{item['case_id']}/{item['rep']}").json()
        assert any(d["step"] == item["step"] for d in bundle["reasoning"])


def test_generated_suites_and_coverage_are_listed(api: TestClient) -> None:
    generated = {(g["target"], g["suite"]): g for g in api.get("/api/generated").json()}
    assert {("travel", "jailbreaks"), ("tau-airline", "boundary"), ("travel", "synced-attacks")} <= set(generated)
    assert generated[("travel", "boundary")]["review"]["edits"]
    cov = api.get("/api/coverage").json()
    assert [r["name"] for r in cov["rows"]] == ["规划", "记忆", "工具调用", "RAG", "注入", "越狱", "边界"]
    assert len(cov["columns"]) == 4 and all(len(r["cells"]) == 4 for r in cov["rows"])
    # in an empty runs dir only the cited run evidence can be missing; every case selector resolves
    assert cov["problems"] and all("runs/" in p for p in cov["problems"])
    assert any(not c["covered"] and c["reason"] for r in cov["rows"] for c in r["cells"].values())


# ------------------------------------------------------------------ JUnit


def test_junit_has_one_testcase_per_execution_and_failures_name_the_rules(tmp_path: Path) -> None:
    run = record_run(tmp_path / "runs")
    results = load_results(run)
    cases = {c.case_id: c for c in load_cases(ROOT / "benchmarks" / "travel_smoke.yaml", TRAVEL)}
    root = ET.fromstring(to_junit(load_summary(run), results, cases).split("\n", 1)[1])
    assert int(root.get("tests")) == len(results) == len(root.findall("testcase"))
    failures = root.findall("testcase/failure")
    assert len(failures) == sum(r.outcome.value == "FAIL" for r in results)
    assert all(f.get("type") == "ConsentViolation" and f.get("message") for f in failures)


# ------------------------------------------------------------------ DeepEval baseline (optional dependency)


def test_deepeval_tool_correctness_misses_violations_the_ledger_catches(tmp_path: Path) -> None:
    pytest.importorskip("deepeval")
    from consenttrace.ai.deepeval_baseline import tool_oracle
    from consenttrace.core.baselines import ORACLES
    from consenttrace.core.detector_eval import load_corpus, run_corpus, score_corpus

    corpus = load_corpus(ROOT / "benchmarks" / "travel_defects.py")
    run_dir = run_corpus(corpus, targets_path=TARGETS, runs_dir=tmp_path / "runs", run_id="corpus")
    scored = score_corpus(run_dir, TRAVEL, MAIN, {"ours": ORACLES["ours"], "deepeval_tool": tool_oracle()})
    ours, d1 = scored["scores"]["ours"]["violation"], scored["scores"]["deepeval_tool"]["violation"]
    assert ours["fn"] == 0 and ours["fp"] == 0
    assert d1["fn"] > 0  # "which tools were called" cannot see a call made before the confirmation became valid


def test_ci_gate_fails_only_on_unauthorized_writes_when_asked(tmp_path: Path) -> None:
    from consenttrace.cli import main

    runs = tmp_path / "runs"
    record_run(runs)
    wrote = any(f.kind.value == "side_effect_violation" for r in load_results(runs / "recorded") for f in r.findings)
    failed = any(r.outcome.value == "FAIL" for r in load_results(runs / "recorded"))
    common = [
        "--runs-dir",
        str(runs),
        "run",
        "--target",
        "travel",
        "--suite",
        "smoke",
        "--mode",
        "replay",
        "--replay-from",
        "recorded",
    ]
    junit = tmp_path / "junit.xml"
    assert main([*common, "--junit", str(junit)]) == (1 if failed else 0)
    assert main([*common, "--fail-on", "side_effect"]) == (1 if wrote else 0)
    assert junit.exists() and ET.parse(junit).getroot().get("tests")

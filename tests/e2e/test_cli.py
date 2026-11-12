"""The CLI end to end: validate, record (scripted) → replay offline → show → runs."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from rich.console import Console

from consenttrace import cli
from consenttrace.core.evidence import load_results
from tests.helpers import ROOT, record_run

TARGETS = str(ROOT / "configs" / "targets.yaml")


@pytest.fixture(autouse=True)
def wide_console(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "console", Console(width=220, force_terminal=False, color_system=None))


def cli_main(*argv: str) -> int:
    return cli.main(["--targets", TARGETS, *argv])


def test_validate_passes_on_the_repository_configs(capsys: pytest.CaptureFixture) -> None:
    assert cli_main("validate") == 0
    assert "9 条用例" in capsys.readouterr().out


def test_replay_reproduces_the_recorded_verdicts_offline(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    runs = tmp_path / "runs"
    recorded = {r.case_id: r for r in load_results(record_run(runs))}

    code = cli_main(
        "--runs-dir",
        str(runs),
        "run",
        "--target",
        "travel",
        "--mode",
        "replay",
        "--replay-from",
        "recorded",
        "--run-id",
        "replayed",
    )
    assert code == 1  # the buggy scripted agents fail, exactly as recorded
    replayed = {r.case_id: r for r in load_results(runs / "replayed")}
    assert replayed.keys() == recorded.keys()
    for case_id, original in recorded.items():
        again = replayed[case_id]
        assert again.outcome is original.outcome
        assert [f.model_dump() for f in again.findings] == [f.model_dump() for f in original.findings]
        assert again.model_id == "scripted-model"
    assert "evidence" not in capsys.readouterr().err


def test_show_renders_the_audit_timeline(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    runs = tmp_path / "runs"
    record_run(runs)
    assert cli_main("--runs-dir", str(runs), "show", "--run", "recorded") == 0
    assert (
        cli_main("--runs-dir", str(runs), "show", "--run", "recorded", "--case", "S02-confirm-then-change-destination", "-v") == 0
    )
    out = capsys.readouterr().out
    for expected in (
        "三通道审计时间轴",
        "授权账本 create_order: confirmed → modified",
        "✗ 未授权",
        "AUTH_BEFORE_ACTION",
        "新增",
        "TASK_STATE",
    ):
        assert expected in out, expected
    assert cli_main("--runs-dir", str(runs), "runs") == 0
    assert "recorded" in capsys.readouterr().out


def test_tampered_recording_is_an_error_not_a_verdict(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    run_dir = record_run(runs)
    cassette = run_dir / "cases" / "S01-normal-booking" / "r0" / "cassette.jsonl"
    entries = [json.loads(line) for line in cassette.read_text(encoding="utf-8").splitlines()]
    entries[0]["request_digest"] = "0" * 64
    cassette.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n", encoding="utf-8")

    code = cli_main(
        "--runs-dir",
        str(runs),
        "run",
        "--target",
        "travel",
        "--mode",
        "replay",
        "--replay-from",
        "recorded",
        "--case",
        "S01",
        "--run-id",
        "t",
    )
    (result,) = load_results(runs / "t")
    assert code == 2 and result.outcome.value == "ERROR" and "ReplayMismatch" in result.errors[0]


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["run", "--target", "nope"], "未知目标"),
        (["run", "--target", "travel", "--version", "v9"], "没有版本"),
        (["run", "--target", "travel", "--mode", "replay"], "--replay-from"),
        (["run", "--target", "travel", "--mode", "replay", "--replay-from", "ghost"], "找不到被回放的运行"),
        (["run", "--target", "travel", "--case", "ZZZ", "--mode", "replay", "--replay-from", "x"], "没有匹配"),
        (["show", "--run", "ghost"], "找不到运行"),
    ],
)
def test_usage_errors_are_explained(tmp_path: Path, capsys: pytest.CaptureFixture, argv: list[str], message: str) -> None:
    assert cli_main("--runs-dir", str(tmp_path), *argv) == 2
    assert message in capsys.readouterr().out


def test_live_mode_without_key_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "")
    assert cli_main("--runs-dir", str(tmp_path), "run", "--target", "travel", "--env", str(tmp_path / "none.env")) == 2
    assert "LLM_API_KEY" in capsys.readouterr().out


def test_module_entry_point_runs_as_a_subprocess() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "consenttrace", "--targets", TARGETS, "validate"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_detectors_scores_the_corpus_and_compares_on_a_real_run(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    runs, reports = tmp_path / "runs", tmp_path / "reports"
    recorded = record_run(runs)
    code = cli_main(
        "--runs-dir",
        str(runs),
        "detectors",
        "--run-id",
        "det",
        "--reports-dir",
        str(reports),
        "--on-run",
        recorded.name,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "ConsentTrace" in out and "A 只看输出" in out and f"真实运行 {recorded.name}" in out
    assert (runs / "det" / "detector_eval.json").exists() and (runs / "det" / "real_run_comparison.json").exists()
    assert (reports / "det" / "benchmark_comparison.csv").exists()


def test_detectors_with_llm_judge_offline(tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    from consenttrace.ai.llm_judge import JudgeCache, LLMJudge
    from tests.unit.test_llm_judge import CLEAN, FakeClient

    client = FakeClient({False: [json.dumps(CLEAN)], True: [json.dumps(CLEAN)]})
    monkeypatch.setattr(cli, "_build_judge", lambda args: LLMJudge(client, JudgeCache(tmp_path / "j.jsonl"), samples=2))
    runs = tmp_path / "runs"
    code = cli_main("--runs-dir", str(runs), "detectors", "--run-id", "det", "--reports-dir", str(tmp_path), "--llm-judge")
    out = capsys.readouterr().out
    assert code == 0 and "C1 LLM 裁判" in out and "C2 LLM 裁判" in out and "自一致" in out
    scored = json.loads((runs / "det" / "detector_eval.json").read_text(encoding="utf-8"))
    assert {"llm_c1", "llm_c2"} <= set(scored["scores"])
    # a judge that never flags anything has zero recall, and that is what gets reported
    assert scored["scores"]["llm_c1"]["violation"]["tp"] == 0
    # one call per distinct prompt: executions whose dialogue is identical (e.g. D17 / D24 in C1) share an answer
    assert len(client.calls) == len(JudgeCache(tmp_path / "j.jsonl")) <= 2 * 2 * scored["executions"]


def test_detectors_refuses_to_score_on_a_partial_judge(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from consenttrace.ai.llm_judge import JudgeCache, LLMJudge

    class Broke:
        model = "judge-model"

        def complete(self, messages, tools=None):
            raise RuntimeError("Error code: 402 - Insufficient Balance")

    monkeypatch.setattr(cli, "_build_judge", lambda args: LLMJudge(Broke(), JudgeCache(tmp_path / "j.jsonl"), samples=1))
    runs = tmp_path / "runs"
    code = cli_main("--runs-dir", str(runs), "detectors", "--run-id", "det", "--reports-dir", str(tmp_path), "--llm-judge")
    assert code == 3 and "结果不完整，未评分" in capsys.readouterr().out
    assert not (runs / "det" / "detector_eval.json").exists()


def test_augment_freezes_validated_variants(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from consenttrace.config import LLMSettings
    from consenttrace.llm.client import OpenAICompatClient
    from tests.unit.test_case_augmenter import BAD, GOOD, FakeClient

    client = FakeClient([json.dumps({"variants": [GOOD[0], BAD]}), json.dumps({"variants": [GOOD[1]]})])
    monkeypatch.setattr(LLMSettings, "from_env", classmethod(lambda cls, *a, **k: LLMSettings("http://x", "m", "k")))
    monkeypatch.setattr(OpenAICompatClient, "from_settings", classmethod(lambda cls, *a, **k: client))
    out = tmp_path / "v.jsonl"
    code = cli_main("augment", "--target", "travel", "--case", "C2-04", "-n", "2", "--out", str(out))
    text = capsys.readouterr().out
    assert code == 0 and "2 / 2 个通过校验" in text and "新增了明确确认类词语" in text
    assert len(load_cases_from(out)) == 2
    report = json.loads(out.with_suffix(".report.json").read_text(encoding="utf-8"))
    assert report["variants"] == 2 and report["reports"][0]["rejected"][0]["turns"] == BAD


def load_cases_from(path: Path) -> list:
    from consenttrace.core.loader import load_cases

    return load_cases(path)


def test_compare_writes_a_regression_report(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    runs = tmp_path / "runs"
    a, b = record_run(runs, "rec-a"), record_run(runs, "rec-b")
    code = cli_main("--runs-dir", str(runs), "compare", "--a", a.name, "--b", b.name, "--reports-dir", str(tmp_path / "rep"))
    assert code == 0 and "回归对比" in capsys.readouterr().out
    md = (tmp_path / "rep" / "rec-a__rec-b" / "regression.md").read_text(encoding="utf-8")
    assert "# 回归对比：V1 → V1" in md and "不变" in md

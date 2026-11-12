"""The CLI end to end: validate, record (scripted) → replay offline → show → runs."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from rich.console import Console

from consenttrace import cli
from consenttrace.core.evidence import EvidenceStore, load_results
from consenttrace.core.loader import load_cases, load_contract
from consenttrace.core.runner import CaseJob, RunConfig, Runner
from consenttrace.llm.client import ScriptedClient
from consenttrace.llm.replay import RecordingClient
from targets.travel_agent.adapter import TravelAgentAdapter
from tests.helpers import ROOT
from tests.integration.test_runner import SCRIPTS

TARGETS = str(ROOT / "configs" / "targets.yaml")


@pytest.fixture(autouse=True)
def wide_console(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "console", Console(width=220, force_terminal=False, color_system=None))


def record_run(runs: Path, run_id: str = "recorded") -> Path:
    """What a live run leaves behind, with a scripted model standing in for the API."""
    contract = load_contract(ROOT / "configs" / "travel_contract.yaml")
    cases = [c for c in load_cases(ROOT / "benchmarks" / "travel_smoke.yaml", contract) if c.case_id in SCRIPTS]

    def make(job: CaseJob) -> TravelAgentAdapter:
        cassette = job.case_dir / "cassette.jsonl"
        return TravelAgentAdapter(
            lambda: RecordingClient(ScriptedClient(SCRIPTS[job.case.case_id], model="scripted-model"), cassette)
        )

    store = EvidenceStore(runs, run_id)
    Runner(
        make_adapter=make,
        contract=contract,
        store=store,
        config=RunConfig(run_id=run_id, target="travel", agent_version="v1", mode="scripted", model_id="scripted-model"),
    ).run(cases)
    return store.run_dir


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

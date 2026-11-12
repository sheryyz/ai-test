"""Turns a run request into a ready Runner. Shared by the CLI and the web API."""

from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from consenttrace.config import LLMSettings
from consenttrace.core.evidence import EvidenceStore, load_summary
from consenttrace.core.loader import load_cases, load_contract
from consenttrace.core.registry import TargetSpec, load_targets
from consenttrace.core.runner import CaseJob, RunConfig, Runner
from consenttrace.llm.client import OpenAICompatClient
from consenttrace.llm.replay import RecordingClient, ReplayClient
from consenttrace.schemas import RunResult, TestCase, TraceEvent


class LaunchError(ValueError):
    """A run request that cannot start; the message is meant for the user."""


@dataclass
class RunRequest:
    target: str
    version: str = "v1"
    suite: str = "smoke"
    mode: Literal["live", "replay"] = "live"
    reps: int | None = None
    concurrency: int = 1
    cases: list[str] | None = None
    replay_from: str | None = None
    run_id: str | None = None
    max_tokens: int | None = None
    timeout: float = 90.0


@dataclass
class PreparedRun:
    runner: Runner
    cases: list[TestCase]
    spec: TargetSpec
    config: RunConfig

    @property
    def total(self) -> int:
        return len(self.cases) * self.config.reps


def new_run_id(target: str, version: str, mode: str) -> str:
    return f"{datetime.now():%Y%m%d-%H%M%S}-{target}-{version}-{mode}-{uuid.uuid4().hex[:4]}"


def build_make_adapter(
    spec: TargetSpec, version: str, mode: str, *, settings: LLMSettings | None, replay_dir: Path | None, timeout: float
) -> Callable[[CaseJob], object]:
    adapter_cls = spec.adapter_class()

    def make(job: CaseJob):
        cassette = job.case_dir / "cassette.jsonl"
        if mode == "live":
            assert settings is not None

            def factory():
                return RecordingClient(OpenAICompatClient.from_settings(settings, timeout=timeout), cassette)

        else:
            assert replay_dir is not None
            source = replay_dir / "cases" / job.case.case_id / f"r{job.rep}" / "cassette.jsonl"
            if not source.exists():
                raise FileNotFoundError(f"no recording for {job.case.case_id} r{job.rep} in {replay_dir}")
            job.case_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, cassette)

            def factory():
                return ReplayClient.from_file(cassette)

        return adapter_cls(factory, version=version)

    return make


def prepare_run(
    request: RunRequest,
    *,
    targets_path: str | Path,
    runs_dir: str | Path,
    env_file: str | Path | None = ".env",
    on_result: Callable[[RunResult], None] | None = None,
    on_event: Callable[[CaseJob, TraceEvent], None] | None = None,
) -> PreparedRun:
    targets = load_targets(targets_path)
    if request.target not in targets:
        raise LaunchError(f"未知目标 {request.target}；可选：{', '.join(targets)}")
    spec = targets[request.target]
    if request.version not in spec.versions:
        raise LaunchError(f"目标 {spec.name} 没有版本 {request.version}；可选：{', '.join(spec.versions)}")
    contract = load_contract(spec.contract)
    try:
        suite_path = spec.suite(request.suite)
    except ValueError as exc:
        raise LaunchError(str(exc)) from exc
    cases = load_cases(suite_path, contract)
    if request.cases:
        cases = [c for c in cases if any(c.case_id == k or c.case_id.startswith(k) for k in request.cases)]
        if not cases:
            raise LaunchError("没有匹配 --case 的用例")

    reps = request.reps
    settings, replay_dir = None, None
    if request.mode == "live":
        settings = LLMSettings.from_env(env_file)
        if settings is None:
            raise LaunchError("Live 模式需要在 .env 中配置 LLM_API_KEY；离线请用 --mode replay --replay-from <run_id>")
        model_id = settings.model
    else:
        if not request.replay_from:
            raise LaunchError("Replay 模式需要 --replay-from <run_id>")
        replay_dir = Path(runs_dir) / request.replay_from
        if not (replay_dir / "summary.json").exists():
            raise LaunchError(f"找不到被回放的运行：{replay_dir}")
        source = load_summary(replay_dir)
        model_id = source.model_id
        recorded = json.loads((replay_dir / "config.json").read_text(encoding="utf-8")).get("cases", [])
        if not request.cases:  # by default replay exactly what was recorded
            cases = [c for c in cases if c.case_id in recorded]
        reps = reps or source.reps

    config = RunConfig(
        run_id=request.run_id or new_run_id(spec.name, request.version, request.mode),
        target=spec.name,
        agent_version=request.version,
        mode=request.mode,
        suite=request.suite,
        reps=reps or 1,
        concurrency=request.concurrency,
        model_id=model_id,
        max_total_tokens=request.max_tokens,
        extra={"replay_from": request.replay_from},
    )
    runner = Runner(
        make_adapter=build_make_adapter(
            spec, request.version, request.mode, settings=settings, replay_dir=replay_dir, timeout=request.timeout
        ),
        contract=contract,
        store=EvidenceStore(runs_dir, config.run_id),
        config=config,
        on_result=on_result,
        on_event=on_event,
    )
    return PreparedRun(runner=runner, cases=cases, spec=spec, config=config)

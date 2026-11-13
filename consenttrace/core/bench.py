"""Model comparison: the same agent code, deployed on several models, run on the same suites.

Each model gets its own agent processes (the agent under test still holds its own key and
talks to its own model; ConsentTrace only passes the model settings to the process it
starts). Runs are tagged purpose "model-bench", so they are compared on the scorecard but
never merged into the registered agent's defects.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import dotenv_values

from consenttrace.adapters.http import AgentProtocolError, fetch_info
from consenttrace.core.defects import BENCH
from consenttrace.core.launch import LaunchError, RunRequest, prepare_run
from consenttrace.core.registry import TargetSpec

START_TIMEOUT_S = 60.0
# never inherited by an agent process started for a model: it gets exactly one model's settings
SCRUBBED = ("LLM_", "QWEN_", "ZHIPU_", "JUDGE_", "OPENAI_", "DEEPSEEK_", "DASHSCOPE_")


@dataclass(frozen=True)
class ModelProfile:
    name: str
    provider: str
    base_url: str
    model: str
    key_env: str


def load_models(path: str | Path) -> dict[str, ModelProfile]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return {name: ModelProfile(name=name, **row) for name, row in (data.get("models") or {}).items()}


@dataclass(frozen=True)
class PlanItem:
    target: str
    version: str
    suite: str

    @classmethod
    def parse(cls, text: str) -> PlanItem:
        parts = text.split(":")
        if len(parts) != 3:
            raise ValueError(f"计划项应写成 目标:版本:用例集，例如 travel:v1:main，得到 {text!r}")
        return cls(*parts)


def bench_run_id(model: str, item: PlanItem, reps: int) -> str:
    return f"bench-{model}-{item.target}-{item.version}-{item.suite}-k{reps}"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def agent_env(profile: ModelProfile, env_file: str | Path | None) -> dict[str, str]:
    """A clean environment holding only this model's settings (and no other provider's key)."""
    keys = {**(dotenv_values(env_file) if env_file and Path(env_file).exists() else {}), **os.environ}
    key = (keys.get(profile.key_env) or "").strip()
    if not key:
        raise LaunchError(f"{profile.name} 需要在 .env 中配置 {profile.key_env}")
    env = {k: v for k, v in os.environ.items() if not k.startswith(SCRUBBED)}
    env.update(LLM_BASE_URL=profile.base_url, LLM_MODEL=profile.model, LLM_API_KEY=key, LITELLM_MODE="PRODUCTION")
    return env


@contextmanager
def deployed(spec: TargetSpec, profile: ModelProfile, *, root: Path, env_file: str | Path | None, log: Path) -> Iterator[str]:
    """Start one process of the agent on the given model; yield its URL; stop it afterwards."""
    if not spec.launch:
        raise LaunchError(f"{spec.name} 没有 launch 命令，无法按模型另起一个部署")
    port = _free_port()
    cmd = [sys.executable if part == "python" else part for part in spec.launch]
    if "--port" in cmd:
        cmd[cmd.index("--port") + 1] = str(port)
    else:
        cmd += ["--port", str(port)]
    cmd += ["--env-file", os.devnull]  # settings come from the environment built above, never from a file
    log.parent.mkdir(parents=True, exist_ok=True)
    out = log.open("ab")
    proc = subprocess.Popen(cmd, cwd=root, env=agent_env(profile, env_file), stdout=out, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + START_TIMEOUT_S
        while True:
            if proc.poll() is not None:
                raise LaunchError(f"{spec.name}@{profile.name} 进程退出（code {proc.returncode}），日志：{log}")
            try:
                info = fetch_info(url, timeout=1.0)
                break
            except AgentProtocolError:
                if time.monotonic() > deadline:
                    raise LaunchError(f"{spec.name}@{profile.name} 启动超时，日志：{log}") from None
                time.sleep(0.3)
        actual = (info.get("llm") or {}).get("model")
        if actual != profile.model:  # the agent must report the model it was given, or the comparison is void
            raise LaunchError(f"{spec.name} 报告的模型是 {actual}，期望 {profile.model}")
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        out.close()


def run_bench(
    profile: ModelProfile,
    plan: list[PlanItem],
    *,
    targets: dict[str, TargetSpec],
    targets_path: str | Path,
    runs_dir: str | Path,
    env_file: str | Path | None,
    reps: int,
    concurrency: int,
    on_done: Callable[[str, PlanItem, object], None] | None = None,
) -> list[str]:
    """Run every plan item on one model; returns the run ids. An existing run is kept, not repeated."""
    root = Path(targets_path).resolve().parent.parent
    done = []
    for item in plan:
        spec = targets.get(item.target)
        if spec is None:
            raise LaunchError(f"未知目标 {item.target}")
        run_id = bench_run_id(profile.name, item, reps)
        if (Path(runs_dir) / run_id / "summary.json").exists():
            done.append(run_id)
            continue
        log = Path(runs_dir) / "_agent_logs" / f"bench-{profile.name}-{item.target}.log"
        with deployed(spec, profile, root=root, env_file=env_file, log=log) as url:
            request = RunRequest(
                target=item.target,
                version=item.version,
                suite=item.suite,
                mode="live",
                reps=reps,
                concurrency=concurrency,
                transport="http",
                service_url=url,
                purpose=BENCH,
                run_id=run_id,
            )
            prepared = prepare_run(request, targets_path=targets_path, runs_dir=runs_dir, env_file=None)
            summary = prepared.runner.run(prepared.cases)
        done.append(run_id)
        if on_done:
            on_done(run_id, item, summary)
    return done

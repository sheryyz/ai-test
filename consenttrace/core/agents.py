"""Agents under test that run in their own processes: status, onboarding check, local launch.

ConsentTrace never imports an agent. For a locally managed agent it runs the `launch`
command from targets.yaml as a child process and talks to it over the agent protocol,
exactly as it would talk to an agent someone else deployed.
"""

from __future__ import annotations

import atexit
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from consenttrace.adapters.http import AgentProtocolError, fetch_info
from consenttrace.core.registry import TargetSpec

START_TIMEOUT_S = 30.0


@dataclass
class AgentStatus:
    name: str
    url: str | None
    online: bool
    info: dict[str, Any] | None = None
    error: str | None = None
    managed: bool = False  # started by this ConsentTrace process
    launchable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "online": self.online,
            "info": self.info,
            "error": self.error,
            "managed": self.managed,
            "launchable": self.launchable,
        }


class AgentProcesses:
    """Child processes for locally managed agents; stopped when ConsentTrace exits."""

    def __init__(self, root: Path, log_dir: Path | None = None) -> None:
        self.root = root
        self.log_dir = log_dir
        self._procs: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()
        atexit.register(self.stop_all)

    def status(self, spec: TargetSpec, *, timeout: float = 1.5) -> AgentStatus:
        managed = spec.name in self._procs and self._procs[spec.name].poll() is None
        if not spec.service_url:
            return AgentStatus(spec.name, None, False, error="未配置独立进程地址", launchable=False)
        try:
            info = fetch_info(spec.service_url, timeout=timeout)
            return AgentStatus(spec.name, spec.service_url, True, info=info, managed=managed, launchable=bool(spec.launch))
        except AgentProtocolError as exc:
            return AgentStatus(spec.name, spec.service_url, False, error=str(exc), managed=managed, launchable=bool(spec.launch))

    def start(self, spec: TargetSpec) -> AgentStatus:
        """Start the agent's own process if it is not already answering; wait until it does."""
        current = self.status(spec)
        if current.online:
            return current
        if not spec.launch:
            current.error = "该 Agent 不由本机管理（没有 launch 命令），请让它的维护者启动"
            return current
        with self._lock:
            proc = self._procs.get(spec.name)
            if proc is None or proc.poll() is not None:
                cmd = [sys.executable if part == "python" else part for part in spec.launch]
                out = subprocess.DEVNULL
                if self.log_dir is not None:
                    self.log_dir.mkdir(parents=True, exist_ok=True)
                    out = (self.log_dir / f"agent-{spec.name}.log").open("ab")
                self._procs[spec.name] = subprocess.Popen(cmd, cwd=self.root, stdout=out, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + START_TIMEOUT_S
        while time.monotonic() < deadline:
            proc = self._procs[spec.name]
            if proc.poll() is not None:
                return AgentStatus(
                    spec.name, spec.service_url, False, error=f"进程已退出（code {proc.returncode}）", launchable=True
                )
            current = self.status(spec, timeout=1.0)
            if current.online:
                return current
            time.sleep(0.3)
        return self.status(spec)

    def stop_all(self) -> None:
        with self._lock:
            procs, self._procs = list(self._procs.values()), {}
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

"""Web API: read-only views over run evidence, plus starting runs with live SSE progress.

The UI never computes a verdict; it renders what this API reads from the evidence store.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from consenttrace.core.analysis import run_breakdown
from consenttrace.core.evidence import load_results, load_summary, load_trace
from consenttrace.core.launch import LaunchError, RunRequest, prepare_run
from consenttrace.core.loader import LoadError, load_cases, load_contract
from consenttrace.core.registry import TargetSpec, load_targets
from consenttrace.core.runner import CaseJob
from consenttrace.schemas import RunResult, TestCase, TraceEvent

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"


class StartRun(BaseModel):
    target: str
    version: str = "v1"
    suite: str = "smoke"
    mode: Literal["live", "replay"] = "live"
    reps: int | None = Field(default=None, ge=1, le=10)
    concurrency: int = Field(default=4, ge=1, le=16)
    cases: list[str] | None = None
    replay_from: str | None = None
    max_tokens: int | None = None


@dataclass
class LiveRun:
    run_id: str
    total: int
    status: str = "running"  # running | done | error
    done: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def push(self, kind: str, data: Any) -> None:
        with self.lock:
            self.events.append({"seq": len(self.events), "type": kind, "data": data})

    def since(self, seq: int) -> list[dict[str, Any]]:
        with self.lock:
            return self.events[seq:]


def _compact(e: TraceEvent) -> dict[str, Any]:
    content = e.content if e.content is None or len(e.content) <= 240 else e.content[:240] + "…"
    return {
        "step_id": e.step_id,
        "turn_id": e.turn_id,
        "kind": e.kind.value,
        "tool": e.tool,
        "status": e.status.value if e.status else None,
        "injection_id": e.injection_id,
        "content": content,
    }


class RunManager:
    def __init__(self, targets_path: Path, runs_dir: Path, env_file: Path | None) -> None:
        self.targets_path, self.runs_dir, self.env_file = targets_path, runs_dir, env_file
        self.live: dict[str, LiveRun] = {}

    def start(self, body: StartRun) -> LiveRun:
        holder: dict[str, LiveRun] = {}

        def on_result(result: RunResult) -> None:
            live = holder["live"]
            live.done += 1
            live.push("result", result.model_dump(mode="json"))

        def on_event(job: CaseJob, event: TraceEvent) -> None:
            holder["live"].push("trace", {"case_id": job.case.case_id, "rep": job.rep, "event": _compact(event)})

        request = RunRequest(
            target=body.target,
            version=body.version,
            suite=body.suite,
            mode=body.mode,
            reps=body.reps,
            concurrency=body.concurrency,
            cases=body.cases,
            replay_from=body.replay_from,
            max_tokens=body.max_tokens,
        )
        prepared = prepare_run(
            request,
            targets_path=self.targets_path,
            runs_dir=self.runs_dir,
            env_file=self.env_file,
            on_result=on_result,
            on_event=on_event,
        )
        live = LiveRun(prepared.config.run_id, prepared.total)
        holder["live"] = live
        self.live[live.run_id] = live
        live.push(
            "start",
            {
                "run_id": live.run_id,
                "total": live.total,
                "cases": [c.case_id for c in prepared.cases],
                "reps": prepared.config.reps,
            },
        )

        def work() -> None:
            try:
                summary = prepared.runner.run(prepared.cases)
                live.status = "done"
                live.push("done", summary.model_dump(mode="json"))
            except Exception as exc:  # surfaced to the UI instead of dying silently
                live.status = "error"
                live.push("error", {"message": f"{type(exc).__name__}: {exc}"})

        threading.Thread(target=work, name=f"run-{live.run_id}", daemon=True).start()
        return live


def create_app(
    *,
    targets_path: str | Path = "configs/targets.yaml",
    runs_dir: str | Path = "runs",
    env_file: str | Path | None = ".env",
    web_dist: Path | None = WEB_DIST,
) -> FastAPI:
    targets_path, runs_dir = Path(targets_path), Path(runs_dir)
    manager = RunManager(targets_path, runs_dir, Path(env_file) if env_file else None)
    app = FastAPI(title="ConsentTrace", version="0.1.0")
    app.state.manager = manager

    def targets() -> dict[str, TargetSpec]:
        return load_targets(targets_path)

    def target(name: str) -> TargetSpec:
        found = targets().get(name)
        if found is None:
            raise HTTPException(404, f"unknown target {name}")
        return found

    @lru_cache(maxsize=32)
    def _suite(path: str, mtime: float) -> dict[str, TestCase]:
        return {c.case_id: c for c in load_cases(path)}

    def suite_cases(spec: TargetSpec, suite: str) -> dict[str, TestCase]:
        path = spec.suites.get(suite)
        if path is None or not path.exists():
            return {}
        return _suite(str(path), path.stat().st_mtime)

    def run_dir(run_id: str) -> Path:
        path = (runs_dir / run_id).resolve()
        if runs_dir.resolve() not in path.parents or not path.is_dir():
            raise HTTPException(404, f"unknown run {run_id}")
        return path

    def run_cases(path: Path) -> dict[str, TestCase]:
        config = json.loads((path / "config.json").read_text(encoding="utf-8")) if (path / "config.json").exists() else {}
        spec = targets().get(config.get("target", ""))
        return suite_cases(spec, config.get("suite", "")) if spec else {}

    # ------------------------------------------------------------ catalogue

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "web": bool(web_dist and (web_dist / "index.html").exists())}

    @app.get("/api/targets")
    def list_targets() -> list[dict[str, Any]]:
        out = []
        for spec in targets().values():
            try:
                contract = load_contract(spec.contract)
                rules, contract_id = len(contract.rules), contract.contract_id
            except LoadError:
                rules, contract_id = 0, None
            out.append(
                {
                    "name": spec.name,
                    "description": spec.description,
                    "versions": list(spec.versions),
                    "suites": {name: len(suite_cases(spec, name)) for name in spec.suites},
                    "contract_id": contract_id,
                    "rules": rules,
                }
            )
        return out

    @app.get("/api/targets/{name}/contract")
    def get_contract(name: str) -> dict[str, Any]:
        spec = target(name)
        contract = load_contract(spec.contract)
        return {"contract": contract.model_dump(mode="json"), "yaml": spec.contract.read_text(encoding="utf-8")}

    @app.get("/api/targets/{name}/suites/{suite}")
    def get_suite(name: str, suite: str) -> list[dict[str, Any]]:
        return [c.model_dump(mode="json") for c in suite_cases(target(name), suite).values()]

    # ------------------------------------------------------------ runs

    @app.get("/api/runs")
    def list_runs() -> list[dict[str, Any]]:
        out = []
        if runs_dir.exists():
            for path in sorted((p for p in runs_dir.iterdir() if (p / "summary.json").exists()), reverse=True):
                out.append({**load_summary(path).model_dump(mode="json"), "status": "done"})
        for live in manager.live.values():
            if live.status != "done":
                out.insert(0, {"run_id": live.run_id, "status": live.status, "executions": live.total, "done": live.done})
        return out

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        path = run_dir(run_id)
        breakdown = run_breakdown(path, run_cases(path))
        live = manager.live.get(run_id)
        breakdown["status"] = live.status if live else "done"
        breakdown["config"] = (
            json.loads((path / "config.json").read_text(encoding="utf-8")) if (path / "config.json").exists() else {}
        )
        return breakdown

    @app.get("/api/runs/{run_id}/results")
    def get_results(run_id: str) -> list[dict[str, Any]]:
        return [r.model_dump(mode="json") for r in load_results(run_dir(run_id))]

    @app.get("/api/runs/{run_id}/cases/{case_id}/{rep}")
    def get_case(run_id: str, case_id: str, rep: int) -> dict[str, Any]:
        path = run_dir(run_id)
        case_dir = path / "cases" / case_id / f"r{rep}"
        if not (case_dir / "verdict.json").exists():
            raise HTTPException(404, f"no evidence for {case_id} r{rep}")

        def read(name: str) -> Any:
            f = case_dir / name
            return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None

        case = run_cases(path).get(case_id)
        config = read("../../../config.json") or {}
        spec = targets().get(config.get("target", ""))
        contract = load_contract(spec.contract).model_dump(mode="json") if spec else None
        return {
            "run_id": run_id,
            "case": case.model_dump(mode="json") if case else None,
            "verdict": read("verdict.json"),
            "trace": [e.model_dump(mode="json") for e in load_trace(case_dir)],
            "auth": read("auth_timeline.json"),
            "state_before": read("state_before.json"),
            "state_after": read("state_after.json"),
            "state_diff": read("state_diff.json"),
            "contract": contract,
            "reps": sorted(int(p.name[1:]) for p in (path / "cases" / case_id).iterdir() if p.name.startswith("r")),
        }

    @app.post("/api/runs", status_code=202)
    def start_run(body: StartRun) -> dict[str, Any]:
        try:
            live = manager.start(body)
        except (LaunchError, LoadError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"run_id": live.run_id, "total": live.total}

    @app.get("/api/runs/{run_id}/stream")
    async def stream(run_id: str) -> StreamingResponse:
        live = manager.live.get(run_id)
        if live is None:
            raise HTTPException(404, f"run {run_id} is not running in this server")

        async def events() -> AsyncIterator[str]:
            seq = 0
            while True:
                batch = live.since(seq)
                for item in batch:
                    yield f"event: {item['type']}\ndata: {json.dumps(item['data'], ensure_ascii=False, default=str)}\n\n"
                seq += len(batch)
                if live.status != "running" and not live.since(seq):
                    return
                await asyncio.sleep(0.15)

        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.get("/api/settings")
    def settings() -> dict[str, Any]:
        from consenttrace.config import LLMSettings

        found = LLMSettings.from_env(env_file) if env_file else None
        return {"live_available": found is not None, "model": found.model if found else None}

    @app.exception_handler(LoadError)
    async def load_error(_request: Any, exc: LoadError) -> JSONResponse:
        return JSONResponse({"detail": str(exc), "problems": exc.problems}, status_code=400)

    # ------------------------------------------------------------ the single-page app

    if web_dist is not None and (web_dist / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            candidate = (web_dist / path).resolve()
            if path and web_dist.resolve() in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(web_dist / "index.html")

    return app


def dump_openapi(path: Path) -> None:  # pragma: no cover - developer convenience
    path.write_text(yaml.safe_dump(create_app(web_dist=None).openapi(), allow_unicode=True), encoding="utf-8")

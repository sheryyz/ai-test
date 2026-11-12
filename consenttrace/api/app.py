"""Web API: read-only views over run evidence, plus starting runs with live SSE progress.

The UI never computes a verdict; it renders what this API reads from the evidence store.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from consenttrace.adapters.http import AgentProtocolError, HttpAgentAdapter
from consenttrace.adapters.probe import probe_agent
from consenttrace.core.agents import AgentProcesses
from consenttrace.core.analysis import run_breakdown
from consenttrace.core.defects import collect_defects, defect_summary, replay_sources, runs_in_force
from consenttrace.core.evidence import load_results, load_summary, load_trace
from consenttrace.core.experiments import experiment_summary
from consenttrace.core.launch import LaunchError, RunRequest, prepare_run
from consenttrace.core.loader import LoadError, load_cases, load_contract
from consenttrace.core.registry import TargetSpec, load_targets
from consenttrace.core.runner import CaseJob
from consenttrace.schemas import RunResult, TestCase, TraceEvent

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"


class ContractText(BaseModel):
    yaml: str
    draft_run: str | None = None  # the draft set this edit started from, for counting human edits
    draft: int | None = None


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
    transport: Literal["inprocess", "http"] = "inprocess"
    retest_of: dict[str, Any] | None = None


class RetestRequest(BaseModel):
    id: str  # defect id: target:version:case_id
    mode: Literal["live", "replay"] = "replay"
    transport: Literal["inprocess", "http"] = "http"
    reps: int | None = Field(default=None, ge=1, le=10)
    replay_from: str | None = None


class ProbeRequest(BaseModel):
    url: str | None = None
    target: str | None = None
    version: str | None = None


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
            transport=body.transport,
            retest_of=body.retest_of,
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
    agent_processes: AgentProcesses | None = None,
) -> FastAPI:
    targets_path, runs_dir = Path(targets_path), Path(runs_dir)
    manager = RunManager(targets_path, runs_dir, Path(env_file) if env_file else None)
    procs = agent_processes or AgentProcesses(targets_path.resolve().parent.parent, log_dir=runs_dir / "_agent_logs")
    app = FastAPI(title="ConsentTrace", version="0.1.0")
    app.state.manager = manager
    app.state.agents = procs

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
        cases = _suite(str(path), path.stat().st_mtime)
        try:
            return {c: cases[c] for c in spec.select(suite, list(cases))}
        except ValueError:
            return {}

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
                    "subsets": sorted(spec.subsets),
                    "contract_id": contract_id,
                    "rules": rules,
                    "service_url": spec.service_url,
                    "in_process": bool(spec.adapter),
                    "origin": spec.origin,
                    "fixed_versions": spec.fixed_versions,
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

    # ------------------------------------------------------------ contract workbench (F09)

    def drafts_dir() -> Path:
        return runs_dir / "contract_drafts"

    def latest_draft_run(name: str) -> Path | None:
        found = [
            p.parent
            for p in drafts_dir().glob("*/evaluation.json")
            if json.loads(p.read_text(encoding="utf-8")).get("target") == name
        ]
        return max(found, key=lambda p: (p / "evaluation.json").stat().st_mtime) if found else None

    def parse_contract(text: str) -> tuple[Any, list[str]]:
        from consenttrace.schemas import TestContract

        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            return None, [f"YAML 无法解析：{exc}"]
        try:
            return TestContract.model_validate(data), []
        except Exception as exc:  # pydantic ValidationError, or a non-mapping document
            errors = getattr(exc, "errors", None)
            if callable(errors):
                return None, [f"{'.'.join(map(str, e['loc'])) or '(root)'}：{e['msg']}" for e in errors()]
            return None, [str(exc)]

    def draft_contract_of(name: str, draft_run: str | None, draft: int | None) -> Any:
        if not draft_run or not draft:
            return None
        path = (drafts_dir() / draft_run / f"draft-{draft}.yaml").resolve()
        if drafts_dir().resolve() not in path.parents or not path.exists():
            return None
        return load_contract(path)

    @app.get("/api/targets/{name}/describe")
    def describe_target(name: str) -> dict[str, Any]:
        from consenttrace.adapters.base import DescribableAdapter

        spec = target(name)
        if not spec.adapter:
            assert spec.service_url is not None
            try:
                return HttpAgentAdapter(spec.service_url, version=spec.versions[0]).describe().model_dump(mode="json")
            except AgentProtocolError as exc:
                raise HTTPException(502, str(exc)) from exc
        adapter = spec.adapter_class()(lambda: None)
        if not isinstance(adapter, DescribableAdapter):
            raise HTTPException(404, f"{name} 的适配器不支持 describe()")
        return adapter.describe().model_dump(mode="json")

    @app.get("/api/targets/{name}/drafts")
    def get_drafts(name: str) -> dict[str, Any]:
        target(name)
        folder = latest_draft_run(name)
        if folder is None:
            return {"run_id": None, "drafts": []}
        ev = json.loads((folder / "evaluation.json").read_text(encoding="utf-8"))
        drafts = []
        for row in ev["drafts"]:
            path = folder / f"draft-{row['draft']}.yaml"
            accepted = folder / f"accepted-{row['draft']}.json"
            drafts.append(
                {
                    **{k: row.get(k) for k in ("draft", "valid", "attempts", "errors", "rationale", "structure", "verdicts")},
                    "yaml": path.read_text(encoding="utf-8") if path.exists() else None,
                    "accepted": json.loads(accepted.read_text(encoding="utf-8")) if accepted.exists() else None,
                }
            )
        return {"run_id": folder.name, "model": ev.get("model"), "prompt_version": ev.get("prompt_version"), "drafts": drafts}

    @app.post("/api/targets/{name}/contract/check")
    def check_contract(name: str, body: ContractText) -> dict[str, Any]:
        from consenttrace.ai.contract_drafter import score_structure

        spec = target(name)
        contract, errors = parse_contract(body.yaml)
        if contract is None:
            return {"ok": False, "errors": errors}
        draft = draft_contract_of(name, body.draft_run, body.draft)
        return {
            "ok": True,
            "errors": [],
            "vs_gold": score_structure(contract, load_contract(spec.contract)),
            # edits a person made: the draft is the start, the edited contract is where they ended up
            "edits_from_draft": score_structure(draft, contract)["edits_to_gold"] if draft is not None else None,
        }

    @app.post("/api/targets/{name}/contract/accept")
    def accept_contract(name: str, body: ContractText) -> dict[str, Any]:
        result = check_contract(name, body)
        if not result["ok"]:
            raise HTTPException(422, "；".join(result["errors"]))
        if not body.draft_run or not body.draft or draft_contract_of(name, body.draft_run, body.draft) is None:
            raise HTTPException(400, "需要指明从哪一份草稿开始编辑")
        folder = drafts_dir() / body.draft_run
        (folder / f"accepted-{body.draft}.yaml").write_text(body.yaml, encoding="utf-8")
        record = {
            "draft": body.draft,
            "edits_from_draft": result["edits_from_draft"],
            "vs_gold": {k: result["vs_gold"][k] for k in ("sensitive_actions", "args_mapping", "rules", "edits_to_gold")},
            "accepted_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        (folder / f"accepted-{body.draft}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return record

    # ------------------------------------------------------------ agents under test (F01)

    @app.get("/api/agents")
    def list_agents() -> list[dict[str, Any]]:
        return [procs.status(spec).to_dict() for spec in targets().values()]

    @app.post("/api/agents/{name}/start")
    def start_agent(name: str) -> dict[str, Any]:
        return procs.start(target(name)).to_dict()

    @app.post("/api/agents/probe")
    def probe(body: ProbeRequest) -> dict[str, Any]:
        url = body.url or (target(body.target).service_url if body.target else None)
        if not url:
            raise HTTPException(400, "需要 url，或一个配置了 service.url 的 target")
        return probe_agent(url, version=body.version).to_dict()

    # ------------------------------------------------------------ defects, re-tests and the workspace

    @app.get("/api/defects")
    def defects() -> dict[str, Any]:
        found = collect_defects(runs_dir, targets(), suite_cases)
        return {"summary": defect_summary(found), "defects": found}

    @app.get("/api/targets/{name}/replay-sources")
    def get_replay_sources(name: str, version: str, suite: str | None = None, case: str | None = None) -> list[dict[str, Any]]:
        spec = target(name)
        if case:
            ids = [case]
        elif suite:
            ids = list(suite_cases(spec, suite))
        else:
            raise HTTPException(400, "需要 suite 或 case")
        return replay_sources(runs_dir, name, version, ids)

    @app.post("/api/defects/retest", status_code=202)
    def retest(body: RetestRequest) -> dict[str, Any]:
        found = next((d for d in collect_defects(runs_dir, targets(), suite_cases) if d["id"] == body.id), None)
        if found is None:
            raise HTTPException(404, f"没有这个缺陷：{body.id}")
        spec = target(found["target"])
        fixed = found["fixed_version"]
        if not fixed:
            raise HTTPException(400, f"{spec.name} {found['version']} 没有登记修复版本（targets.yaml fixed_versions）")
        suite = next((s for s in [found["first"]["suite"], *spec.suites] if found["case_id"] in suite_cases(spec, s)), None)
        if suite is None:
            raise HTTPException(400, f"没有包含 {found['case_id']} 的用例集")
        replay_from = body.replay_from
        if body.mode == "replay" and not replay_from:
            sources = replay_sources(runs_dir, spec.name, fixed, [found["case_id"]])
            if not sources:
                raise HTTPException(400, f"修复版 {fixed} 还没有这条用例的录制，只能 Live 复测")
            replay_from = sources[0]["run_id"]
        request = StartRun(
            target=spec.name,
            version=fixed,
            suite=suite,
            mode=body.mode,
            reps=body.reps if body.mode == "live" else None,
            concurrency=3,
            cases=[found["case_id"]],
            replay_from=replay_from,
            transport=body.transport,
            retest_of={"defect": found["id"], "run_id": found["first"]["run_id"], "rep": found["first"]["rep"]},
        )
        try:
            live = manager.start(request)
        except (LaunchError, LoadError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"run_id": live.run_id, "total": live.total, "version": fixed, "replay_from": replay_from}

    @app.get("/api/workspace")
    def workspace() -> dict[str, Any]:
        specs = targets()
        found = collect_defects(runs_dir, specs, suite_cases)
        refs = runs_in_force(runs_dir)
        statuses = {spec.name: procs.status(spec).to_dict() for spec in specs.values()}
        last_run = {}
        for ref in refs:
            last_run[ref.summary.target] = {
                "run_id": ref.run_id,
                "version": ref.summary.agent_version,
                "suite": ref.summary.suite,
                "mode": ref.summary.mode,
                "counts": ref.summary.counts,
                "executions": ref.summary.executions,
                "finished_at": ref.summary.finished_at.isoformat(),
            }
        acceptance_runs = [r for r in refs if r.summary.suite == "acceptance"]
        writes = [d for d in found if d["kind"] == "side_effect"]
        verified = [d for d in writes if d["status"] == "fixed_verified"]
        tested_targets = sorted({r.summary.target for r in refs})
        steps = [
            {
                "key": "connect",
                "title": "接入独立进程中的被测 Agent",
                "done": any(st["online"] for st in statuses.values()),
                "detail": "、".join(f"{n}（{st['url']}）" for n, st in statuses.items() if st["online"]) or "尚无在线 Agent",
                "href": "#/agents",
            },
            {
                "key": "batch",
                "title": "批量执行验收套件（多轮授权变更 + 工具注入 + RAG 投毒）",
                "done": bool(acceptance_runs),
                "detail": acceptance_runs[-1].run_id if acceptance_runs else "还没有验收套件的运行",
                "href": f"#/runs/{acceptance_runs[-1].run_id}" if acceptance_runs else "#/console",
            },
            {
                "key": "locate",
                "title": "从轨迹与数据库实际写入中自动定位缺陷",
                "done": bool(writes),
                "detail": f"{len(writes)} 个越权写入缺陷" if writes else "尚未发现越权写入",
                "href": f"#/defects/{writes[0]['id']}" if writes else "#/defects",
            },
            {
                "key": "retest",
                "title": "修复后同一用例复测通过",
                "done": bool(verified),
                "detail": f"{len(verified)} 个已验证修复" if verified else "尚未复测",
                "href": f"#/defects/{verified[0]['id']}" if verified else "#/defects",
            },
            {
                "key": "reuse",
                "title": "第二个不同业务的 Agent 复用同一测试内核",
                "done": len(tested_targets) >= 2,
                "detail": "、".join(tested_targets) or "—",
                "href": "#/agents",
            },
        ]
        return {
            "agents": [
                {
                    **statuses[spec.name],
                    "description": spec.description,
                    "origin": spec.origin,
                    "versions": list(spec.versions),
                    "suites": {name: len(suite_cases(spec, name)) for name in spec.suites},
                    "fixed_versions": spec.fixed_versions,
                    "in_process": bool(spec.adapter),
                    "last_run": last_run.get(spec.name),
                }
                for spec in specs.values()
            ],
            "defects": {
                "summary": defect_summary(found),
                # authorization defects first, then the most recently seen
                "recent": sorted(found, key=lambda d: (d["kind"] == "task", -_ts(d["last_seen"])))[:6],
            },
            "recent_runs": [
                {
                    "run_id": r.run_id,
                    "target": r.summary.target,
                    "version": r.summary.agent_version,
                    "suite": r.summary.suite,
                    "mode": r.summary.mode,
                    "transport": r.transport,
                    "counts": r.summary.counts,
                    "executions": r.summary.executions,
                    "finished_at": r.summary.finished_at.isoformat(),
                    "retest_of": r.retest_of,
                }
                for r in reversed(refs[-8:])
            ],
            "acceptance": steps,
        }

    # ------------------------------------------------------------ adversarial generation (F10, injections)

    @app.get("/api/attacks/{name}")
    def attacks(name: str) -> dict[str, Any]:
        from consenttrace.ai.attack_generator import AttackSpec, read_library
        from consenttrace.core.attacks import attack_report

        spec = target(name)
        root = targets_path.resolve().parent.parent
        spec_path = root / "configs" / f"{name}_attacks.yaml"
        library = root / "benchmarks" / f"{name}_injection_library.jsonl"
        if not spec_path.exists() or not library.exists():
            raise HTTPException(404, f"{name} 还没有对抗用例（consenttrace attacks generate --target {name}）")
        attack_spec = AttackSpec.load(spec_path)
        header, entries = read_library(library)
        report_path = library.with_suffix(".report.json")
        gen = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else None
        cases = suite_cases(spec, "attacks")
        latest: dict[str, Any] = {}
        for ref in runs_in_force(runs_dir):
            s = ref.summary
            if s.target == name and s.suite == "attacks" and s.mode == "live":
                latest[s.agent_version] = ref
        reports = [attack_report(latest[v].path, cases) for v in spec.versions if v in latest]
        return {
            "spec": {
                "spec_id": attack_spec.spec_id,
                "styles": {
                    k: {"name": v.name, "description": v.description, "placement": v.placement.model_dump(mode="json")}
                    for k, v in attack_spec.styles.items()
                },
                "goals": {k: {"name": v.name, "action": v.action} for k, v in attack_spec.goals.items()},
                "combos": [c.model_dump() for c in attack_spec.combos],
            },
            "library": {"header": header, "entries": entries},
            "generation": None
            if gen is None
            else {
                "accepted": gen["accepted"],
                "rejected": gen["rejected"],
                "model": gen["model"],
                "tokens": sum(c["prompt_tokens"] + c["completion_tokens"] for c in gen["combos"]),
                "rejections": [{**r, "style": c["style"], "goal": c["goal"]} for c in gen["combos"] for r in c["rejected"]],
            },
            "runs": reports,
        }

    @app.get("/api/analysis")
    def analysis() -> dict[str, Any]:
        return experiment_summary(runs_dir, targets(), suite_cases)

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
            "target": config.get("target"),
            "transport": config.get("transport") or "inprocess",
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


def _ts(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()


def dump_openapi(path: Path) -> None:  # pragma: no cover - developer convenience
    path.write_text(yaml.safe_dump(create_app(web_dist=None).openapi(), allow_unicode=True), encoding="utf-8")

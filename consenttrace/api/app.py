"""Web API: read-only views over run evidence, plus starting runs with live SSE progress.

The UI never computes a verdict; it renders what this API reads from the evidence store.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from consenttrace.adapters.http import AgentProtocolError, HttpAgentAdapter
from consenttrace.adapters.probe import probe_agent
from consenttrace.core.agents import AgentProcesses
from consenttrace.core.analysis import run_breakdown
from consenttrace.core.auth import SESSION_TTL, Sessions, UserStore
from consenttrace.core.defects import collect_defects, defect_summary, replay_sources, runs_in_force
from consenttrace.core.evidence import load_results, load_summary, load_trace
from consenttrace.core.experiments import experiment_summary
from consenttrace.core.launch import LaunchError, RunRequest, prepare_run
from consenttrace.core.loader import LoadError, load_cases, load_contract
from consenttrace.core.registry import TargetSpec, load_targets, read_registered, registered_agents_path, write_registered
from consenttrace.core.runner import CaseJob
from consenttrace.schemas import RunResult, TestCase, TraceEvent

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
SESSION_COOKIE = "ct_session"
AGENT_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,31}$")


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


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterAgent(BaseModel):
    name: str
    url: str
    like: str  # the built-in target whose business (contract and suites) this agent shares
    description: str = ""


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
    labels_dir: Path | None = None,
    users: UserStore | None = None,
) -> FastAPI:
    """`users=None` serves without sign-in (tests, local scripts); `consenttrace serve` passes the accounts."""
    targets_path, runs_dir = Path(targets_path), Path(runs_dir)
    manager = RunManager(targets_path, runs_dir, Path(env_file) if env_file else None)
    procs = agent_processes or AgentProcesses(targets_path.resolve().parent.parent, log_dir=runs_dir / "_agent_logs")
    app = FastAPI(title="ConsentTrace", version="0.1.0")
    app.state.manager = manager
    app.state.agents = procs
    sessions = Sessions()
    registered_path = registered_agents_path(runs_dir)

    def targets() -> dict[str, TargetSpec]:
        return load_targets(targets_path, registered=registered_path)

    def current_user(request: Request) -> str | None:
        return sessions.get(request.cookies.get(SESSION_COOKIE)) if users is not None else None

    # ------------------------------------------------------------ sign-in

    if users is not None:

        @app.middleware("http")
        async def require_login(request: Request, call_next: Any) -> Any:
            path = request.url.path
            public = path.startswith("/api/auth/") or path == "/api/health" or not path.startswith("/api/")
            if not public and current_user(request) is None:
                return JSONResponse({"detail": "请先登录"}, status_code=401)
            return await call_next(request)

    @app.get("/api/auth/me")
    def auth_me(request: Request) -> dict[str, Any]:
        if users is None:
            return {"enabled": False, "user": None, "demo": None}
        name = current_user(request)
        user = users.users().get(name) if name else None
        return {"enabled": True, "user": user.public() if user else None, "demo": users.demo_login()}

    @app.post("/api/auth/login")
    def auth_login(body: LoginRequest, response: Response) -> dict[str, Any]:
        if users is None:
            raise HTTPException(404, "本服务未启用登录")
        user = users.authenticate(body.username, body.password)
        if user is None:
            time.sleep(0.3)  # slows down guessing; the hash check already takes the same time for every name
            raise HTTPException(401, "用户名或密码错误")
        token = sessions.create(user.username)
        response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", max_age=int(SESSION_TTL), path="/")
        return {"user": user.public()}

    @app.post("/api/auth/logout")
    def auth_logout(request: Request, response: Response) -> dict[str, Any]:
        sessions.drop(request.cookies.get(SESSION_COOKIE))
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"ok": True}

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
                    "like": spec.like,
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
        report = probe_agent(url, version=body.version).to_dict()
        report["describe"], report["registered"], report["businesses"] = None, None, []
        info = report.get("info")
        if not info:
            return report
        try:  # what the agent says about itself: tools, prompt, state tables
            version = body.version or info["versions"][0]
            report["describe"] = HttpAgentAdapter(url, version=version).describe().model_dump(mode="json")
        except AgentProtocolError:
            pass  # optional endpoint; the probe already reports it as SKIP
        report["businesses"] = businesses_for(report["describe"])
        spec = next((t for t in targets().values() if t.service_url and _same_endpoint(t.service_url, url)), None)
        if spec is not None:
            contract = load_contract(spec.contract)
            report["registered"] = {
                "name": spec.name,
                "origin": spec.origin,
                "versions": list(spec.versions),
                "contract_id": contract.contract_id,
                "rules": len(contract.rules),
                "actions": [{"action": a.action, "tool": a.tool} for a in contract.sensitive_actions],
                "suites": {name: len(suite_cases(spec, name)) for name in spec.suites},
                "fixed_versions": spec.fixed_versions,
            }
        return report

    def businesses_for(describe: dict[str, Any] | None) -> list[dict[str, Any]]:
        """Built-in targets whose contract this agent could be tested with: it has every sensitive tool."""
        tools = _tool_names(describe) if describe else None
        out = []
        for spec in targets().values():
            if spec.registered:
                continue
            contract = load_contract(spec.contract)
            needed = sorted({a.tool for a in contract.sensitive_actions})
            missing = [t for t in needed if tools is not None and t not in tools]
            out.append(
                {
                    "name": spec.name,
                    "description": spec.description,
                    "contract_id": contract.contract_id,
                    "rules": len(contract.rules),
                    "sensitive_tools": needed,
                    "missing": missing,
                    "checked": tools is not None,
                    "compatible": tools is not None and not missing,
                    "suites": {name: len(suite_cases(spec, name)) for name in spec.suites},
                }
            )
        return out

    @app.post("/api/agents/register", status_code=201)
    def register_agent(body: RegisterAgent, request: Request) -> dict[str, Any]:
        specs = targets()
        if not AGENT_NAME.match(body.name):
            raise HTTPException(422, "名称只能用小写字母、数字和连字符，2–32 个字符，以字母或数字开头")
        if body.name in specs:
            raise HTTPException(409, f"名称 {body.name} 已被占用")
        base = specs.get(body.like)
        if base is None or base.registered:
            raise HTTPException(400, f"没有这种业务：{body.like}")
        taken = next((t.name for t in specs.values() if t.service_url and _same_endpoint(t.service_url, body.url)), None)
        if taken:
            raise HTTPException(409, f"这个地址已经接入为 {taken}")
        report = probe_agent(body.url)
        if not report.ok or not report.info:
            failed = [f"{c.title}：{c.detail}" for c in report.checks if c.status == "FAIL"] or ["Agent 没有响应"]
            raise HTTPException(400, "接入检查未通过，不能保存。" + "；".join(failed))
        versions = [str(v) for v in report.info.get("versions") or []] or ["v1"]
        try:
            describe = HttpAgentAdapter(body.url, version=versions[0]).describe().model_dump(mode="json")
        except AgentProtocolError:
            describe = None
        business = next(b for b in businesses_for(describe) if b["name"] == base.name)
        if business["missing"]:
            raise HTTPException(400, f"这个 Agent 没有 {base.name} 契约要求的敏感工具：{'、'.join(business['missing'])}")
        now = datetime.now(UTC).astimezone()
        who = current_user(request)
        entries = read_registered(registered_path)
        entries[body.name] = {
            "like": base.name,
            "description": body.description.strip() or f"{base.name} 同类业务的 Agent（{body.url}）",
            "origin": f"用户接入（{who + '，' if who else ''}{now:%Y-%m-%d %H:%M}）；契约与用例沿用 {base.name}"
            + ("" if describe else "；Agent 未提供工具定义，敏感工具未核对"),
            "service": {"url": body.url.strip().rstrip("/")},
            "versions": versions,
            "registered_at": now.isoformat(timespec="seconds"),
        }
        write_registered(registered_path, entries)
        return {"name": body.name, "versions": versions, "like": base.name, "tools_checked": describe is not None}

    @app.delete("/api/agents/{name}")
    def unregister_agent(name: str) -> dict[str, Any]:
        spec = target(name)
        if not spec.registered:
            raise HTTPException(400, "内置的被测 Agent 在 configs/targets.yaml 中维护，不能在界面里删除")
        entries = read_registered(registered_path)
        entries.pop(name, None)
        write_registered(registered_path, entries)
        return {"ok": True}

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
                    "like": spec.like,
                    "registered_at": spec.registered_at,
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
        round2 = library.with_name(library.stem + ".r2.jsonl")
        r2_header, r2_entries = read_library(round2) if round2.exists() else ({}, [])
        report_path = library.with_suffix(".report.json")
        gen = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else None
        suites = [s for s in ("attacks", "attacks-r2") if s in spec.suites]
        latest: dict[tuple[str, str], Any] = {}
        for ref in runs_in_force(runs_dir):
            s = ref.summary
            if s.target == name and s.suite in suites and s.mode == "live":
                latest[(s.suite, s.agent_version)] = ref
        reports = [
            {
                **attack_report(latest[(suite, v)].path, suite_cases(spec, suite)),
                "suite": suite,
                "round": 2 if suite == "attacks-r2" else 1,
            }
            for suite in suites
            for v in spec.versions
            if (suite, v) in latest
        ]
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
            "library": {
                "header": header,
                "entries": [{**e, "round": 1} for e in entries] + r2_entries,
                "round2": r2_header or None,
            },
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

    # ------------------------------------------------------------ RAG knowledge-base health check

    @app.get("/api/kb/{name}")
    def kb_report(name: str) -> dict[str, Any]:
        from consenttrace.core.kb import latest_kb_report

        target(name)
        found = latest_kb_report(runs_dir, name)
        if found is None:
            raise HTTPException(404, f"{name} 还没有知识库体检报告（consenttrace kb-check --target {name}）")
        return found

    # ------------------------------------------------------------ blind human annotation (PRD §10.5)

    labels_dir = labels_dir or targets_path.resolve().parent.parent / "benchmarks" / "labels"

    @app.get("/api/annotation")
    def annotation_items() -> dict[str, Any]:
        from consenttrace.core.annotation import LABELS, SAMPLE, latest_labels, read_jsonl

        header, items = read_jsonl(labels_dir / SAMPLE)
        if not items:
            raise HTTPException(404, "还没有标注样本（consenttrace annotate sample）")
        labels = latest_labels(read_jsonl(labels_dir / LABELS)[1])
        done: dict[str, list[str]] = {}
        for bid, who in labels:
            done.setdefault(bid, []).append(who)
        # strata stay hidden: an annotator must not know why an item was drawn
        return {
            "n": len(items),
            "seed": header.get("seed"),
            "items": [{"blind_id": i["blind_id"], "labeled_by": sorted(done.get(i["blind_id"], []))} for i in items],
            "annotators": sorted({who for _, who in labels}),
        }

    @app.get("/api/annotation/score")
    def annotation_score(annotator: str | None = None) -> dict[str, Any]:
        from consenttrace.core.annotation import score

        return score(runs_dir, targets(), suite_cases, labels_dir, annotator=annotator)

    @app.get("/api/annotation/{blind_id}")
    def annotation_item(blind_id: str, annotator: str | None = None) -> dict[str, Any]:
        from consenttrace.core.annotation import LABELS, SAMPLE, blind_view, latest_labels, read_jsonl

        item = next((i for i in read_jsonl(labels_dir / SAMPLE)[1] if i["blind_id"] == blind_id), None)
        if item is None:
            raise HTTPException(404, f"没有样本 {blind_id}")
        mine = latest_labels(read_jsonl(labels_dir / LABELS)[1]).get((blind_id, annotator or ""))
        return {**blind_view(runs_dir, item), "label": mine}

    @app.post("/api/annotation/{blind_id}")
    def annotate(blind_id: str, body: dict[str, Any]) -> dict[str, Any]:
        from consenttrace.core.annotation import SAMPLE, Label, append_label, read_jsonl

        if not any(i["blind_id"] == blind_id for i in read_jsonl(labels_dir / SAMPLE)[1]):
            raise HTTPException(404, f"没有样本 {blind_id}")
        try:
            label = Label.model_validate({**body, "blind_id": blind_id})
        except Exception as exc:
            raise HTTPException(422, str(exc)) from exc
        return append_label(labels_dir, label)

    @app.get("/api/synced-attacks")
    def synced_attacks() -> list[dict[str, Any]]:
        """Consent-synchronised injection: per run, the synced arm against the early arm (same texts)."""
        out = []
        for ref in runs_in_force(runs_dir, include_bench=True):
            s = ref.summary
            if s.suite != "synced-attacks" or s.mode != "live":
                continue
            arms: dict[str, dict[str, int]] = {}
            for r in load_results(ref.path):
                arm = r.case_id.rsplit("-", 1)[1]
                if arm not in ("synced", "early", "none"):
                    continue
                a = arms.setdefault(arm, {"executions": 0, "reached": 0, "violations": 0, "writes": 0})
                a["executions"] += 1
                # the baseline arm has nothing to reach: every execution counts
                if arm == "none" or r.metrics.get("injections_reached"):
                    a["reached"] += 1
                    kinds = {f.kind.value for f in r.findings}
                    a["violations"] += bool(kinds & {"attempt_violation", "side_effect_violation"})
                    a["writes"] += "side_effect_violation" in kinds
            out.append({"run_id": ref.run_id, "target": s.target, "version": s.agent_version, "model": s.model_id, "arms": arms})
        return out

    @app.get("/api/generated")
    def generated() -> list[dict[str, Any]]:
        """Every AI-generated suite: who generated it, what was accepted or rejected, what review changed."""
        root = targets_path.resolve().parent.parent
        out = []
        for spec in targets().values():
            if spec.registered:
                continue
            for suite, path in spec.suites.items():
                if suite in spec.subsets or not path.exists() or path.suffix != ".jsonl":
                    continue
                first = path.read_text(encoding="utf-8").split("\n", 1)[0]
                header = json.loads(first[3:]) if first.startswith("// ") else {}
                library = header.get("library")
                gen: dict[str, Any] = {}
                lib_path = root / library if library else None
                if lib_path and lib_path.with_suffix(".report.json").exists():
                    rep = json.loads(lib_path.with_suffix(".report.json").read_text(encoding="utf-8"))
                    gen = {"model": rep.get("model"), "accepted": rep.get("accepted"), "rejected": rep.get("rejected")}
                elif path.with_suffix(".generation.json").exists():
                    rep = json.loads(path.with_suffix(".generation.json").read_text(encoding="utf-8"))
                    gen = {"model": rep.get("generator_model"), "rounds": rep.get("rounds"), "valid": rep.get("valid")}
                elif path.with_name(path.stem + ".report.json").exists():
                    rep = json.loads(path.with_name(path.stem + ".report.json").read_text(encoding="utf-8"))
                    gen = {"model": rep.get("model")}
                if not gen and not header.get("generator_model") and not header.get("spec_id"):
                    continue
                cases = list(suite_cases(spec, suite).values())
                out.append(
                    {
                        "target": spec.name,
                        "suite": suite,
                        "file": str(path.relative_to(root)),
                        "cases": len(cases),
                        "spec_id": header.get("spec_id"),
                        "model": gen.get("model") or header.get("generator_model") or header.get("model"),
                        "accepted": gen.get("accepted"),
                        "rejected": gen.get("rejected"),
                        "rounds": gen.get("rounds") or header.get("rounds"),
                        "review": header.get("review"),
                        "review_sheet": str(path.with_suffix(".review.md").relative_to(root))
                        if path.with_suffix(".review.md").exists()
                        else None,
                        "created_at": header.get("created_at"),
                        "samples": [
                            {"case_id": c.case_id, "title": c.title, "text": c.turns[0].text, "tags": c.tags} for c in cases[:60]
                        ],
                    }
                )
        return out

    @app.get("/api/coverage")
    def coverage() -> dict[str, Any]:
        from consenttrace.core.coverage import build

        root = targets_path.resolve().parent.parent
        return build(root / "configs" / "coverage_matrix.yaml", targets(), runs_dir, root)

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

    def run_reasoning(path: Path) -> dict[str, Any]:
        from consenttrace.core.reasoning import diagnose, summarize

        diags = []
        for r in load_results(path):
            if r.outcome.value == "FAIL":
                diags += [
                    {**d, "case_id": r.case_id, "rep": r.rep}
                    for d in diagnose(r, load_trace(path / "cases" / r.case_id / f"r{r.rep}"))
                ]
        return {**summarize(diags), "items": diags}

    @app.get("/api/runs/{run_id}/reasoning")
    def get_run_reasoning(run_id: str) -> dict[str, Any]:
        from consenttrace.core.reasoning import legend

        return {**run_reasoning(run_dir(run_id)), "legend": legend()}

    @app.get("/api/runs/{run_id}/scorecard")
    def run_scorecard(run_id: str) -> dict[str, Any]:
        from consenttrace.core.scorecard import method, scorecard

        path = run_dir(run_id)
        return {**scorecard(load_results(path), run_cases(path)), "method": method()}

    @app.get("/api/scorecards")
    def scorecards() -> dict[str, Any]:
        """Every live run's scorecard, grouped by agent × version × suite × model (model-bench runs included)."""
        from consenttrace.core.bench import load_models
        from consenttrace.core.defects import BENCH
        from consenttrace.core.scorecard import method, scorecard

        root = targets_path.resolve().parent.parent
        profiles = load_models(root / "configs" / "models.yaml") if (root / "configs" / "models.yaml").exists() else {}
        by_model = {p.model: p for p in profiles.values()}
        specs = targets()
        groups = []
        for ref in runs_in_force(runs_dir, include_bench=True):
            s = ref.summary
            if s.mode != "live" or s.target not in specs:
                continue
            profile = by_model.get(s.model_id or "")
            groups.append(
                {
                    "run_id": ref.run_id,
                    "target": s.target,
                    "version": s.agent_version,
                    "suite": s.suite,
                    "reps": s.reps,
                    "model": s.model_id,
                    "provider": profile.provider if profile else None,
                    "bench": ref.purpose == BENCH,
                    "finished_at": s.finished_at.isoformat(),
                    **scorecard(load_results(ref.path), suite_cases(specs[s.target], s.suite)),
                    "reasoning": {k: v for k, v in run_reasoning(ref.path).items() if k != "items"},
                }
            )
        from consenttrace.core.reasoning import legend

        return {
            "groups": groups,
            "models": [{"name": p.name, "provider": p.provider, "model": p.model} for p in profiles.values()],
            "method": method(),
            "reasoning_legend": legend(),
        }

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

        from consenttrace.core.reasoning import diagnose

        case = run_cases(path).get(case_id)
        config = read("../../../config.json") or {}
        trace = load_trace(case_dir)
        verdict = read("verdict.json")
        spec = targets().get(config.get("target", ""))
        contract = load_contract(spec.contract).model_dump(mode="json") if spec else None
        return {
            "run_id": run_id,
            "target": config.get("target"),
            "transport": config.get("transport") or "inprocess",
            "case": case.model_dump(mode="json") if case else None,
            "verdict": verdict,
            "trace": [e.model_dump(mode="json") for e in trace],
            "reasoning": diagnose(RunResult.model_validate(verdict), trace) if verdict else [],
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


def _same_endpoint(a: str, b: str) -> bool:
    def norm(u: str) -> str:
        return u.strip().rstrip("/").replace("://localhost", "://127.0.0.1")

    return norm(a) == norm(b)


def _tool_names(describe: dict[str, Any]) -> set[str]:
    names = set()
    for tool in describe.get("tools") or []:
        fn = tool.get("function", tool) if isinstance(tool, dict) else {}
        if isinstance(fn, dict) and fn.get("name"):
            names.add(str(fn["name"]))
    return names


def _ts(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()


def dump_openapi(path: Path) -> None:  # pragma: no cover - developer convenience
    path.write_text(yaml.safe_dump(create_app(web_dist=None).openapi(), allow_unicode=True), encoding="utf-8")

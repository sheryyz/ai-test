"""Serve an instrumented agent over the ConsentTrace Agent Protocol (HTTP + JSON).

An agent team wraps its agent once, with the SDK's Toolbox / TraceRecorder / snapshot
helpers, and runs it as its own process:

    serve_agent(name="travel", versions=["v1"], factory=lambda clients, version: MyAdapter(clients, version=version))

ConsentTrace then drives it from outside, knowing only its URL. Every session gets its
own working directory and sandbox, so concurrent cases never share state. The agent
uses its own model key (read from its own .env); ConsentTrace never sees it.

Endpoints (all JSON, prefix /ct/v1; the full contract is docs/agent_protocol.md):

    GET    /info                         name, versions, capabilities, model availability
    GET    /describe?version=            tool schemas, system prompt, state schema (optional)
    GET    /knowledge                    retrieval knowledge base passages (optional, RAG agents)
    POST   /knowledge/search             the agent's own retriever: {query, k} -> ranked ids (optional)
    POST   /sessions                     start an isolated session for one case execution
    POST   /sessions/{id}/messages       one trusted user turn -> TurnResult
    GET    /sessions/{id}/events?since=  trace events with step_id > since (non-destructive)
    GET    /sessions/{id}/snapshot       current business state, or null without state access
    GET    /sessions/{id}/cassette       model calls recorded in a live session (for later replay)
    GET    /sessions/{id}/artifacts[/n]  files the agent kept for this session (e.g. its SQLite db)
    DELETE /sessions/{id}
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypeVar

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from consenttrace.adapters.base import AgentAdapter, CaseContext, DescribableAdapter, KnowledgeAdapter
from consenttrace.config import LLMSettings
from consenttrace.llm.client import AssistantTurn, ChatClient, OpenAICompatClient, ScriptedClient
from consenttrace.llm.replay import RecordingClient, ReplayClient
from consenttrace.schemas import InjectionSpec, TraceEvent
from consenttrace.sdk.injection import InjectionController

T = TypeVar("T")

PROTOCOL_VERSION = "1"
PREFIX = "/ct/v1"
CASSETTE = "cassette.jsonl"
MAX_SESSIONS = 64
SESSION_TTL_S = 3600.0

# (client_factory, version) -> a fresh adapter around this agent
AdapterFactory = Callable[[Callable[[], ChatClient], str], AgentAdapter]


class LLMOptions(BaseModel):
    """How the agent gets model replies in this session."""

    mode: Literal["live", "replay", "scripted"] = "live"
    cassette: list[dict[str, Any]] | None = None  # replay: entries recorded by an earlier live session
    script: list[dict[str, Any]] | None = None  # scripted: assistant turns, for protocol self-tests without a model
    timeout: float = Field(default=90.0, gt=0)


class SessionRequest(BaseModel):
    version: str
    run_id: str = "adhoc"
    case_id: str = "adhoc"
    fixture: str = "default"
    seed: int = 0
    injections: list[InjectionSpec] = Field(default_factory=list)
    llm: LLMOptions = Field(default_factory=LLMOptions)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    k: int = Field(default=10, ge=1, le=100)


class MessageRequest(BaseModel):
    text: str = Field(min_length=1)


@dataclass
class _Session:
    adapter: AgentAdapter
    workdir: Path
    created: float = field(default_factory=time.monotonic)
    events: dict[int, TraceEvent] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)
    busy: threading.Lock = field(default_factory=threading.Lock)  # one turn at a time, like a real conversation
    # Every call into the adapter runs on this session's own thread: agents often hold
    # thread-bound resources (a sqlite3 connection, for one) created during reset().
    worker: ThreadPoolExecutor = field(default_factory=lambda: ThreadPoolExecutor(max_workers=1, thread_name_prefix="ct-session"))

    def run(self, fn: Callable[..., T], *args: Any) -> T:
        return self.worker.submit(fn, *args).result()

    def record(self, event: TraceEvent) -> None:
        with self.lock:
            self.events[event.step_id] = event

    def since(self, step: int) -> list[TraceEvent]:
        with self.lock:
            return [self.events[k] for k in sorted(self.events) if k > step]


class _Sessions:
    def __init__(self) -> None:
        self._items: dict[str, _Session] = {}
        self._lock = threading.Lock()

    def add(self, session: _Session) -> str:
        sid = uuid.uuid4().hex
        with self._lock:
            self._expire()
            if len(self._items) >= MAX_SESSIONS:
                raise HTTPException(503, f"too many open sessions ({MAX_SESSIONS}); close finished ones first")
            self._items[sid] = session
        return sid

    def get(self, sid: str) -> _Session:
        with self._lock:
            session = self._items.get(sid)
        if session is None:
            raise HTTPException(404, f"unknown or closed session {sid}")
        return session

    def pop(self, sid: str) -> _Session | None:
        with self._lock:
            return self._items.pop(sid, None)

    def _expire(self) -> None:
        now = time.monotonic()
        for sid in [s for s, v in self._items.items() if now - v.created > SESSION_TTL_S]:
            _dispose(self._items.pop(sid))


def _dispose(session: _Session) -> None:
    try:
        session.run(session.adapter.close)
    finally:
        session.worker.shutdown(wait=False)
        shutil.rmtree(session.workdir, ignore_errors=True)


def _probe_client() -> ChatClient:
    return ScriptedClient([])


def create_agent_app(
    *,
    name: str,
    versions: Sequence[str],
    factory: AdapterFactory,
    description: str = "",
    env_file: str | Path | None = ".env",
    settings: LLMSettings | None = None,
) -> FastAPI:
    """Build the protocol server for one agent. `settings` overrides what `env_file` provides."""
    if not versions:
        raise ValueError("an agent needs at least one version")
    versions = list(versions)
    llm = settings if settings is not None else LLMSettings.from_env(env_file)
    sessions = _Sessions()
    caps = factory(_probe_client, versions[0]).capabilities()
    app = FastAPI(title=f"{name} · ConsentTrace Agent Protocol", version=PROTOCOL_VERSION)

    def check_version(version: str) -> None:
        if version not in versions:
            raise HTTPException(400, f"unknown version {version!r}; this agent serves {versions}")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get(f"{PREFIX}/info")
    def info() -> dict[str, Any]:
        return {
            "protocol": PROTOCOL_VERSION,
            "name": name,
            "description": description,
            "versions": versions,
            "capabilities": caps.model_dump(),
            "llm": {"live_available": llm is not None, "model": llm.model if llm else None, "replay": True},
        }

    @app.get(f"{PREFIX}/describe")
    def describe(version: str | None = None) -> dict[str, Any]:
        version = version or versions[0]
        check_version(version)
        adapter = factory(_probe_client, version)
        if not isinstance(adapter, DescribableAdapter):
            raise HTTPException(404, "this agent does not describe itself")
        return adapter.describe().model_dump(mode="json")

    def knowledge_adapter() -> KnowledgeAdapter:
        adapter = factory(_probe_client, versions[0])
        if not isinstance(adapter, KnowledgeAdapter):
            raise HTTPException(404, "this agent has no retrieval knowledge base")
        return adapter

    @app.get(f"{PREFIX}/knowledge")
    def knowledge() -> dict[str, Any]:
        return {"passages": knowledge_adapter().knowledge()}

    @app.post(f"{PREFIX}/knowledge/search")
    def knowledge_search(req: SearchRequest) -> dict[str, Any]:
        return {"ids": knowledge_adapter().search_knowledge(req.query, req.k)}

    @app.post(f"{PREFIX}/sessions")
    def open_session(req: SessionRequest) -> dict[str, str]:
        check_version(req.version)
        workdir = Path(tempfile.mkdtemp(prefix=f"ct-{name}-"))
        session: _Session | None = None
        try:
            clients = _client_factory(req.llm, llm, workdir / CASSETTE)
            adapter = factory(clients, req.version)
            session = _Session(adapter=adapter, workdir=workdir)
            ctx = CaseContext(
                run_id=req.run_id,
                case_id=req.case_id,
                case_dir=workdir,
                fixture=req.fixture,
                seed=req.seed,
                interceptors=[InjectionController(req.injections)] if req.injections else [],
                injections=req.injections,
                on_event=session.record,
            )
            session.run(adapter.reset, ctx)
        except HTTPException:
            shutil.rmtree(workdir, ignore_errors=True)
            raise
        except Exception as exc:
            if session is not None:
                session.worker.shutdown(wait=False)
            shutil.rmtree(workdir, ignore_errors=True)
            raise HTTPException(400, f"session setup failed: {type(exc).__name__}: {exc}") from exc
        return {"session_id": sessions.add(session)}

    @app.post(f"{PREFIX}/sessions/{{sid}}/messages")
    def send(sid: str, req: MessageRequest) -> dict[str, Any]:
        session = sessions.get(sid)
        if not session.busy.acquire(blocking=False):
            raise HTTPException(409, "a turn is already in progress in this session")
        try:
            result = session.run(session.adapter.send, req.text)
            for event in session.run(session.adapter.drain_events):  # adapters that do not stream events still deliver them
                session.record(event)
        finally:
            session.busy.release()
        return result.model_dump(mode="json")

    @app.get(f"{PREFIX}/sessions/{{sid}}/events")
    def events(sid: str, since: int = Query(default=0, ge=0)) -> list[dict[str, Any]]:
        return [e.model_dump(mode="json") for e in sessions.get(sid).since(since)]

    @app.get(f"{PREFIX}/sessions/{{sid}}/snapshot")
    def snapshot(sid: str) -> dict[str, Any] | None:
        session = sessions.get(sid)
        snap = session.run(session.adapter.snapshot)
        return None if snap is None else snap.model_dump(mode="json")

    @app.get(f"{PREFIX}/sessions/{{sid}}/cassette")
    def cassette(sid: str) -> list[dict[str, Any]]:
        path = sessions.get(sid).workdir / CASSETTE
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    @app.get(f"{PREFIX}/sessions/{{sid}}/artifacts")
    def artifacts(sid: str) -> list[str]:
        workdir = sessions.get(sid).workdir
        return sorted(p.name for p in workdir.iterdir() if p.is_file() and p.name != CASSETTE)

    @app.get(f"{PREFIX}/sessions/{{sid}}/artifacts/{{artifact}}")
    def artifact(sid: str, artifact: str) -> FileResponse:
        workdir = sessions.get(sid).workdir
        path = workdir / artifact
        if "/" in artifact or path.name == CASSETTE or not path.is_file():
            raise HTTPException(404, f"no artifact {artifact!r}")
        return FileResponse(path)

    @app.delete(f"{PREFIX}/sessions/{{sid}}")
    def close(sid: str) -> dict[str, bool]:
        session = sessions.pop(sid)
        if session is not None:
            _dispose(session)
        return {"closed": session is not None}

    return app


def _client_factory(options: LLMOptions, settings: LLMSettings | None, cassette: Path) -> Callable[[], ChatClient]:
    if options.mode == "live":
        if settings is None:
            raise HTTPException(409, "this agent has no model key configured (LLM_API_KEY); use replay mode")
        return lambda: RecordingClient(OpenAICompatClient.from_settings(settings, timeout=options.timeout), cassette)
    if options.mode == "replay":
        entries = options.cassette or []
        return lambda: ReplayClient(entries)
    turns = [AssistantTurn.model_validate(t) for t in options.script or []]
    return lambda: ScriptedClient(turns)


def serve_agent(
    *,
    name: str,
    versions: Sequence[str],
    factory: AdapterFactory,
    description: str = "",
    default_port: int = 9100,
    argv: Sequence[str] | None = None,
) -> None:
    """Command-line entry point for an agent process: parses --host/--port/--env-file and serves."""
    ap = argparse.ArgumentParser(description=f"Serve the {name} agent over the ConsentTrace Agent Protocol")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=default_port)
    ap.add_argument("--env-file", default=".env", help="this agent's own model key (LLM_API_KEY / LLM_BASE_URL / LLM_MODEL)")
    args = ap.parse_args(argv)
    import uvicorn

    app = create_agent_app(name=name, versions=versions, factory=factory, description=description, env_file=args.env_file)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")

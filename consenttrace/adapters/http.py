"""Drive an agent that runs in its own process, through the ConsentTrace Agent Protocol.

ConsentTrace knows only the agent's URL. Everything it judges arrives over the wire:
trace events, state snapshots, recorded model calls. Capabilities come from the agent's
own declaration and are checked by `consenttrace probe` (see adapters/probe.py).
"""

from __future__ import annotations

import contextlib
import json
import threading
from pathlib import Path
from typing import Any, Literal

import httpx

from consenttrace.adapters.base import CaseContext
from consenttrace.schemas import AdapterCapabilities, AgentDescription, StateSnapshot, TraceEvent, TurnResult

PREFIX = "/ct/v1"
CASSETTE = "cassette.jsonl"


class AgentProtocolError(RuntimeError):
    """The agent answered, but not as the protocol requires (or not at all)."""


def protocol_client(base_url: str, timeout: float = 120.0) -> httpx.Client:
    return httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout, trust_env=False)


def call(client: httpx.Client, method: str, path: str, **kwargs: Any) -> Any:
    try:
        resp = client.request(method, PREFIX + path, **kwargs)
    except httpx.HTTPError as exc:
        raise AgentProtocolError(f"{method} {path}: {type(exc).__name__}: {exc}") from exc
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except ValueError:
            detail = resp.text
        raise AgentProtocolError(f"{method} {path} -> HTTP {resp.status_code}: {detail}")
    return resp.json() if resp.content else None


def fetch_info(base_url: str, *, client: httpx.Client | None = None, timeout: float = 5.0) -> dict[str, Any]:
    own = client is None
    client = client or protocol_client(base_url, timeout=timeout)
    try:
        return call(client, "GET", "/info")
    finally:
        if own:
            client.close()


class HttpAgentAdapter:
    """An AgentAdapter whose agent lives behind a URL."""

    def __init__(
        self,
        base_url: str,
        *,
        version: str,
        mode: Literal["live", "replay", "scripted"] = "live",
        timeout: float = 90.0,
        client: httpx.Client | None = None,
        poll_interval: float = 0.4,
        script: list[dict[str, Any]] | None = None,  # scripted mode: assistant turns, for self-tests without a model
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.version = version
        self.mode = mode
        self.timeout = timeout
        self._script = script or []
        self._client = client or protocol_client(self.base_url, timeout=timeout + 30)
        self._poll_interval = poll_interval
        self._info: dict[str, Any] | None = None
        self._sid: str | None = None
        self._ctx: CaseContext | None = None
        self._buffer: list[TraceEvent] = []
        self._last_step = 0
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- identity

    @property
    def info(self) -> dict[str, Any]:
        if self._info is None:
            self._info = call(self._client, "GET", "/info")
        return self._info

    @property
    def name(self) -> str:
        return str(self.info["name"])

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities.model_validate(self.info["capabilities"])

    def describe(self) -> AgentDescription:
        return AgentDescription.model_validate(call(self._client, "GET", "/describe", params={"version": self.version}))

    # ---------------------------------------------------------------- one case

    def reset(self, ctx: CaseContext) -> None:
        self.close()
        llm: dict[str, Any] = {"mode": self.mode, "timeout": self.timeout}
        if self.mode == "replay":
            llm["cassette"] = _read_cassette(ctx.case_dir / CASSETTE)
        elif self.mode == "scripted":
            llm["script"] = self._script
        body = {
            "version": self.version,
            "run_id": ctx.run_id,
            "case_id": ctx.case_id,
            "fixture": ctx.fixture,
            "seed": ctx.seed,
            "injections": [spec.model_dump(mode="json") for spec in ctx.injections],
            "llm": llm,
        }
        self._sid = call(self._client, "POST", "/sessions", json=body)["session_id"]
        self._ctx = ctx
        self._buffer, self._last_step = [], 0

    def send(self, user_message: str) -> TurnResult:
        sid, ctx = self._require()
        stop = threading.Event()
        poller = None
        if ctx.on_event is not None:  # stream events to the console while the turn is still running
            poller = threading.Thread(target=self._poll, args=(stop,), daemon=True, name="ct-http-poll")
            poller.start()
        try:
            data = call(self._client, "POST", f"/sessions/{sid}/messages", json={"text": user_message})
        finally:
            stop.set()
            if poller is not None:
                poller.join(timeout=5)
        self._pull()
        return TurnResult.model_validate(data)

    def drain_events(self) -> list[TraceEvent]:
        if self._sid is not None:
            self._pull()
        with self._lock:
            out, self._buffer = self._buffer, []
        return out

    def snapshot(self) -> StateSnapshot | None:
        sid, _ = self._require()
        data = call(self._client, "GET", f"/sessions/{sid}/snapshot")
        return None if data is None else StateSnapshot.model_validate(data)

    def close(self) -> None:
        sid, ctx = self._sid, self._ctx
        self._sid = self._ctx = None
        if sid is None or ctx is None:
            return
        try:
            if self.mode == "live":
                entries = call(self._client, "GET", f"/sessions/{sid}/cassette") or []
                ctx.case_dir.mkdir(parents=True, exist_ok=True)
                (ctx.case_dir / CASSETTE).write_text(
                    "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8"
                )
            for artifact in call(self._client, "GET", f"/sessions/{sid}/artifacts") or []:
                resp = self._client.get(f"{PREFIX}/sessions/{sid}/artifacts/{artifact}")
                if resp.status_code == 200:
                    ctx.case_dir.mkdir(parents=True, exist_ok=True)
                    (ctx.case_dir / Path(artifact).name).write_bytes(resp.content)
        finally:
            # the agent may already have expired the session; nothing left to free
            with contextlib.suppress(AgentProtocolError):
                call(self._client, "DELETE", f"/sessions/{sid}")

    # ---------------------------------------------------------------- internals

    def _require(self) -> tuple[str, CaseContext]:
        if self._sid is None or self._ctx is None:
            raise RuntimeError("call reset() before driving the adapter")
        return self._sid, self._ctx

    def _poll(self, stop: threading.Event) -> None:
        while not stop.wait(self._poll_interval):
            try:
                self._pull()
            except AgentProtocolError:
                return  # the main request reports the failure

    def _pull(self) -> None:
        sid, ctx = self._sid, self._ctx
        if sid is None or ctx is None:
            return
        with self._lock:
            since = self._last_step
            data = call(self._client, "GET", f"/sessions/{sid}/events", params={"since": since})
            fresh = [TraceEvent.model_validate(e) for e in data or []]
            fresh = [e for e in fresh if e.step_id > self._last_step]
            if fresh:
                self._last_step = max(e.step_id for e in fresh)
                self._buffer.extend(fresh)
        if ctx.on_event is not None:
            for event in fresh:
                with contextlib.suppress(Exception):  # a broken viewer must never break the run
                    ctx.on_event(event)


def _read_cassette(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise AgentProtocolError(f"replay needs a recording at {path}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

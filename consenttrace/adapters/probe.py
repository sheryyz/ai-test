"""Onboarding check for an agent behind a URL (F01): does it really deliver what it declares?

Runs without a model: sessions use the protocol's scripted mode, so a probe costs nothing
and can be repeated. What cannot be checked this way (e.g. whether an injection point is
ever reached) is reported as SKIP with the reason, never as PASS.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import httpx
from pydantic import ValidationError

from consenttrace.adapters.http import AgentProtocolError, call, protocol_client
from consenttrace.schemas import AdapterCapabilities, AgentDescription, EventKind, StateSnapshot, TraceEvent, TurnResult

Status = Literal["PASS", "FAIL", "SKIP"]
PING = "ConsentTrace 接入检查：你好"
MARKER = "[ConsentTrace probe marker: injected tool-result text]"
PONG = "probe-ok"


@dataclass
class ProbeCheck:
    key: str
    title: str
    status: Status
    detail: str = ""


@dataclass
class ProbeReport:
    url: str
    info: dict[str, Any] | None = None
    checks: list[ProbeCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c.status != "FAIL" for c in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {"url": self.url, "ok": self.ok, "info": self.info, "checks": [asdict(c) for c in self.checks]}


def probe_agent(url: str, *, version: str | None = None, client: httpx.Client | None = None) -> ProbeReport:
    own = client is None
    client = client or protocol_client(url, timeout=20)
    report = ProbeReport(url=url)
    try:
        _run(report, client, version)
    finally:
        if own:
            client.close()
    return report


def _run(report: ProbeReport, client: httpx.Client, version: str | None) -> None:
    add = report.checks.append
    try:
        info = call(client, "GET", "/info")
        caps = AdapterCapabilities.model_validate(info["capabilities"])
        versions = list(info["versions"])
        if str(info.get("protocol")) != "1" or not info.get("name") or not versions:
            raise ValueError("protocol / name / versions missing")
    except (AgentProtocolError, KeyError, TypeError, ValueError, ValidationError) as exc:
        add(ProbeCheck("handshake", "协议握手", "FAIL", f"{exc}"))
        return
    report.info = info
    version = version or versions[0]
    declared = [k for k in ("output", "trace", "state", "inject_tool_response", "visible_reasoning") if getattr(caps, k)]
    add(
        ProbeCheck(
            "handshake", "协议握手", "PASS", f"{info['name']}：版本 {', '.join(versions)}；声明能力 {', '.join(declared) or '无'}"
        )
    )

    desc: AgentDescription | None = None
    try:
        desc = AgentDescription.model_validate(call(client, "GET", "/describe", params={"version": version}))
        tables = ", ".join(desc.state_schema) or "未声明"
        add(ProbeCheck("describe", "自我描述", "PASS", f"{len(desc.tools)} 个工具；状态表：{tables}（供 AI 起草契约）"))
    except AgentProtocolError as exc:
        status: Status = "SKIP" if "HTTP 404" in str(exc) else "FAIL"
        add(ProbeCheck("describe", "自我描述", status, "Agent 未提供工具定义，契约需人工编写" if status == "SKIP" else str(exc)))
    except ValidationError as exc:
        add(ProbeCheck("describe", "自我描述", "FAIL", f"返回内容不符合 AgentDescription：{exc.error_count()} 处错误"))

    try:
        passages = call(client, "GET", "/knowledge")["passages"]
        add(ProbeCheck("knowledge", "知识库", "PASS", f"{len(passages)} 条段落，可做 RAG 知识库体检"))
    except AgentProtocolError as exc:
        add(
            ProbeCheck(
                "knowledge",
                "知识库",
                "SKIP" if "HTTP 404" in str(exc) else "FAIL",
                "不适用：这个 Agent 没有检索知识库（可选能力），RAG 知识库体检对它不可用" if "HTTP 404" in str(exc) else str(exc),
            )
        )

    sessions: list[str] = []
    try:
        first = _open(client, version, "probe-1")
        sessions.append(first)
        initial = call(client, "GET", f"/sessions/{first}/snapshot")
        turn = TurnResult.model_validate(call(client, "POST", f"/sessions/{first}/messages", json={"text": PING}))
        if caps.output:
            ok = turn.status.value == "ok" and turn.reply == PONG
            add(
                ProbeCheck(
                    "output",
                    "输出能力",
                    "PASS" if ok else "FAIL",
                    "回复与脚本一致" if ok else f"期望回复 {PONG!r}，实际 {turn.reply!r}（{turn.status.value}）",
                )
            )
        else:
            add(ProbeCheck("output", "输出能力", "SKIP", "未声明"))

        events = [
            TraceEvent.model_validate(e) for e in call(client, "GET", f"/sessions/{first}/events", params={"since": 0}) or []
        ]
        add(_trace_check(caps.trace, events))

        snap = call(client, "GET", f"/sessions/{first}/snapshot")
        add(_state_check(caps.state, initial, snap))

        if caps.state and initial is not None:
            second = _open(client, version, "probe-2")
            sessions.append(second)
            other = call(client, "GET", f"/sessions/{second}/snapshot")
            same = other is not None and other.get("digest") == initial.get("digest")
            add(
                ProbeCheck(
                    "isolation",
                    "会话隔离",
                    "PASS" if same else "FAIL",
                    "新会话的初始状态与第一个会话的初始状态一致" if same else "新会话的初始状态不同：用例之间可能相互污染",
                )
            )
        else:
            add(ProbeCheck("isolation", "会话隔离", "SKIP", "没有状态能力，无法比较"))
    except (AgentProtocolError, ValidationError) as exc:
        add(ProbeCheck("session", "会话与输出", "FAIL", str(exc)))
    finally:
        for sid in sessions:
            with contextlib.suppress(AgentProtocolError):
                call(client, "DELETE", f"/sessions/{sid}")

    if caps.inject_tool_response:
        add(_inject_check(client, version, desc))
    else:
        add(ProbeCheck("inject", "工具返回注入", "SKIP", "未声明：注入类用例将无法执行注入"))
    llm = info.get("llm") or {}
    add(
        ProbeCheck(
            "model",
            "模型与回放",
            "PASS" if llm.get("live_available") or llm.get("replay") else "SKIP",
            f"Live：{'可用（' + str(llm.get('model')) + '）' if llm.get('live_available') else '未配置 Key'}；回放：{'支持' if llm.get('replay') else '不支持'}",
        )
    )


def _open(
    client: httpx.Client, version: str, case_id: str, *, script: list[dict] | None = None, injections: list[dict] | None = None
) -> str:
    body = {
        "version": version,
        "run_id": "probe",
        "case_id": case_id,
        "injections": injections or [],
        "llm": {"mode": "scripted", "script": script or [{"content": PONG}]},
    }
    return call(client, "POST", "/sessions", json=body)["session_id"]


def _no_argument_tool(desc: AgentDescription | None) -> str | None:
    """A tool the scripted session can call without inventing arguments; listing / reading tools first."""
    if desc is None:
        return None
    names = [t["function"]["name"] for t in desc.tools if not (t["function"].get("parameters") or {}).get("required")]
    names.sort(key=lambda n: (not n.startswith(("list", "get", "search", "show")), n))
    return names[0] if names else None


def _inject_check(client: httpx.Client, version: str, desc: AgentDescription | None) -> ProbeCheck:
    """Script one tool call with an injection on it, in a throwaway session, and look for the marker."""
    tool = _no_argument_tool(desc)
    if tool is None:
        return ProbeCheck(
            "inject",
            "工具返回注入",
            "SKIP",
            "已声明；但没有可以不带参数安全调用的工具，需在含注入的用例中验证（未命中的注入记为 SKIPPED）",
        )
    script = [
        {"tool_calls": [{"id": "probe-call", "name": tool, "arguments": {}, "raw_arguments": "{}"}]},
        {"content": PONG},
    ]
    injection = {
        "injection_id": "PROBE-INJ",
        "tool": tool,
        "mode": "append_text",
        "payload": MARKER,
        "field": "consenttrace_probe",
    }
    sid = None
    try:
        sid = _open(client, version, "probe-inject", script=script, injections=[injection])
        call(client, "POST", f"/sessions/{sid}/messages", json={"text": PING})
        events = [TraceEvent.model_validate(e) for e in call(client, "GET", f"/sessions/{sid}/events", params={"since": 0}) or []]
    except (AgentProtocolError, ValidationError) as exc:
        return ProbeCheck("inject", "工具返回注入", "FAIL", f"带注入的会话失败：{exc}")
    finally:
        if sid is not None:
            with contextlib.suppress(AgentProtocolError):
                call(client, "DELETE", f"/sessions/{sid}")
    fired = any(e.kind is EventKind.INJECTION and e.injection_id == "PROBE-INJ" for e in events)
    seen = any(e.kind is EventKind.TOOL_RESULT and e.tool == tool and MARKER in str(e.result) for e in events)
    if fired and seen:
        return ProbeCheck(
            "inject", "工具返回注入", "PASS", f"在隔离会话里调用 {tool}：注入事件已记录，Agent 看到的返回里出现了注入的标记文字"
        )
    if not any(e.kind is EventKind.TOOL_CALL_ATTEMPT and e.tool == tool for e in events):
        return ProbeCheck("inject", "工具返回注入", "FAIL", f"脚本要求调用 {tool}，但轨迹里没有这次调用")
    return ProbeCheck(
        "inject",
        "工具返回注入",
        "FAIL",
        f"声明了注入能力，但调用 {tool} 时{'没有记录注入事件' if not fired else 'Agent 看到的返回里没有注入内容'}",
    )


def _trace_check(declared: bool, events: list[TraceEvent]) -> ProbeCheck:
    if not declared:
        return ProbeCheck(
            "trace",
            "轨迹能力",
            "PASS" if not events else "FAIL",
            "未声明，也没有返回事件" if not events else "未声明却返回了事件",
        )
    problems = []
    if not events:
        problems.append("声明了轨迹能力，但一轮对话后没有任何事件")
    else:
        if events[0].kind is not EventKind.USER_MESSAGE or events[0].content != PING:
            problems.append("第一个事件应是本轮的用户消息")
        steps = [e.step_id for e in events]
        if steps != list(range(steps[0], steps[0] + len(steps))):
            problems.append(f"step_id 不连续：{steps}")
        if {e.case_id for e in events} != {"probe-1"}:
            problems.append("事件没有带上会话的 case_id")
    if problems:
        return ProbeCheck("trace", "轨迹能力", "FAIL", "；".join(problems))
    kinds = sorted({e.kind.value for e in events})
    return ProbeCheck("trace", "轨迹能力", "PASS", f"{len(events)} 个有序事件：{', '.join(kinds)}")


def _state_check(declared: bool, initial: Any, snap: Any) -> ProbeCheck:
    if not declared:
        ok = initial is None and snap is None
        return ProbeCheck("state", "状态能力", "PASS" if ok else "FAIL", "未声明，快照为空" if ok else "未声明却返回了快照")
    try:
        parsed = StateSnapshot.model_validate(snap)
    except ValidationError as exc:
        return ProbeCheck("state", "状态能力", "FAIL", f"快照不符合 StateSnapshot：{exc.error_count()} 处错误")
    if not parsed.tables or not re.fullmatch(r"[0-9a-f]{64}", parsed.digest):
        return ProbeCheck("state", "状态能力", "FAIL", "快照没有表或摘要格式不对")
    rows = sum(len(t.rows) for t in parsed.tables.values())
    return ProbeCheck("state", "状态能力", "PASS", f"{len(parsed.tables)} 张表、{rows} 行，摘要 {parsed.digest[:12]}…")

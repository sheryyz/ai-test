"""ConsentTrace command line: validate, run, show, runs."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.text import Text

from consenttrace.core.evidence import EvidenceStore, load_results, load_summary, load_trace
from consenttrace.core.launch import LaunchError, RunRequest, prepare_run
from consenttrace.core.loader import LoadError, load_cases, load_contract
from consenttrace.core.reevaluate import reevaluate_run
from consenttrace.core.registry import load_targets
from consenttrace.core.runner import outcome_exit_code
from consenttrace.schemas import EventKind, RunResult, TraceEvent

console = Console()

OUTCOME_STYLE = {"PASS": "bold green", "FAIL": "bold red", "ERROR": "bold yellow", "UNSUPPORTED": "bold bright_black"}
LANE_STYLE = {
    "用户": "bold blue",
    "Agent": "cyan",
    "模型": "bright_black",
    "工具": "white",
    "注入": "bold magenta",
    "状态": "bold cyan",
    "错误": "bold red",
}


# ---------------------------------------------------------------- validate


def cmd_validate(args: argparse.Namespace) -> int:
    targets = load_targets(args.targets)
    table = Table(title="ConsentTrace 配置校验", title_style="bold")
    for col in ("目标", "对象", "结果", "说明"):
        table.add_column(col)
    problems = 0
    for name, spec in targets.items():
        try:
            spec.adapter_class()
            table.add_row(name, f"adapter {spec.adapter}", "[green]OK[/]", "")
        except Exception as exc:
            problems += 1
            table.add_row(name, f"adapter {spec.adapter}", "[red]ERROR[/]", f"{type(exc).__name__}: {exc}")
        try:
            contract = load_contract(spec.contract)
            table.add_row(
                name,
                f"contract {spec.contract.name}",
                "[green]OK[/]",
                f"{len(contract.sensitive_actions)} 个敏感动作，{len(contract.rules)} 条规则",
            )
        except LoadError as exc:
            problems += 1
            table.add_row(name, f"contract {spec.contract.name}", "[red]ERROR[/]", "\n".join(exc.problems))
            continue
        for suite, path in spec.suites.items():
            try:
                cases = load_cases(path, contract)
                table.add_row(name, f"suite {suite} ({path.name})", "[green]OK[/]", f"{len(cases)} 条用例")
            except LoadError as exc:
                problems += 1
                table.add_row(name, f"suite {suite} ({path.name})", "[red]ERROR[/]", "\n".join(exc.problems[:10]))
    console.print(table)
    return 1 if problems else 0


# ---------------------------------------------------------------- run


def cmd_run(args: argparse.Namespace) -> int:
    request = RunRequest(
        target=args.target,
        version=args.version,
        suite=args.suite,
        mode=args.mode,
        reps=args.reps,
        concurrency=args.concurrency,
        cases=args.case,
        replay_from=args.replay_from,
        run_id=args.run_id,
        max_tokens=args.max_tokens,
        timeout=args.timeout,
    )
    done = 0
    total = 0

    def on_result(result: RunResult) -> None:
        nonlocal done
        done += 1
        rules = ",".join(sorted({f.rule_id for f in result.findings}))
        tokens = result.metrics.get("usage", {})
        tok = (tokens.get("prompt_tokens", 0) + tokens.get("completion_tokens", 0)) if tokens else 0
        console.print(
            f"  [{done:>3}/{total}] ",
            Text(f"{result.outcome.value:<11}", style=OUTCOME_STYLE[result.outcome.value]),
            f"{result.case_id} r{result.rep}",
            Text(f"  {rules}" if rules else "", style="red"),
            Text(f"  {tok} tok · {result.metrics.get('duration_ms', 0) / 1000:.1f}s", style="bright_black"),
        )

    try:
        prepared = prepare_run(request, targets_path=args.targets, runs_dir=args.runs_dir, env_file=args.env, on_result=on_result)
    except LaunchError as exc:
        console.print(f"[red]{exc}[/]")
        return 2
    config, cases = prepared.config, prepared.cases
    store = prepared.runner.store
    total = prepared.total
    console.rule(f"[bold]ConsentTrace run[/] {config.run_id}")
    console.print(
        f"目标 [bold]{prepared.spec.name}[/] {config.agent_version} · 模式 [bold]{config.mode}[/] · 模型 {config.model_id} · 套件 {config.suite}"
        f" · {len(cases)} 条用例 × {config.reps} 次 · 并发 {config.concurrency}"
    )
    summary = prepared.runner.run(cases)
    _print_results(load_results(store.run_dir))
    counts = " · ".join(f"{k} {v}" for k, v in sorted(summary.counts.items()))
    console.print(
        f"\n[bold]{counts}[/] · 模型调用 {summary.llm_calls} 次 · {summary.usage.total_tokens} tokens"
        f"（缓存命中 {summary.usage.cached_tokens}）\n证据目录：[underline]{store.run_dir}[/]"
    )
    return outcome_exit_code(summary.counts)


def _print_results(results: Sequence[RunResult]) -> None:
    table = Table(title="执行结果", title_style="bold", show_lines=False)
    for col in ("用例", "rep", "结果", "首个违规步骤", "违规规则", "敏感调用(未授权/总数)", "tokens"):
        table.add_column(col)
    for r in results:
        m = r.metrics
        usage = m.get("usage") or {}
        table.add_row(
            r.case_id,
            str(r.rep),
            Text(r.outcome.value, style=OUTCOME_STYLE[r.outcome.value]),
            str(m.get("first_bad_step") or "—"),
            Text(", ".join(sorted({f.rule_id for f in r.findings})) or "—", style="red" if r.findings else ""),
            f"{m.get('unauthorized_attempts', 0)}/{m.get('sensitive_attempts', 0)}",
            str(usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)),
        )
    console.print(table)


# ---------------------------------------------------------------- show


def _short(value: Any, limit: int = 90) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _describe(e: TraceEvent) -> tuple[str, str]:
    k = e.kind
    if k is EventKind.USER_MESSAGE:
        return "用户", e.content or ""
    if k is EventKind.LLM_CALL:
        usage = e.meta.get("usage", {})
        return (
            "模型",
            f"{e.meta.get('model')} · {e.meta.get('latency_ms')}ms · {usage.get('prompt_tokens', 0)}+{usage.get('completion_tokens', 0)} tok",
        )
    if k is EventKind.AGENT_REASONING:
        return "模型", "推理摘要：" + _short(e.content or "")
    if k is EventKind.TOOL_CALL_ATTEMPT:
        return "Agent", f"调用 {e.tool}({_short(e.args or {}, 110)})"
    if k is EventKind.WRITE_RECEIPT:
        r = e.result or {}
        return "状态", f"写入回执 {r.get('table')} {r.get('op')} {_short(r.get('pk'))}"
    if k is EventKind.INJECTION:
        return "注入", f"{e.injection_id} [{e.meta.get('mode')}] → {_short(e.result, 100)}"
    if k is EventKind.TOOL_RESULT:
        return "工具", f"{e.tool} 返回 [{e.status.value if e.status else ''}] {_short(e.result, 100)}"
    if k is EventKind.AGENT_MESSAGE:
        return "Agent", ("（工具调用前）" if e.meta.get("with_tool_calls") else "回复：") + _short(e.content or "", 120)
    return "错误", e.content or ""


def cmd_show(args: argparse.Namespace) -> int:
    run_dir = Path(args.runs_dir) / args.run
    if not run_dir.exists():
        console.print(f"[red]找不到运行 {run_dir}[/]")
        return 2
    if not args.case:
        summary = load_summary(run_dir)
        console.rule(f"[bold]{summary.run_id}[/]")
        console.print(f"{summary.target} {summary.agent_version} · {summary.mode} · {summary.model_id} · {summary.counts}")
        _print_results(load_results(run_dir))
        return 0

    case_dir = run_dir / "cases" / args.case / f"r{args.rep}"
    verdict = RunResult.model_validate_json((case_dir / "verdict.json").read_text(encoding="utf-8"))
    events = load_trace(case_dir)
    auth = json.loads((case_dir / "auth_timeline.json").read_text(encoding="utf-8"))
    transitions_by_step: dict[int, list[dict]] = {}
    for t in auth.get("transitions", []):
        transitions_by_step.setdefault(t["step"], []).append(t)
    attempts = {a["step"]: a for a in auth.get("attempts", [])}
    bad_steps: dict[int, list[str]] = {}
    for f in verdict.findings:
        bad_steps.setdefault(f.first_bad_step, []).append(f.rule_id)

    console.rule(f"[bold]{args.case}[/] r{args.rep} · ", style="bright_black")
    console.print(
        Text(verdict.outcome.value, style=OUTCOME_STYLE[verdict.outcome.value]),
        f" {verdict.agent_version} · {verdict.mode} · {verdict.model_id}",
    )
    table = Table(
        show_lines=False, expand=True, title="三通道审计时间轴（用户授权 / Agent 与工具 / 业务状态）", title_style="bold"
    )
    table.add_column("step", justify="right", style="bright_black", width=4)
    table.add_column("轮", justify="right", width=2)
    table.add_column("通道", width=6)
    table.add_column("事件", ratio=1)
    for e in events:
        if not args.verbose and e.kind in (EventKind.LLM_CALL,):
            continue
        lane, text = _describe(e)
        row_style = ""
        note = ""
        attempt = attempts.get(e.step_id)
        if attempt is not None:
            mark = "✓ 已授权" if attempt["authorized"] else "✗ 未授权"
            note = f"  [{mark} · 授权状态 {attempt['status_at_attempt']} v{attempt['version']}]"
        if e.step_id in bad_steps:
            row_style = "on #3b0d0d"
            note += f"  ⚠ {', '.join(bad_steps[e.step_id])}"
        table.add_row(
            str(e.step_id), str(e.turn_id), Text(lane, style=LANE_STYLE.get(lane, "")), Text(text + note), style=row_style
        )
        for t in transitions_by_step.get(e.step_id, []):
            label = f"授权账本 {t['action']}: {t['from_status']} → {t['to_status']} (v{t['version']}) {_short(t['params'], 80)}"
            table.add_row("", "", Text("授权", style="bold blue"), Text(label, style="blue"))
    console.print(table)

    if verdict.findings:
        ft = Table(title="发现", title_style="bold red")
        for col in ("规则", "类型", "step", "原因", "期望", "实际"):
            ft.add_column(col)
        for f in verdict.findings:
            ft.add_row(f.rule_id, f.kind.value, str(f.first_bad_step), f.reason, _short(f.expected, 40), _short(f.actual, 40))
        console.print(ft)

    diff_path = case_dir / "state_diff.json"
    diff = json.loads(diff_path.read_text(encoding="utf-8")) if diff_path.exists() else None
    if diff and diff.get("tables"):
        dt = Table(title="业务状态变化（before → after）", title_style="bold cyan")
        for col in ("表", "变化", "主键", "内容"):
            dt.add_column(col)
        for name, td in diff["tables"].items():
            for change in td["inserted"]:
                dt.add_row(name, "[green]新增[/]", _short(change["pk"]), _short(change["after"], 100))
            for change in td["deleted"]:
                dt.add_row(name, "[red]删除[/]", _short(change["pk"]), _short(change["before"], 100))
            for change in td["updated"]:
                fields = ", ".join(f"{c}: {change['before'][c]} → {change['after'][c]}" for c in change["changed"])
                dt.add_row(name, "[yellow]修改[/]", _short(change["pk"]), fields)
        console.print(dt)

    at = Table(title="断言", title_style="bold")
    for col in ("断言", "结果", "说明"):
        at.add_column(col)
    for a in verdict.assertions:
        at.add_row(a.rule_id, Text(a.status.value, style=OUTCOME_STYLE.get(a.status.value, "")), a.detail)
    console.print(at)
    for err in verdict.errors:
        console.print(f"[yellow]错误：{err.strip()}[/]")
    return 0


# ---------------------------------------------------------------- runs


def cmd_runs(args: argparse.Namespace) -> int:
    root = Path(args.runs_dir)
    table = Table(title="运行记录", title_style="bold")
    for col in ("run_id", "目标/版本", "模式", "模型", "执行数", "结果"):
        table.add_column(col)
    for run_dir in sorted((p for p in root.glob("*") if (p / "summary.json").exists()), reverse=True):
        s = load_summary(run_dir)
        counts = " ".join(f"{k}:{v}" for k, v in sorted(s.counts.items()))
        table.add_row(s.run_id, f"{s.target} {s.agent_version}", s.mode, s.model_id or "—", str(s.executions), counts)
    console.print(table)
    return 0


def cmd_reevaluate(args: argparse.Namespace) -> int:
    source = Path(args.runs_dir) / args.run
    if not (source / "summary.json").exists():
        console.print(f"[red]找不到运行 {source}[/]")
        return 2
    config = json.loads((source / "config.json").read_text(encoding="utf-8"))
    spec = load_targets(args.targets).get(config.get("target", ""))
    if spec is None or config.get("suite") not in spec.suites:
        console.print(f"[red]运行 {args.run} 的目标或套件已不在注册表中：{config.get('target')} / {config.get('suite')}[/]")
        return 2
    contract = load_contract(spec.contract)
    cases = {c.case_id: c for c in load_cases(spec.suite(config["suite"]), contract)}
    try:
        fallback = spec.adapter_class()(lambda: None).capabilities()
    except Exception:
        fallback = None
    new_id = args.as_run or f"{args.run}-reeval-{datetime.now():%m%d%H%M%S}"
    changes: list[tuple[RunResult, RunResult]] = []

    def on_result(old: RunResult, new: RunResult) -> None:
        if old.outcome != new.outcome or {f.rule_id for f in old.findings} != {f.rule_id for f in new.findings}:
            changes.append((old, new))

    summary = reevaluate_run(
        source,
        EvidenceStore(args.runs_dir, new_id),
        contract=contract,
        cases=cases,
        fallback_capabilities=fallback,
        on_result=on_result,
    )
    console.rule(f"[bold]重新判定[/] {args.run} → {new_id}")
    table = Table(title=f"判定发生变化的执行（{len(changes)} / {summary.executions}）", title_style="bold")
    for col in ("用例", "rep", "原结果", "新结果", "原违规规则", "新违规规则"):
        table.add_column(col)
    for old, new in changes:
        table.add_row(
            old.case_id,
            str(old.rep),
            Text(old.outcome.value, style=OUTCOME_STYLE[old.outcome.value]),
            Text(new.outcome.value, style=OUTCOME_STYLE[new.outcome.value]),
            ", ".join(sorted({f.rule_id for f in old.findings})) or "—",
            ", ".join(sorted({f.rule_id for f in new.findings})) or "—",
        )
    console.print(table)
    console.print(f"新结果：{summary.counts}（原始运行保持不变：{source}）")
    return outcome_exit_code(summary.counts)


def cmd_serve(args: argparse.Namespace) -> int:  # pragma: no cover - blocks on a server
    import uvicorn

    from consenttrace.api.app import create_app

    app = create_app(targets_path=args.targets, runs_dir=args.runs_dir, env_file=args.env)
    console.print(f"ConsentTrace 控制台：[underline]http://{args.host}:{args.port}[/]")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


# ---------------------------------------------------------------- entry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="consenttrace", description="面向多轮授权与工具注入的 AI Agent 自动化测试平台")
    parser.add_argument("--targets", default="configs/targets.yaml", help="目标注册表（默认 configs/targets.yaml）")
    parser.add_argument("--runs-dir", default="runs", help="证据目录（默认 runs/）")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate", help="校验适配器、契约与用例集")

    run = sub.add_parser("run", help="执行测试套件")
    run.add_argument("--target", required=True)
    run.add_argument("--version", default="v1")
    run.add_argument("--suite", default="smoke")
    run.add_argument("--mode", choices=["live", "replay"], default="live")
    run.add_argument("--replay-from", help="回放某次 Live 运行的录制（run_id）")
    run.add_argument("-k", "--reps", type=int, help="每条用例重复执行次数（Live 默认 1；Replay 默认与被回放的运行一致）")
    run.add_argument("-j", "--concurrency", type=int, default=1, help="并行执行的用例数")
    run.add_argument("--case", action="append", help="只运行指定用例（可重复，支持前缀）")
    run.add_argument("--run-id")
    run.add_argument("--max-tokens", type=int, help="整次运行的 token 预算")
    run.add_argument("--timeout", type=float, default=90.0, help="单次模型调用超时（秒）")
    run.add_argument("--env", default=".env")

    show = sub.add_parser("show", help="查看运行结果或某个用例的审计时间轴")
    show.add_argument("--run", required=True)
    show.add_argument("--case")
    show.add_argument("--rep", type=int, default=0)
    show.add_argument("-v", "--verbose", action="store_true", help="同时显示每次模型调用")

    sub.add_parser("runs", help="列出运行记录")

    reeval = sub.add_parser("reevaluate", help="用当前契约与用例重新判定一次已完成的运行（不调用模型）")
    reeval.add_argument("--run", required=True)
    reeval.add_argument("--as", dest="as_run", help="新运行的 run_id")

    serve = sub.add_parser("serve", help="启动 Web 控制台（FastAPI + 前端）")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--env", default=".env")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {
        "validate": cmd_validate,
        "run": cmd_run,
        "show": cmd_show,
        "runs": cmd_runs,
        "serve": cmd_serve,
        "reevaluate": cmd_reevaluate,
    }
    try:
        return handlers[args.command](args)
    except LoadError as exc:
        console.print(f"[red]配置错误：{exc.source}[/]")
        for p in exc.problems:
            console.print(f"  [red]- {p}[/]")
        return 2


if __name__ == "__main__":
    sys.exit(main())

"""ConsentTrace command line: validate, run, show, runs, reevaluate, detectors, serve."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.text import Text

from consenttrace.adapters.probe import probe_agent
from consenttrace.core.agents import AgentProcesses, AgentStatus
from consenttrace.core.baselines import ORACLE_LABELS, ORACLES
from consenttrace.core.detector_eval import (
    compare_on_run,
    executions,
    load_corpus,
    run_corpus,
    score_corpus,
    score_table,
    write_score_csv,
)
from consenttrace.core.evidence import EvidenceStore, load_results, load_summary, load_trace, write_json
from consenttrace.core.launch import LaunchError, RunRequest, prepare_run
from consenttrace.core.loader import LoadError, load_cases, load_contract, load_suite
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
        if spec.service_url:
            table.add_row(
                name, f"service {spec.service_url}", "[green]OK[/]", "独立进程；在线状态与能力用 consenttrace agents 检查"
            )
        if spec.adapter:
            try:
                spec.adapter_class()
                table.add_row(name, f"adapter {spec.adapter}", "[green]OK[/]", "同进程（开发与测试）")
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
            label = f"suite {suite} ({path.name}{' 子集' if suite in spec.subsets else ''})"
            try:
                cases = load_suite(spec, suite, contract)
                table.add_row(name, label, "[green]OK[/]", f"{len(cases)} 条用例")
            except LoadError as exc:
                problems += 1
                table.add_row(name, label, "[red]ERROR[/]", "\n".join(exc.problems[:10]))
            except ValueError as exc:
                problems += 1
                table.add_row(name, label, "[red]ERROR[/]", str(exc))
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
        transport=args.via,
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


def _declared_capabilities(spec: Any) -> Any:
    """What the target's adapter declares, for runs recorded before capabilities were stored per execution."""
    try:
        return spec.adapter_class()(lambda: None).capabilities()
    except Exception:
        return None


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
    fallback = _declared_capabilities(spec)
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


def _pct(num: int, den: int) -> str:
    return f"{num}/{den}" if den else "—"


def _build_judge(args: argparse.Namespace) -> Any:
    from consenttrace.ai.llm_judge import JudgeCache, LLMJudge
    from consenttrace.config import LLMSettings
    from consenttrace.llm.client import OpenAICompatClient

    settings = LLMSettings.from_env(args.env, model_var="JUDGE_MODEL")
    if settings is None:
        raise SystemExit("LLM 裁判需要 .env 中的 LLM_API_KEY（裁判模型取 JUDGE_MODEL）")
    client = OpenAICompatClient.from_settings(settings, timeout=args.timeout, response_format={"type": "json_object"})
    cache = JudgeCache(args.judge_cache or Path(args.runs_dir) / "judge_cache" / f"{settings.model}.jsonl")
    return LLMJudge(client, cache, samples=args.judge_samples)


class JudgeUnavailable(RuntimeError):
    pass


def _prefetch(judge: Any, execs: list[Any], contract: Any, workers: int, label: str) -> None:
    """Fill the judge cache; refuse to score on a partial judge (a failed call would read as "not flagged")."""
    from rich.progress import Progress

    with Progress(console=console, transient=True) as progress:
        task = progress.add_task(f"LLM 裁判 · {label}", total=None)
        judge.prefetch(execs, contract, workers=workers, on_done=lambda d, t: progress.update(task, completed=d, total=t))
    if judge.stats.call_failures:
        raise JudgeUnavailable(
            f"{judge.stats.call_failures} 次裁判调用失败（网络、限流或余额不足），结果不完整，未评分。"
            f"已成功的回答保存在 {judge.cache.path}，重新运行会从缓存续跑。"
        )


def _print_judge(summaries: list[dict[str, Any]]) -> None:
    for sm in summaries:
        sc = sm["self_consistency"]
        console.print(
            f"  {ORACLE_LABELS.get(sm['view'], sm['view'])}（{sm['model']}，{sm['prompt_version']}）："
            f"自一致 {_pct(sc['agree'], sc['total'])}，无法解析的回答 {sm['unusable_answers']}"
        )


def cmd_detectors(args: argparse.Namespace) -> int:
    """Score every oracle on a labelled defect corpus, and compare them on real (unlabelled) runs."""
    try:
        return _detectors(args)
    except JudgeUnavailable as exc:
        console.print(f"[red]{exc}[/]")
        return 3


def _detectors(args: argparse.Namespace) -> int:
    from consenttrace.ai.llm_judge import VIEWS

    corpus = load_corpus(args.corpus)
    spec = load_targets(args.targets)[corpus.TARGET]
    contract = load_contract(spec.contract)
    suite = {c.case_id: c for c in load_cases(spec.suite(corpus.SUITE), contract)}
    judge = _build_judge(args) if args.llm_judge else None
    oracles = {**ORACLES, **judge.oracles()} if judge else None
    run_id = args.run_id or f"detectors-{corpus.TARGET}-{datetime.now():%m%d%H%M%S}"
    run_dir = run_corpus(corpus, targets_path=args.targets, runs_dir=args.runs_dir, run_id=run_id)
    if judge:
        labels = json.loads((run_dir / "labels.json").read_text(encoding="utf-8"))
        corpus_execs = [ex for _, _, ex in executions(run_dir, suite, case_of=lambda cid: labels[cid]["case_id"])]
        _prefetch(judge, corpus_execs, contract, args.judge_workers, "缺陷语料")
    scored = score_corpus(run_dir, contract, suite, oracles)
    if judge:
        scored["llm_judge"] = [judge.view_summary(corpus_execs, contract, v) for v in VIEWS]
    write_json(run_dir / "detector_eval.json", scored)
    write_score_csv(score_table(scored), Path(args.reports_dir) / run_id / "benchmark_comparison.csv")

    n, pos = scored["executions"], scored["positives"]
    console.rule(f"[bold]检测器评估[/] {run_id}（{n} 条带标注执行，{pos} 条含越权）")
    table = Table(title="同一批执行、只换判定方法（召回 = TP/正例，误报 = FP/负例）", title_style="bold")
    for col in ("判定方法", "越权 召回", "越权 误报", "副作用 召回", "副作用 误报", "虚假陈述 召回", "首个违规步骤"):
        table.add_column(col)
    for name, s in scored["scores"].items():
        v, se, cl, loc = s["violation"], s["side_effect"], s["claim"], s["localization"]
        table.add_row(
            ORACLE_LABELS.get(name, name),
            _pct(v["tp"], v["tp"] + v["fn"]),
            _pct(v["fp"], v["fp"] + v["tn"]),
            _pct(se["tp"], se["tp"] + se["fn"]),
            _pct(se["fp"], se["fp"] + se["tn"]),
            _pct(cl["tp"], cl["tp"] + cl["fn"]),
            _pct(loc["num"], loc["den"]),
        )
    console.print(table)
    if judge:
        _print_judge(scored["llm_judge"])
    console.print("[bright_black]语料为人工编写并预先标注的脚本化行为，只用于度量检测器，不代表真实 Agent 的缺陷率。[/]")

    comparisons = []
    for real in args.on_run or []:
        source = Path(args.runs_dir) / real
        config = json.loads((source / "config.json").read_text(encoding="utf-8"))
        real_spec = load_targets(args.targets)[config["target"]]
        real_contract = load_contract(real_spec.contract)
        real_cases = {c.case_id: c for c in load_cases(real_spec.suite(config["suite"]), real_contract)}
        fallback = _declared_capabilities(real_spec)
        if judge:
            real_execs = [ex for _, _, ex in executions(source, real_cases, fallback_capabilities=fallback)]
            _prefetch(judge, real_execs, real_contract, args.judge_workers, real)
        cmp = compare_on_run(source, real_contract, real_cases, oracles, fallback_capabilities=fallback)
        if judge:
            cmp["llm_judge"] = [judge.view_summary(real_execs, real_contract, v) for v in VIEWS]
        comparisons.append(cmp)
        t = Table(title=f"真实运行 {real}（{cmp['executions']} 次执行，无标注）", title_style="bold")
        for col in ("判定方法", "判为越权", "与 ConsentTrace 一致"):
            t.add_column(col)
        for name, flagged in cmp["flagged"].items():
            t.add_row(ORACLE_LABELS.get(name, name), str(flagged), _pct(cmp["agreement_with_ours"][name], cmp["executions"]))
        console.print(t)
        if judge:
            _print_judge(cmp["llm_judge"])
    if comparisons:
        write_json(run_dir / "real_run_comparison.json", comparisons)
    if judge:
        st = judge.stats
        console.print(
            f"LLM 裁判本次调用 {st.calls} 次（其余来自缓存 {judge.cache.path}），"
            f"token：输入 {st.prompt_tokens} / 输出 {st.completion_tokens}，失败 {st.errors}"
        )
    console.print(f"证据：{run_dir}　表格：{Path(args.reports_dir) / run_id / 'benchmark_comparison.csv'}")
    return 0


def cmd_augment(args: argparse.Namespace) -> int:
    """F10: generate phrasing variants of a suite, validate them deterministically and freeze them."""
    from collections import Counter

    from consenttrace.ai.case_augmenter import CaseAugmenter, VariantSpec, write_suite
    from consenttrace.config import LLMSettings
    from consenttrace.llm.client import OpenAICompatClient

    spec = load_targets(args.targets)[args.target]
    contract = load_contract(spec.contract)
    cases = load_cases(spec.suite(args.suite), contract)
    if args.case:
        cases = [c for c in cases if any(c.case_id.startswith(p) for p in args.case)]
    variant_spec_path = Path(args.spec or f"configs/{args.target}_variants.yaml")
    variant_spec = VariantSpec.load(variant_spec_path)
    settings = LLMSettings.from_env(args.env, model_var="JUDGE_MODEL")
    if settings is None:
        console.print("[red]生成变体需要 .env 中的 LLM_API_KEY[/]")
        return 2
    if args.model:
        settings = LLMSettings(base_url=settings.base_url, model=args.model, api_key=settings.api_key)
    client = OpenAICompatClient.from_settings(settings, timeout=args.timeout, response_format={"type": "json_object"})
    augmenter = CaseAugmenter(client, variant_spec, n=args.n, max_attempts=args.max_attempts)
    out = Path(args.out or f"benchmarks/{args.target}_variants.jsonl")

    from rich.progress import Progress

    with Progress(console=console, transient=True) as progress:
        task = progress.add_task(f"生成措辞变体（{settings.model}）", total=len(cases))
        variants, reports = augmenter.augment_all(cases, workers=args.workers, on_done=lambda r: progress.advance(task))
    order = {c.case_id: i for i, c in enumerate(cases)}
    variants.sort(key=lambda v: (order[v.case_id.rsplit(".p", 1)[0]], v.case_id))
    reports.sort(key=lambda r: order[r.case_id])

    provenance = {
        "target": args.target,
        "base_suite": args.suite,
        "spec_id": variant_spec.spec_id,
        "model": settings.model,
        "per_case": args.n,
        "max_attempts": args.max_attempts,
    }
    write_suite(out, variants, provenance)
    load_cases(out, contract)  # the frozen file must load like any other suite
    report_path = out.with_suffix(".report.json")
    write_json(
        report_path,
        {**provenance, "cases": len(cases), "variants": len(variants), "reports": [r.__dict__ for r in reports]},
    )

    table = Table(title=f"措辞变体：{len(variants)} / {args.n * len(cases)} 个通过校验", title_style="bold")
    for col in ("用例", "通过", "轮次", "被拒", "错误"):
        table.add_column(col)
    for r in reports:
        style = "green" if r.accepted == r.requested else "yellow"
        table.add_row(
            r.case_id, Text(f"{r.accepted}/{r.requested}", style=style), str(r.attempts), str(len(r.rejected)), str(len(r.errors))
        )
    console.print(table)
    reasons = Counter(p.split("：", 1)[-1].split("（")[0] for r in reports for rej in r.rejected for p in rej["problems"])
    if reasons:
        console.print("被拒原因：" + "；".join(f"{k} ×{v}" for k, v in reasons.most_common(8)))
    tokens = sum(r.prompt_tokens for r in reports), sum(r.completion_tokens for r in reports)
    console.print(f"token：输入 {tokens[0]} / 输出 {tokens[1]}　已冻结：{out}　校验记录：{report_path}")
    return 0 if len(variants) == args.n * len(cases) else 1


def cmd_phrasing(args: argparse.Namespace) -> int:
    """F10 metamorphic check on a variants run, against the base run's repetitions."""
    from consenttrace.core.analysis import phrasing_sensitivity

    source = Path(args.runs_dir) / args.run
    config = json.loads((source / "config.json").read_text(encoding="utf-8"))
    spec = load_targets(args.targets)[config["target"]]
    contract = load_contract(spec.contract)
    cases = {c.case_id: c for c in load_cases(spec.suite(config["suite"]), contract)}
    base = load_results(Path(args.runs_dir) / args.base) if args.base else []
    out = phrasing_sensitivity(load_results(source), cases, base)
    write_json(source / "phrasing_sensitivity.json", {**out, "base_run": args.base})

    def show(r: dict[str, Any]) -> str:
        return f"{r['num']}/{r['den']}" if r["den"] else "—"

    console.rule(f"[bold]措辞不变性[/] {args.run}（{out['bases']} 条主用例，{out['variants']} 个变体）")
    console.print(
        f"变体之间结果不一致：{show(out['variant_outcome_split'])}　越权判定不一致：{show(out['variant_violation_split'])}"
    )
    if args.base:
        console.print(
            f"对照 · 同一措辞重复执行（{args.base}）结果不一致：{show(out['rep_outcome_split'])}　"
            f"越权判定不一致：{show(out['rep_violation_split'])}"
        )
        console.print(f"变体出现了原措辞 k 次都没出现过的结果：{show(out['outside_base'])}")
    table = Table(title="结果不一致的主用例", title_style="bold")
    for col in ("主用例", "变体结果", "原措辞各次结果", "变体违规规则"):
        table.add_column(col)
    for row in out["rows"]:
        if not (row["variant_outcome_split"] or row["outside_base"]):
            continue
        table.add_row(
            row["base"],
            " ".join(Text(v["outcome"], style=OUTCOME_STYLE[v["outcome"]]).markup for v in row["variants"]),
            " ".join(r["outcome"] for r in row["reps"]) or "—",
            "; ".join(",".join(v["rules"]) or "—" for v in row["variants"]),
        )
    console.print(table)
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    """Regression report between two runs of the same suite (PRD §10.7 v1_v2_regression.md)."""
    from consenttrace.core.analysis import CHANGE_NAMES, regression, render_regression_md, run_breakdown

    breakdowns, labels = [], []
    for run in (args.a, args.b):
        source = Path(args.runs_dir) / run
        config = json.loads((source / "config.json").read_text(encoding="utf-8"))
        spec = load_targets(args.targets)[config["target"]]
        contract = load_contract(spec.contract)
        cases = {c.case_id: c for c in load_cases(spec.suite(config["suite"]), contract)}
        breakdowns.append(run_breakdown(source, cases))
        labels.append(str(config.get("agent_version", run)).upper())
    reg = regression(*breakdowns)
    out = Path(args.reports_dir) / f"{args.a}__{args.b}"
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "regression.json", reg)
    md = render_regression_md(reg, a_label=labels[0], b_label=labels[1])
    (out / "regression.md").write_text(md, encoding="utf-8")

    ta, tb = reg["totals"]["a"], reg["totals"]["b"]

    def r(x: dict[str, Any]) -> str:
        return f"{x['num']}/{x['den']}" if x["den"] else "—"

    console.rule(f"[bold]回归对比[/] {labels[0]} {args.a} → {labels[1]} {args.b}")
    table = Table(title_style="bold")
    for col in ("指标", labels[0], labels[1]):
        table.add_column(col)
    for name, key in (
        ("越权（含尝试）", "auth_violation"),
        ("真实写入的越权", "side_effect"),
        ("任务成功", "task_success"),
        ("pass^k", "pass_k"),
    ):
        table.add_row(name, r(ta[key]), r(tb[key]))
    table.add_row("任务保持率", r(reg["task_retention"]["a"]), r(reg["task_retention"]["b"]))
    console.print(table)
    console.print("按用例：" + "，".join(f"{CHANGE_NAMES[k]} {v}" for k, v in reg["changes"].items()))
    changed = Table(title="发生变化的用例", title_style="bold")
    for col in ("用例", "变化", f"{labels[0]} 未通过（写入）", f"{labels[1]} 未通过（写入）", f"{labels[1]} 命中规则"):
        changed.add_column(col)
    for row in reg["rows"]:
        if row["change"] != "unchanged":
            changed.add_row(
                row["case_id"],
                CHANGE_NAMES[row["change"]],
                f"{row['a']['fail']}/{row['a']['reps']}（{row['a']['writes']}）",
                f"{row['b']['fail']}/{row['b']['reps']}（{row['b']['writes']}）",
                ", ".join(row["b"]["rules"]) or "—",
            )
    console.print(changed)
    console.print(f"报告：{out / 'regression.md'}")
    return 0


def cmd_draft_contract(args: argparse.Namespace) -> int:
    """F09: draft a contract from the adapter's own description, score it against the gold contract."""
    import yaml

    from consenttrace.adapters.base import DescribableAdapter
    from consenttrace.ai.contract_drafter import PROMPT_VERSION, Draft, draft_contract, score_structure, verdict_agreement
    from consenttrace.config import LLMSettings
    from consenttrace.llm.client import OpenAICompatClient

    spec = load_targets(args.targets)[args.target]
    version = args.version or spec.versions[0]
    adapter = spec.adapter_class()(lambda: None, version=version)
    if not isinstance(adapter, DescribableAdapter):
        console.print(f"[red]目标 {args.target} 的适配器不支持 describe()，无法起草契约[/]")
        return 2
    desc = adapter.describe()
    gold = load_contract(spec.contract)
    settings = LLMSettings.from_env(args.env, model_var="JUDGE_MODEL")
    if settings is None and not args.from_drafts:
        console.print("[red]起草契约需要 .env 中的 LLM_API_KEY[/]")
        return 2
    if settings is not None and args.model:
        settings = LLMSettings(base_url=settings.base_url, model=args.model, api_key=settings.api_key)
    client = (
        OpenAICompatClient.from_settings(settings, timeout=args.timeout, response_format={"type": "json_object"})
        if settings is not None and not args.from_drafts
        else None
    )
    model_name = settings.model if settings is not None else "?"

    execs = []
    for real in args.on_run or []:
        source = Path(args.runs_dir) / real
        config = json.loads((source / "config.json").read_text(encoding="utf-8"))
        cases = {c.case_id: c for c in load_cases(spec.suite(config["suite"]), gold)}
        execs += [ex for _, _, ex in executions(source, cases, fallback_capabilities=_declared_capabilities(spec))]

    run_id = args.run_id or f"draft-{args.target}-{datetime.now():%m%d%H%M%S}"
    out = Path(args.runs_dir) / "contract_drafts" / run_id
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "description.json", desc.model_dump(mode="json"))
    rows = []
    saved = sorted(Path(args.from_drafts).glob("draft-*.json")) if args.from_drafts else []
    for i in range(1, (len(saved) if args.from_drafts else args.n) + 1):
        if args.from_drafts:  # re-score drafts made earlier; no model call
            old_row = json.loads((Path(args.from_drafts) / f"draft-{i}.json").read_text(encoding="utf-8"))
            yaml_path = Path(args.from_drafts) / f"draft-{i}.yaml"
            d = Draft(
                contract=load_contract(yaml_path) if yaml_path.exists() else None,
                rationale=old_row.get("rationale", {}),
                attempts=old_row.get("attempts", 0),
                errors=old_row.get("errors", []),
                prompt_tokens=old_row.get("usage", {}).get("prompt_tokens", 0),
                completion_tokens=old_row.get("usage", {}).get("completion_tokens", 0),
                raw=old_row.get("raw", []),
                model=old_row.get("model", ""),
            )
        else:
            assert client is not None
            with console.status(f"起草契约 {i}/{args.n}（{model_name}）"):
                d = draft_contract(client, desc)
        row: dict[str, Any] = {
            "draft": i,
            "valid": d.contract is not None,
            "attempts": d.attempts,
            "errors": d.errors,
            "rationale": d.rationale,
            "model": d.model,
            "usage": {"prompt_tokens": d.prompt_tokens, "completion_tokens": d.completion_tokens},
        }
        if d.contract is not None:
            (out / f"draft-{i}.yaml").write_text(
                yaml.safe_dump(d.contract.model_dump(mode="json", exclude_defaults=True), allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            row["structure"] = score_structure(d.contract, gold)
            if execs:
                row["verdicts"] = verdict_agreement(d.contract, gold, execs)
        write_json(out / f"draft-{i}.json", {**row, "raw": d.raw})
        rows.append(row)
    write_json(
        out / "evaluation.json",
        {
            "target": args.target,
            "version": version,
            "model": next((r["model"] for r in rows if r["model"]), model_name),
            "prompt_version": PROMPT_VERSION,
            "gold": str(spec.contract),
            "on_runs": args.on_run or [],
            "drafts": rows,
        },
    )

    def pr(x: dict[str, Any]) -> str:
        return f"P {x['tp']}/{x['tp'] + x['fp']} · R {x['tp']}/{x['tp'] + x['fn']}"

    drafted_by = next((r["model"] for r in rows if r["model"]), model_name)
    table = Table(
        title=f"F09 契约起草：{args.target} {version}（{drafted_by}，与金标准 {Path(spec.contract).name} 比较）",
        title_style="bold",
    )
    for col in ("草稿", "校验", "敏感动作", "参数映射", "规则", "改到金标准", "越权判定一致", "虚假陈述判定一致", "结果一致"):
        table.add_column(col)
    for row in rows:
        if not row["valid"]:
            table.add_row(str(row["draft"]), Text("无效", style="red"), *["—"] * 7)
            continue
        st = row["structure"]
        v = row.get("verdicts")
        table.add_row(
            str(row["draft"]),
            f"{row['attempts']} 轮",
            pr(st["sensitive_actions"]),
            pr(st["args_mapping"]),
            pr(st["rules"]),
            f"{st['edits_to_gold']['total']} 处",
            *(
                f"{v[k]['num']}/{v[k]['den']}" if v else "—"
                for k in ("same_authorization_verdict", "same_claim_verdict", "same_outcome")
            ),
        )
    console.print(table)
    for row in rows:
        if row["valid"]:
            st = row["structure"]["rules"]
            if st["missing"] or st["extra"]:
                console.print(f"  草稿 {row['draft']}：缺少规则 {st['missing'] or '—'}；多出规则 {st['extra'] or '—'}")
    tokens = sum(r["usage"]["prompt_tokens"] for r in rows), sum(r["usage"]["completion_tokens"] for r in rows)
    console.print(f"token：输入 {tokens[0]} / 输出 {tokens[1]}　草稿与评估：{out}")
    return 0 if all(r["valid"] for r in rows) else 1


def cmd_report(args: argparse.Namespace) -> int:
    """Static, offline report of one or more runs (PRD §6.4)."""
    from consenttrace.api.report import ReportError, build_report

    out = Path(args.out) if args.out else Path(args.reports_dir) / args.run[0] / "index.html"
    try:
        path = build_report(args.run, out, targets_path=args.targets, runs_dir=args.runs_dir, analysis=not args.no_analysis)
    except ReportError as exc:
        console.print(f"[red]{exc}[/]")
        return 2
    console.print(f"静态报告：{path}（{path.stat().st_size / 1e6:.1f} MB，单个文件，可直接用浏览器打开）")
    return 0


def cmd_attacks(args: argparse.Namespace) -> int:
    """Adversarial case generation (F10 injection half) and attack success rates."""
    from consenttrace.ai.attack_generator import AttackGenerator, AttackSpec, mount, read_library, write_library
    from consenttrace.core.attacks import attack_report

    spec_path = Path(args.spec or f"configs/{args.target}_attacks.yaml")
    attack_spec = AttackSpec.load(spec_path)
    target = load_targets(args.targets)[args.target]
    contract = load_contract(target.contract)
    base = {c.case_id: c for c in load_cases(target.suite(attack_spec.base_suite), contract)}
    library = Path(args.library or f"benchmarks/{args.target}_injection_library.jsonl")
    suite_out = Path(args.out or f"benchmarks/{args.target}_attacks.jsonl")

    if args.action == "report":
        if not args.run:
            console.print("[red]report 需要 --run[/]")
            return 2
        cases = {c.case_id: c for c in load_cases(suite_out, contract)}
        round2 = suite_out.with_name(suite_out.stem + "_r2.jsonl")
        if round2.exists():
            cases |= {c.case_id: c for c in load_cases(round2, contract)}
        table = Table(title="注入攻击成功率（分母：实际到达注入点的执行）", title_style="bold")
        for col in ("运行", "版本", "样式", "到达", "未到达", "错误", "越权尝试", "真实写入"):
            table.add_column(col)
        for run_id in args.run:
            rep = attack_report(Path(args.runs_dir) / run_id, cases)
            for style, r in [*rep["by_style"].items(), ("合计", rep["totals"])]:
                table.add_row(
                    run_id,
                    rep["version"],
                    attack_spec.styles[style].name if style in attack_spec.styles else style,
                    str(r["reached"]),
                    str(r["not_reached"]),
                    str(r["errors"]),
                    f"{r['attempt']['num']}/{r['attempt']['den']}",
                    f"{r['write']['num']}/{r['write']['den']}",
                )
        console.print(table)
        return 0

    if args.action == "evolve":
        from concurrent.futures import ThreadPoolExecutor

        from consenttrace.ai.attack_generator import evolve_one
        from consenttrace.config import LLMSettings
        from consenttrace.core.attacks import agent_response, attack_facts
        from consenttrace.llm.client import OpenAICompatClient

        if not args.run:
            console.print("[red]evolve 需要 --run（用哪次攻击套件运行里失败的攻击和 Agent 的回应来演化）[/]")
            return 2
        settings = LLMSettings.from_env(args.env, model_var="JUDGE_MODEL")
        if settings is None:
            console.print("[red]演化攻击需要 .env 中的 LLM_API_KEY[/]")
            return 2
        client = OpenAICompatClient.from_settings(settings, timeout=args.timeout, response_format={"type": "json_object"})
        run_dir = Path(args.runs_dir) / args.run[0]
        _, parents = read_library(library)
        cases = {c.case_id: c for c in load_cases(suite_out, contract)}
        failed = {f["case_id"] for f in attack_facts(run_dir, cases) if f["reached"] and not f["attempted"] and not f["error"]}
        todo = [e for e in parents if e["attack_id"] in failed]

        def one(entry: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
            return evolve_one(client, attack_spec, entry, base[entry["carrier"]], agent_response(run_dir, entry["attack_id"]), [])

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(one, todo))
        children = [c for c, _ in results if c is not None]
        out_lib = library.with_name(library.stem + ".r2.jsonl")
        provenance = {
            "target": args.target,
            "spec_id": attack_spec.spec_id,
            "model": settings.model,
            "round": 2,
            "evolved_from_run": args.run[0],
        }
        write_library(out_lib, children, provenance)
        write_json(
            out_lib.with_suffix(".report.json"),
            {**provenance, "parents": len(todo), "accepted": len(children), "logs": [log for _, log in results]},
        )
        out_suite = suite_out.with_name(suite_out.stem + "_r2.jsonl")
        from consenttrace.ai.case_augmenter import write_suite

        write_suite(
            out_suite, [mount(c, base[c["carrier"]], attack_spec) for c in children], {**provenance, "library": str(out_lib)}
        )
        load_cases(out_suite, contract)
        console.print(
            f"第 2 轮：{len(todo)} 条失败的攻击 → {len(children)} 条通过校验的加强版；注入库 {out_lib}，攻击套件 {out_suite}"
        )
        return 0

    if args.action == "generate":
        from consenttrace.config import LLMSettings
        from consenttrace.llm.client import OpenAICompatClient

        settings = LLMSettings.from_env(args.env, model_var="JUDGE_MODEL")
        if settings is None:
            console.print("[red]生成攻击需要 .env 中的 LLM_API_KEY[/]")
            return 2
        if args.model:
            settings = LLMSettings(base_url=settings.base_url, model=args.model, api_key=settings.api_key)
        client = OpenAICompatClient.from_settings(settings, timeout=args.timeout, response_format={"type": "json_object"})
        generator = AttackGenerator(client, attack_spec, n=args.n)
        entries, reports = generator.generate_all(base, workers=args.workers)
        provenance = {"target": args.target, "spec_id": attack_spec.spec_id, "model": settings.model, "per_combo": generator.n}
        write_library(library, entries, provenance)
        write_json(
            library.with_suffix(".report.json"),
            {
                **provenance,
                "combos": [r.__dict__ for r in reports],
                "accepted": len(entries),
                "rejected": sum(len(r.rejected) for r in reports),
            },
        )
        console.print(f"注入库：{library}（{len(entries)} 条通过校验，{sum(len(r.rejected) for r in reports)} 条被拒）")

    _, entries = read_library(library)
    mounted = [mount(e, base[e["carrier"]], attack_spec) for e in entries]
    from consenttrace.ai.case_augmenter import write_suite

    write_suite(suite_out, mounted, {"target": args.target, "spec_id": attack_spec.spec_id, "library": str(library)})
    load_cases(suite_out, contract)  # the frozen suite must load like any other
    console.print(f"攻击套件：{suite_out}（{len(mounted)} 条，载体 {len({e['carrier'] for e in entries})} 个）")
    return 0


def cmd_kb_check(args: argparse.Namespace) -> int:
    """RAG knowledge-base health check: errors, redundancy, conflicts, retrieval quality."""
    from consenttrace.core.kb import run_kb_check

    spec = load_targets(args.targets)[args.target]
    root = Path(args.targets).resolve().parent.parent
    client = None
    if args.llm:
        from consenttrace.config import LLMSettings
        from consenttrace.llm.client import OpenAICompatClient

        settings = LLMSettings.from_env(args.env, model_var="JUDGE_MODEL")
        if settings is None:
            console.print("[red]--llm 需要 .env 中的 LLM_API_KEY[/]")
            return 2
        client = OpenAICompatClient.from_settings(settings, timeout=120, response_format={"type": "json_object"})
    try:
        r = run_kb_check(
            spec, root=root, runs_dir=Path(args.runs_dir), transport=args.via, client=client, regenerate_queries=args.regenerate
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        return 2
    table = Table(title=f"知识库体检：{spec.name}（{r['passages']} 条段落）", title_style="bold")
    for col in ("类型", "规则", "段落", "说明", "LLM 复核"):
        table.add_column(col)
    for i in r["issues"]:
        llm = i.get("llm")
        table.add_row(
            i["kind"],
            i["rule"],
            ", ".join(i["passages"]),
            i["detail"],
            "" if not llm else ("确认冲突" if llm["conflict"] else "不构成冲突") + f"：{llm['reason']}",
        )
    console.print(table if r["issues"] else "[green]没有发现结构错误、冗余或冲突候选[/]")
    rq = r["retrieval"]
    if rq:
        k = rq["k"]
        console.print(
            f"检索质量（{rq['queries']} 题，Agent 自己的检索器）：Recall@1 {rq['recall_at_1']['num']}/{rq['queries']}，"
            f"Recall@{k} {rq[f'recall_at_{k}']['num']}/{rq['queries']}，MRR {rq['mrr']}"
        )
    s = r["seeded"]
    console.print(f"检查器自检：植入 {s['planted']} 个已知故障，检出 {s['detected']} 个；新增误报 {len(s['false_alarms'])} 个")
    p = r["poisoning"]
    console.print(
        f"投毒段落：{p['passages']} 条（来自本目标用例集的检索投毒），规则判为与现有条款冲突 {p['flagged']} 条"
        + (f"，LLM 判为冲突 {p['llm_flagged']} 条" if p.get("llm_flagged") is not None else "")
    )
    if r.get("llm_review"):
        confirmed = [x for x in r["llm_review"]["pairs"] if x["conflict"]]
        console.print(
            f"LLM 复核（{r['llm_review']['model']}）：审查 {len(r['llm_review']['pairs'])} 对条款，判为冲突 {len(confirmed)} 对"
        )
    console.print(f"报告：{r['path']}/report.json")
    return 0


def cmd_annotate(args: argparse.Namespace) -> int:
    """Blind human annotation: draw the sample, or score every oracle against the labels."""
    from consenttrace.core.annotation import SAMPLE, sample, score, write_sample

    folder = Path(args.targets).resolve().parent.parent / "benchmarks" / "labels"
    targets = load_targets(args.targets)
    if args.action == "sample":
        if (folder / SAMPLE).exists() and not args.force:
            console.print(f"[red]{folder / SAMPLE} 已存在；样本冻结后不应重抽（确需重抽用 --force）[/]")
            return 2
        header, items = sample(Path(args.runs_dir), targets, n=args.n, seed=args.seed)
        path = write_sample(folder, header, items)
        console.print(f"标注样本：{path}（{header['n']} 条；分层 {header['strata']}；可选池 {header['pool']}）")
        console.print("打开控制台「盲标」页开始标注；分层信息不会显示给标注者。")
        return 0

    def suite_cases(spec: Any, suite: str) -> dict[str, Any]:
        try:
            return {c.case_id: c for c in load_suite(spec, suite)}
        except (LoadError, ValueError):
            return {}

    r = score(Path(args.runs_dir), targets, suite_cases, folder, annotator=args.annotator)
    console.print(
        f"已标注 {r['labeled']}/{r['sample']}（标注者 {', '.join(r['annotators']) or '无'}；以 {r['primary']} 为准；人工判为越权 {r['human_positives']} 条）"
    )
    table = Table(title="各判定方法 vs 人工盲标", title_style="bold")
    for col in ("方法", "越权召回", "越权误报率", "真实写入召回", "Cohen's κ", "首个违规步骤一致"):
        table.add_column(col)
    for o in r["oracles"].values():
        v, w = o["violation"], o["side_effect"]
        table.add_row(
            o["label"],
            f"{v['tp']}/{v['tp'] + v['fn']}",
            f"{v['fp']}/{v['fp'] + v['tn']}",
            f"{w['tp']}/{w['tp'] + w['fn']}",
            str(o["kappa"]),
            f"{o['first_step']['num']}/{o['first_step']['den']}",
        )
    console.print(table)
    if r["inter_annotator"]:
        ia = r["inter_annotator"]
        console.print(f"标注者一致性：{ia['annotators']} 共同 {ia['items']} 条，κ={ia['kappa']}")
    return 0


def _agent_table(statuses: list[AgentStatus]) -> Table:
    table = Table(title="被测 Agent（独立进程，经 Agent 协议接入）", title_style="bold")
    for col in ("目标", "地址", "状态", "版本", "能力", "模型"):
        table.add_column(col)
    for st in statuses:
        info = st.info or {}
        caps = info.get("capabilities") or {}
        llm = info.get("llm") or {}
        table.add_row(
            st.name,
            st.url or "—",
            "[green]在线[/]" if st.online else f"[red]离线[/] {st.error or ''}",
            ", ".join(info.get("versions", [])),
            ", ".join(k for k in ("output", "trace", "state", "inject_tool_response", "visible_reasoning") if caps.get(k)),
            (llm.get("model") or "未配置 Key（仅回放）") if st.online else "",
        )
    return table


def cmd_agents(args: argparse.Namespace) -> int:
    targets = load_targets(args.targets)
    root = Path(args.targets).resolve().parent.parent
    procs = AgentProcesses(root, log_dir=Path(args.runs_dir) / "_agent_logs")
    chosen = [targets[n] for n in args.name] if args.name else [t for t in targets.values() if t.service_url]
    if args.start:
        statuses = [procs.start(spec) for spec in chosen]
        console.print(_agent_table(statuses))
        if any(st.managed for st in statuses):
            console.print("Agent 进程由本命令启动，按 Ctrl+C 结束。")
            try:
                while True:
                    time.sleep(3600)
            except KeyboardInterrupt:
                procs.stop_all()
        return 0 if all(st.online for st in statuses) else 2
    statuses = [procs.status(spec) for spec in chosen]
    console.print(_agent_table(statuses))
    return 0 if all(st.online for st in statuses) else 2


def cmd_probe(args: argparse.Namespace) -> int:
    url = args.url
    if url is None:
        spec = load_targets(args.targets).get(args.target or "")
        if spec is None or not spec.service_url:
            console.print("[red]用 --url 指定地址，或用 --target 指定一个配置了 service.url 的目标[/]")
            return 2
        url = spec.service_url
    report = probe_agent(url, version=args.version)
    table = Table(title=f"接入检查 {url}", title_style="bold")
    for col in ("检查项", "结果", "说明"):
        table.add_column(col)
    style = {"PASS": "green", "FAIL": "red", "SKIP": "bright_black"}
    for check in report.checks:
        table.add_row(check.title, f"[{style[check.status]}]{check.status}[/]", check.detail)
    console.print(table)
    if args.json:
        write_json(Path(args.json), report.to_dict())
    return 0 if report.ok else 1


def cmd_serve(args: argparse.Namespace) -> int:  # pragma: no cover - blocks on a server
    import uvicorn

    from consenttrace.api.app import create_app

    root = Path(args.targets).resolve().parent.parent
    procs = AgentProcesses(root, log_dir=Path(args.runs_dir) / "_agent_logs")
    if not args.no_agents:
        targets = load_targets(args.targets)
        statuses = [procs.start(spec) for spec in targets.values() if spec.service_url and spec.launch]
        console.print(_agent_table(statuses))
    app = create_app(targets_path=args.targets, runs_dir=args.runs_dir, env_file=args.env, agent_processes=procs)
    console.print(f"ConsentTrace 控制台：[underline]http://{args.host}:{args.port}[/]")
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    finally:
        procs.stop_all()
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
    run.add_argument(
        "--via",
        choices=["inprocess", "http"],
        default="inprocess",
        help="接入方式：http = 被测 Agent 是独立进程，只通过 Agent 协议访问；inprocess = 同进程加载（开发与测试）",
    )

    atk = sub.add_parser("attacks", help="F10：对抗用例生成（间接注入库）与注入攻击成功率")
    atk.add_argument("action", choices=["generate", "mount", "evolve", "report"])
    atk.add_argument("--target", default="travel")
    atk.add_argument("--spec", help="攻击规格（默认 configs/<target>_attacks.yaml）")
    atk.add_argument("--library", help="注入库（默认 benchmarks/<target>_injection_library.jsonl）")
    atk.add_argument("--out", help="攻击套件（默认 benchmarks/<target>_attacks.jsonl）")
    atk.add_argument("-n", type=int, help="每个样式 × 目标组合生成几条")
    atk.add_argument("--model", help="生成用的模型（默认 JUDGE_MODEL）")
    atk.add_argument("--workers", type=int, default=4)
    atk.add_argument("--timeout", type=float, default=120.0)
    atk.add_argument("--run", action="append", help="report：要统计的攻击套件运行（可重复）；evolve：从这次运行里失败的攻击演化")
    atk.add_argument("--env", default=".env")

    kb = sub.add_parser("kb-check", help="RAG 知识库体检：结构错误、冗余、冲突、检索质量（含检查器自检与投毒检测）")
    kb.add_argument("--target", default="travel")
    kb.add_argument("--via", choices=["inprocess", "http"], default="inprocess", help="从哪里读取知识库与检索器")
    kb.add_argument("--llm", action="store_true", help="用 JUDGE_MODEL 复核冲突候选（没有冻结的测试题时也用它生成）")
    kb.add_argument("--regenerate", action="store_true", help="重新生成并冻结检索测试题")
    kb.add_argument("--env", default=".env")

    an = sub.add_parser("annotate", help="人工盲标：抽取样本，或用人工标签为各判定方法评分")
    an.add_argument("action", choices=["sample", "score"])
    an.add_argument("--n", type=int, default=120)
    an.add_argument("--seed", type=int, default=0)
    an.add_argument("--force", action="store_true", help="覆盖已冻结的样本")
    an.add_argument("--annotator", help="score：以哪位标注者为准（默认标注最多的一位）")

    ag = sub.add_parser("agents", help="列出独立进程的被测 Agent 及其在线状态与能力声明")
    ag.add_argument("name", nargs="*", help="只看这些目标")
    ag.add_argument("--start", action="store_true", help="启动本机管理的 Agent 进程（按 Ctrl+C 结束）")

    pr = sub.add_parser("probe", help="接入检查：一个 Agent 协议地址是否真的提供它声明的能力（不调用模型）")
    pr.add_argument("--url", help="Agent 地址，如 http://127.0.0.1:9101")
    pr.add_argument("--target", help="或者用注册表里的目标")
    pr.add_argument("--version")
    pr.add_argument("--json", help="同时把检查结果写成 JSON")

    show = sub.add_parser("show", help="查看运行结果或某个用例的审计时间轴")
    show.add_argument("--run", required=True)
    show.add_argument("--case")
    show.add_argument("--rep", type=int, default=0)
    show.add_argument("-v", "--verbose", action="store_true", help="同时显示每次模型调用")

    sub.add_parser("runs", help="列出运行记录")

    reeval = sub.add_parser("reevaluate", help="用当前契约与用例重新判定一次已完成的运行（不调用模型）")
    reeval.add_argument("--run", required=True)
    reeval.add_argument("--as", dest="as_run", help="新运行的 run_id")

    det = sub.add_parser("detectors", help="在带标注的缺陷语料上评估各判定方法（含对照组与消融）")
    det.add_argument("--corpus", default="benchmarks/travel_defects.py")
    det.add_argument("--on-run", action="append", help="同时在一次真实运行上比较各判定方法（可重复）")
    det.add_argument("--run-id")
    det.add_argument("--reports-dir", default="reports")
    det.add_argument("--llm-judge", action="store_true", help="加入 LLM 裁判对照组 C1 / C2（调用 JUDGE_MODEL，结果缓存）")
    det.add_argument("--judge-samples", type=int, default=2, help="同一输入的裁判次数，用于自一致性（默认 2）")
    det.add_argument("--judge-workers", type=int, default=6)
    det.add_argument("--judge-cache", help="裁判缓存文件（默认 <runs-dir>/judge_cache/<模型>.jsonl）")
    det.add_argument("--timeout", type=float, default=120.0)
    det.add_argument("--env", default=".env")

    aug = sub.add_parser("augment", help="F10：用 LLM 生成用例的措辞变体，确定性校验后冻结")
    aug.add_argument("--target", required=True)
    aug.add_argument("--suite", default="main")
    aug.add_argument("--spec", help="变体约束（默认 configs/<target>_variants.yaml）")
    aug.add_argument("--out", help="输出（默认 benchmarks/<target>_variants.jsonl）")
    aug.add_argument("-n", type=int, default=3, help="每条用例的变体数")
    aug.add_argument("--case", action="append", help="只处理指定用例（可重复，支持前缀）")
    aug.add_argument("--model", help="生成用的模型（默认取 JUDGE_MODEL）")
    aug.add_argument("--workers", type=int, default=4)
    aug.add_argument("--max-attempts", type=int, default=3)
    aug.add_argument("--timeout", type=float, default=180.0)
    aug.add_argument("--env", default=".env")

    phr = sub.add_parser("phrasing", help="F10：措辞不变性分析（变体之间 vs 原措辞重复执行）")
    phr.add_argument("--run", required=True, help="变体套件的运行")
    phr.add_argument("--base", help="同一版本在原用例集上的运行（k≥2，作为采样噪声对照）")

    cmp_ = sub.add_parser("compare", help="两次运行的逐用例回归对比，生成 Markdown 报告")
    cmp_.add_argument("--a", required=True, help="基线运行（如 V2）")
    cmp_.add_argument("--b", required=True, help="对比运行（如 V2.1）")
    cmp_.add_argument("--reports-dir", default="reports")

    dc = sub.add_parser("draft-contract", help="F09：由 AI 根据被测 Agent 的工具定义起草测试契约，并与金标准比较")
    dc.add_argument("--target", required=True)
    dc.add_argument("--version", help="描述哪个版本的 Agent（默认注册表中的第一个）")
    dc.add_argument("-n", type=int, default=1, help="起草次数（衡量稳定性）")
    dc.add_argument("--on-run", action="append", help="在这次运行的轨迹上比较草稿与金标准的判定（可重复）")
    dc.add_argument("--run-id")
    dc.add_argument("--from-drafts", help="重新评分一个已有草稿目录（不调用模型）")
    dc.add_argument("--model")
    dc.add_argument("--timeout", type=float, default=300.0)
    dc.add_argument("--env", default=".env")

    rep = sub.add_parser("report", help="生成离线静态报告（单个 HTML，内嵌运行数据与前端）")
    rep.add_argument("--run", action="append", required=True, help="要包含的运行（可重复）")
    rep.add_argument("--out", help="输出文件（默认 reports/<第一个运行>/index.html）")
    rep.add_argument("--reports-dir", default="reports")
    rep.add_argument("--no-analysis", action="store_true", help="不包含实验分析页")
    rep.add_argument("--html", action="store_true", help="（默认即为 HTML，兼容 PRD 中的写法）")

    serve = sub.add_parser("serve", help="启动 Web 控制台（FastAPI + 前端）")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--env", default=".env")
    serve.add_argument("--no-agents", action="store_true", help="不自动启动本机管理的被测 Agent 进程")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {
        "validate": cmd_validate,
        "run": cmd_run,
        "show": cmd_show,
        "runs": cmd_runs,
        "serve": cmd_serve,
        "agents": cmd_agents,
        "attacks": cmd_attacks,
        "kb-check": cmd_kb_check,
        "annotate": cmd_annotate,
        "probe": cmd_probe,
        "reevaluate": cmd_reevaluate,
        "detectors": cmd_detectors,
        "augment": cmd_augment,
        "phrasing": cmd_phrasing,
        "compare": cmd_compare,
        "draft-contract": cmd_draft_contract,
        "report": cmd_report,
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

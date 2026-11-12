"""ConsentTrace command line: validate, run, show, runs, reevaluate, detectors, serve."""

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
        "detectors": cmd_detectors,
        "augment": cmd_augment,
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

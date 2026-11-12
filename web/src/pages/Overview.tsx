import { useMemo, useState } from "react";
import { Heatmap, OutcomeBar } from "../components/charts";
import { Card, ErrorNote, Loading, Pill, Segmented, StatTile } from "../components/ui";
import { api, type RunSummary, type Summ } from "../lib/api";
import { CATEGORY_NAMES, compact, href, useAsync, versionColor } from "../lib/util";

export type Metric = "auth_violation" | "side_effect" | "task_success" | "pass_k" | "attack_success";
export const METRICS: { value: Metric; label: string; goodWhenHigh: boolean }[] = [
  { value: "auth_violation", label: "越权率", goodWhenHigh: false },
  { value: "side_effect", label: "真实写入越权率", goodWhenHigh: false },
  { value: "attack_success", label: "注入攻击成功率", goodWhenHigh: false },
  { value: "task_success", label: "任务成功率", goodWhenHigh: true },
  { value: "pass_k", label: "pass^k", goodWhenHigh: true },
];

export function latestPerVersion(runs: RunSummary[], suite: string): RunSummary[] {
  const best = new Map<string, RunSummary>();
  for (const r of runs) {
    if (r.status && r.status !== "done") continue;
    if (r.suite !== suite) continue;
    const prev = best.get(r.agent_version);
    if (!prev || r.finished_at > prev.finished_at) best.set(r.agent_version, r);
  }
  return [...best.values()].sort((a, b) => a.agent_version.localeCompare(b.agent_version));
}

export function Overview() {
  const runs = useAsync(() => api.runs(), []);
  const chosen = useMemo(() => latestPerVersion(runs.data ?? [], "main"), [runs.data]);
  const breakdowns = useAsync(() => Promise.all(chosen.map((r) => api.run(r.run_id))), [chosen.map((r) => r.run_id).join(",")]);

  if (runs.error) return <ErrorNote error={runs.error} />;
  if (!runs.data) return <Loading what="运行记录" />;
  const done = runs.data.filter((r) => !r.status || r.status === "done").sort((x, y) => (y.finished_at ?? "").localeCompare(x.finished_at ?? ""));
  const original = (r: RunSummary) => r.mode === "live" && !r.config?.reevaluated_from;
  const liveRuns = done.filter(original);
  const totalExec = done.reduce((n, r) => n + (r.executions ?? 0), 0);
  const liveExec = liveRuns.reduce((n, r) => n + (r.executions ?? 0), 0);
  const llmCalls = liveRuns.reduce((n, r) => n + (r.llm_calls ?? 0), 0);
  const bds = breakdowns.data ?? [];

  return (
    <div className="space-y-5">
      <section className="card relative overflow-hidden p-6">
        <div className="max-w-3xl">
          <h1 className="text-2xl font-semibold text-ink">授权链路审计</h1>
          <p className="mt-2 text-sm leading-relaxed text-ink-2">
            ConsentTrace 以可信用户事件驱动独立的授权账本，在每一次敏感工具调用发生的那一刻核验授权是否有效，再用 SQLite 前后状态差分和写入回执核实副作用。下表的每个数字都来自 runs/ 下的原始证据，并标注样本量。
          </p>
        </div>
      </section>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile label="运行记录" value={done.length} sub={`Live ${liveRuns.length} · 回放 ${done.filter((r) => r.mode === "replay").length} · 重新判定 ${done.filter((r) => r.config?.reevaluated_from).length}`} />
        <StatTile label="真实模型执行" value={compact(liveExec)} sub={`另有 ${compact(totalExec - liveExec)} 次为回放或重新判定（不调用模型）`} accent="var(--s1)" />
        <StatTile label="真实模型调用" value={compact(llmCalls)} sub="Live 运行中的 LLM 请求数" />
        <StatTile
          label="最新一组运行的真实写入越权"
          value={bds.map((b) => `${b.totals.side_effect.num}`).join(" → ") || "—"}
          sub={chosen.map((r) => r.agent_version.toUpperCase()).join(" → ")}
          accent="var(--critical)"
        />
      </div>

      <RiskHeatmap runs={runs.data} />

      <Card title="运行记录" subtitle="点击进入运行详情">
        <RunsTable runs={done} />
      </Card>
    </div>
  );
}

export function metricOf(s: Summ | undefined, metric: Metric) {
  if (!s) return null;
  return s[metric];
}

/** Risk category × agent version, latest run of each version on one suite (experiment evidence). */
export function RiskHeatmap({ runs }: { runs: RunSummary[] }) {
  const [suite, setSuite] = useState("main");
  const [metric, setMetric] = useState<Metric>("auth_violation");
  const chosen = useMemo(() => latestPerVersion(runs.filter((r) => r.target === "travel" && r.mode === "live"), suite), [runs, suite]);
  const breakdowns = useAsync(() => Promise.all(chosen.map((r) => api.run(r.run_id))), [chosen.map((r) => r.run_id).join(",")]);
  const bds = breakdowns.data ?? [];
  return (
      <Card
        title="风险类别 × 被测 Agent 版本"
        subtitle={`被测对象：差旅 Agent 的三个版本；每个版本取套件 ${suite} 下最近一次运行；单元格显示比例与分子/分母`}
        right={
          <div className="flex flex-wrap gap-2">
            <Segmented label="套件" value={suite} onChange={setSuite} options={[{ value: "main", label: "主套件 48" }, { value: "smoke", label: "冒烟 9" }]} />
            <Segmented label="指标" value={metric} onChange={setMetric} options={METRICS.map((m) => ({ value: m.value, label: m.label }))} />
          </div>
        }
      >
        {breakdowns.error && <ErrorNote error={breakdowns.error} />}
        {chosen.length === 0 ? (
          <p className="text-sm text-muted">该套件还没有运行记录。</p>
        ) : !breakdowns.data ? (
          <Loading />
        ) : (
          <Heatmap
            rows={Object.keys(CATEGORY_NAMES)
              .filter((c) => bds.some((b) => b.categories[c]))
              .map((c) => ({ key: c, label: CATEGORY_NAMES[c] }))}
            cols={bds.map((b) => ({ key: b.run_id, label: `Agent ${b.summary?.agent_version ?? ""}`, sub: b.run_id, swatch: versionColor(b.summary?.agent_version ?? "") }))}
            cell={(row, col) => metricOf(bds.find((b) => b.run_id === col)?.categories[row], metric)}
            metricLabel={METRICS.find((m) => m.value === metric)!.label}
            goodWhenHigh={METRICS.find((m) => m.value === metric)!.goodWhenHigh}
            onCellClick={(_row, col) => (window.location.hash = href("runs", col))}
          />
        )}
      </Card>

  );
}

export function RunsTable({ runs }: { runs: RunSummary[] }) {
  return (
    <div className="scroll-x">
      <table className="w-full text-left text-xs">
        <thead>
          <tr className="hairline-b text-muted">
            {["运行", "被测 Agent", "模式", "接入", "模型", "套件", "执行", "结果分布", "tokens", "完成时间"].map((h) => (
              <th key={h} className="px-2 py-2 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.run_id} className="hairline-b align-middle">
              <td className="px-2 py-2">
                <a href={href("runs", r.run_id)} className="mono font-medium text-s1 hover:underline">
                  {r.run_id}
                </a>
                {typeof r.config?.reevaluated_from === "string" && <div className="text-[11px] text-muted">重新判定自 {r.config.reevaluated_from}</div>}
              </td>
              <td className="px-2 py-2">
                <Pill color={versionColor(r.agent_version)}>{r.target} {r.agent_version}</Pill>
              </td>
              <td className="px-2 py-2 text-ink-2">{r.mode}</td>
              <td className="px-2 py-2 text-ink-2">{r.config?.transport === "http" ? "独立进程" : "同进程"}</td>
              <td className="px-2 py-2 text-ink-2">{r.model_id ?? "—"}</td>
              <td className="px-2 py-2 text-ink-2">{r.suite} × {r.reps}</td>
              <td className="tabular px-2 py-2 text-ink">{r.executions}</td>
              <td className="w-56 px-2 py-2">
                <OutcomeBar counts={r.counts} total={r.executions} compact />
              </td>
              <td className="tabular px-2 py-2 text-ink-2">{compact((r.usage?.prompt_tokens ?? 0) + (r.usage?.completion_tokens ?? 0))}</td>
              <td className="tabular px-2 py-2 text-muted">{r.finished_at?.slice(0, 16).replace("T", " ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

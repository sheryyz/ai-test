import { useMemo, useState } from "react";
import { Heatmap } from "../components/charts";
import { GRADE_META, GradeBadge, MethodNote } from "../components/Scorecard";
import { Card, ErrorNote, Loading, PageHeader, Segmented, tipHandlers, useTooltip } from "../components/ui";
import { api, type ScoreGroup, type SyncedArm } from "../lib/api";
import { compact, href, planName, useAsync } from "../lib/util";

const SCENARIOS: { key: string; target: string; suite: string; label: string }[] = [
  { key: "travel-main", target: "travel", suite: "main", label: "差旅 · 完整测试" },
  { key: "tau-core", target: "tau-airline", suite: "core", label: "τ-bench 航空 · 完整测试" },
  { key: "approval-core", target: "approval", suite: "core", label: "审批 · 完整测试" },
  { key: "travel-jailbreaks", target: "travel", suite: "jailbreaks", label: "差旅 · 越狱" },
  { key: "tau-jailbreaks", target: "tau-airline", suite: "jailbreaks", label: "τ-bench · 越狱" },
  { key: "travel-boundary", target: "travel", suite: "boundary", label: "差旅 · 边界" },
  { key: "tau-boundary", target: "tau-airline", suite: "boundary", label: "τ-bench · 边界" },
];
const CAUSES = ["overridden", "belief_error", "knowing_violation", "request_as_consent", "unclassified", "no_reasoning"];

export function Bench() {
  const data = useAsync(() => api.scorecards(), []);
  const synced = useAsync(() => api.syncedAttacks(), []);
  const [scenario, setScenario] = useState("travel-main");
  const groups = useMemo(() => (data.data?.groups ?? []).filter((g) => g.bench), [data.data]);
  if (data.error) return <ErrorNote error={data.error} />;
  if (!data.data) return <Loading what="模型横评" />;
  const order = data.data.models.map((m) => m.model);
  const sorted = (gs: ScoreGroup[]) => [...gs].sort((a, b) => order.indexOf(a.model ?? "") - order.indexOf(b.model ?? ""));
  const sc = SCENARIOS.find((s) => s.key === scenario)!;
  const rows = sorted(groups.filter((g) => g.target === sc.target && g.suite === sc.suite));
  const missing = data.data.models.filter((m) => m.name !== "qwen3.8-max" && !rows.some((g) => g.model === m.model));
  const dims = (rows[0]?.dimensions ?? []).filter((d) => rows.some((g) => (g.dimensions.find((x) => x.key === d.key)?.den ?? 0) > 0));

  return (
    <div className="space-y-6">
      <PageHeader title="模型横评">
        同一份 Agent 代码（差旅 V1、τ-bench 航空 v1、审批 v1）分别部署在不同的大模型上，跑同一批场景。每个部署都是独立进程、用自己的模型 Key；这些结果用于比较模型，不计入「问题与复测」里已注册 Agent 的问题。
      </PageHeader>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card title="越狱成功率（越低越好）" subtitle="用户用越狱话术诱导跳过确认后，Agent 真的执行了敏感操作的比例；线段为 95% 置信区间">
          <JailbreakBars groups={sorted(groups.filter((g) => g.suite === "jailbreaks"))} />
        </Card>
        <Card title="授权时序注入：时机的影响" subtitle="同一段注入文本，在授权刚失效的那一轮注入 vs 在第一轮注入；只统计注入真正到达 Agent 的执行">
          {synced.data ? <Dumbbell rows={synced.data} /> : <Loading />}
        </Card>
      </div>

      <Card
        title="可靠性评分卡（按模型）"
        subtitle="每格为该维度的达标比例；悬停查看分子分母"
        right={<Segmented label="场景" value={scenario} onChange={setScenario} options={SCENARIOS.filter((s) => groups.some((g) => g.target === s.target && g.suite === s.suite)).map((s) => ({ value: s.key, label: s.label }))} />}
      >
        {rows.length === 0 ? (
          <p className="text-sm text-muted">这个场景还没有横评数据。</p>
        ) : (
          <div className="space-y-5">
            <Heatmap
              rows={rows.map((g) => ({ key: g.model ?? "?", label: g.provider ?? "", sub: `${g.executions} 次执行` }))}
              cols={dims.map((d) => ({ key: d.key, label: d.label }))}
              cell={(model, dim) => {
                const d = rows.find((g) => g.model === model)?.dimensions.find((x) => x.key === dim);
                return d && d.den ? { num: d.num, den: d.den, rate: d.rate } : null;
              }}
              metricLabel="达标比例"
              goodWhenHigh
            />
            <div className="scroll-x">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="hairline-b text-muted">
                    {["模型", "整体评级", "最弱的一项", "各维度评级", "tokens / 次", "平均耗时", "报告"].map((h) => (
                      <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((g) => {
                    const weak = g.dimensions.find((d) => d.key === g.weakest);
                    return (
                      <tr key={g.run_id} className="hairline-b">
                        <td className="whitespace-nowrap px-2 py-2 font-medium text-ink">
                          {g.model} <span className="font-normal text-muted">{g.provider}</span>
                        </td>
                        <td className="px-2 py-2">
                          <GradeBadge grade={g.overall} size="sm" />
                        </td>
                        <td className="whitespace-nowrap px-2 py-2 text-ink-2">{weak ? `${weak.label} ${weak.num}/${weak.den}` : "—"}</td>
                        <td className="px-2 py-2">
                          <span className="flex gap-1">
                            {g.dimensions
                              .filter((d) => d.den)
                              .map((d) => (
                                <span key={d.key} title={`${d.label} ${d.num}/${d.den}`} className="grid size-5 place-items-center rounded text-[10px] font-bold text-white" style={{ background: d.grade ? GRADE_META[d.grade].color : "var(--muted)" }}>
                                  {d.grade ?? "·"}
                                </span>
                              ))}
                          </span>
                        </td>
                        <td className="tabular px-2 py-2 text-ink-2">{compact(Math.round(g.tokens / Math.max(1, g.executions)))}</td>
                        <td className="tabular px-2 py-2 text-ink-2">{g.avg_duration_ms ? `${(g.avg_duration_ms / 1000).toFixed(1)} 秒` : "—"}</td>
                        <td className="px-2 py-2">
                          <a className="text-s1 hover:underline" href={href("runs", g.run_id)}>
                            查看 →
                          </a>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {missing.length > 0 && <p className="text-[11px] text-muted">没有这一组数据的模型：{missing.map((m) => m.name).join("、")}（未运行或模型额度不足）。</p>}
            <MethodNote method={data.data.method} />
          </div>
        )}
      </Card>

      {rows.some((g) => g.reasoning.attempts > 0) && (
        <Card title="思维链路诊断：越权之前模型在想什么" subtitle={`${planName(sc.suite)}中每一次越权调用，按同一轮里调用之前的可见推理归因（只是信号，不参与判定）`}>
          <div className="scroll-x">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="hairline-b text-muted">
                  <th className="px-2 py-2 font-medium">模型</th>
                  <th className="px-2 py-2 font-medium">越权调用</th>
                  {CAUSES.map((c) => (
                    <th key={c} className="whitespace-nowrap px-2 py-2 font-medium">
                      {data.data!.reasoning_legend.find((l) => l.key === c)?.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows
                  .filter((g) => g.reasoning.attempts > 0)
                  .map((g) => (
                    <tr key={g.run_id} className="hairline-b">
                      <td className="whitespace-nowrap px-2 py-2 font-medium text-ink">{g.model}</td>
                      <td className="tabular px-2 py-2 text-ink">{g.reasoning.attempts}</td>
                      {CAUSES.map((c) => (
                        <td key={c} className="tabular px-2 py-2 text-ink-2">
                          {g.reasoning.by_cause[c] || <span className="text-muted">0</span>}
                        </td>
                      ))}
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          <ul className="mt-3 grid gap-1 text-[11px] text-muted sm:grid-cols-2">
            {data.data.reasoning_legend.map((l) => (
              <li key={l.key}>
                <b className="text-ink-2">{l.label}</b>：{l.means}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

function JailbreakBars({ groups }: { groups: ScoreGroup[] }) {
  const tip = useTooltip();
  if (!groups.length) return <p className="text-sm text-muted">还没有越狱横评数据。</p>;
  const targets = [...new Set(groups.map((g) => g.target))];
  return (
    <div className="space-y-4">
      {targets.map((t) => (
        <div key={t}>
          <div className="mb-1.5 text-xs font-semibold text-ink">{t === "travel" ? "差旅 Agent（中文话术）" : "τ-bench 航空 Agent（英文话术）"}</div>
          <div className="space-y-1.5">
            {groups
              .filter((g) => g.target === t)
              .map((g) => {
                const c = g.dimensions.find((d) => d.key === "consent")!;
                const bad = c.den - c.num;
                const rate = c.den ? bad / c.den : 0;
                const ci = c.ci ? [1 - c.ci[1], 1 - c.ci[0]] : null;
                return (
                  <div key={g.run_id} className="grid grid-cols-[110px_minmax(0,1fr)_88px] items-center gap-3">
                    <span className="truncate text-xs text-ink-2">{g.model}</span>
                    <span
                      tabIndex={0}
                      className="relative h-3 rounded-[4px]"
                      style={{ background: "var(--surface-3)" }}
                      {...tipHandlers(tip, () => (
                        <div>
                          <b>{g.model}</b>：{bad}/{c.den} 次执行被越狱成功（{(rate * 100).toFixed(1)}%）
                          {ci && <div className="text-muted">95% 置信区间 {(ci[0] * 100).toFixed(1)}% – {(ci[1] * 100).toFixed(1)}%</div>}
                        </div>
                      ))}
                    >
                      <span className="absolute inset-y-0 left-0 rounded-[4px]" style={{ width: `${rate * 100}%`, minWidth: bad ? 3 : 0, background: "var(--seq-500)" }} />
                      {ci && <span aria-hidden className="absolute top-1/2 h-[2px] -translate-y-1/2" style={{ left: `${ci[0] * 100}%`, width: `${Math.max(0.6, (ci[1] - ci[0]) * 100)}%`, background: "var(--ink)" }} />}
                    </span>
                    <span className="tabular text-xs text-ink">
                      <b>{(rate * 100).toFixed(0)}%</b> <span className="text-muted">{bad}/{c.den}</span>
                    </span>
                  </div>
                );
              })}
          </div>
        </div>
      ))}
    </div>
  );
}

function Dumbbell({ rows }: { rows: { run_id: string; model: string | null; arms: Record<string, SyncedArm> }[] }) {
  const tip = useTooltip();
  if (!rows.length) return <p className="text-sm text-muted">还没有授权时序注入的运行。</p>;
  const rate = (a?: SyncedArm) => (a && a.reached ? a.violations / a.reached : null);
  return (
    <div>
      <div className="mb-3 flex items-center gap-4 text-[11px] text-ink-2">
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden className="size-2.5 rounded-full border-2" style={{ borderColor: "var(--s1)", background: "var(--surface)" }} />
          第一轮注入（对照）
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden className="size-2.5 rounded-full" style={{ background: "var(--s2)" }} />
          授权刚失效的那一轮注入
        </span>
      </div>
      <div className="space-y-3">
        {rows.map((r) => {
          const early = rate(r.arms.early);
          const syn = rate(r.arms.synced);
          const reached = (r.arms.early?.reached ?? 0) + (r.arms.synced?.reached ?? 0);
          return (
            <div key={r.run_id} className="grid grid-cols-[110px_minmax(0,1fr)_120px] items-center gap-3">
              <span className="truncate text-xs text-ink-2">{r.model}</span>
              {reached === 0 ? (
                <span className="text-[11px] text-muted">注入没有到达（这个模型在那几轮没有调用只读工具），不计算成功率</span>
              ) : (
                <span
                  tabIndex={0}
                  className="relative h-4"
                  {...tipHandlers(tip, () => (
                    <div>
                      <div>第一轮注入：{r.arms.early?.violations}/{r.arms.early?.reached} 次越权</div>
                      <div>授权刚失效时注入：{r.arms.synced?.violations}/{r.arms.synced?.reached} 次越权</div>
                    </div>
                  ))}
                >
                  <span aria-hidden className="absolute inset-x-0 top-1/2 h-px" style={{ background: "var(--grid)" }} />
                  {early !== null && syn !== null && (
                    <span aria-hidden className="absolute top-1/2 h-[2px] -translate-y-1/2" style={{ left: `${Math.min(early, syn) * 100}%`, width: `${Math.abs(syn - early) * 100}%`, background: "var(--axis)" }} />
                  )}
                  {early !== null && (
                    <span aria-hidden className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2" style={{ left: `${early * 100}%`, borderColor: "var(--s1)", background: "var(--surface)" }} />
                  )}
                  {syn !== null && (
                    <span aria-hidden className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-[var(--surface)]" style={{ left: `${syn * 100}%`, background: "var(--s2)" }} />
                  )}
                </span>
              )}
              <span className="tabular text-xs text-ink-2">
                {reached ? (
                  <>
                    {early !== null ? `${Math.round(early * 100)}%` : "—"} → <b className="text-ink">{syn !== null ? `${Math.round(syn * 100)}%` : "—"}</b>
                  </>
                ) : (
                  "—"
                )}
              </span>
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex justify-between pl-[122px] pr-[132px] text-[10px] text-muted">
        <span>0%</span>
        <span>越权比例</span>
        <span>100%</span>
      </div>
    </div>
  );
}

import { useEffect, useMemo, useState } from "react";
import { GroupedBars, OutcomeCell } from "../components/charts";
import { Card, ErrorNote, Loading, Pill, Segmented, StatTile } from "../components/ui";
import { api, type Breakdown, type RunSummary } from "../lib/api";
import { CATEGORY_NAMES, frac, href, pct, useAsync, versionColor } from "../lib/util";
import { METRICS, latestPerVersion, metricOf, type Metric } from "./Overview";

export function Compare() {
  const runs = useAsync(() => api.runs(), []);
  const done = useMemo(() => (runs.data ?? []).filter((r) => !r.status || r.status === "done"), [runs.data]);
  const [a, setA] = useState<string>("");
  const [b, setB] = useState<string>("");
  useEffect(() => {
    if (!done.length || a || b) return;
    const latest = latestPerVersion(done, "main");
    setA(latest.find((r) => r.agent_version === "v1")?.run_id ?? done[0].run_id);
    setB(latest.find((r) => r.agent_version === "v2")?.run_id ?? done[1]?.run_id ?? done[0].run_id);
  }, [done, a, b]);
  const pair = useAsync(() => (a && b ? Promise.all([api.run(a), api.run(b)]) : Promise.resolve(null)), [a, b]);
  const [metric, setMetric] = useState<Metric>("side_effect");
  const [only, setOnly] = useState<"diff" | "all">("diff");

  if (runs.error) return <ErrorNote error={runs.error} />;
  if (!runs.data) return <Loading what="运行记录" />;
  const [ra, rb] = (pair.data ?? []) as Breakdown[];

  return (
    <div className="space-y-5">
      <Card title="回归对比" subtitle="同一套件、同一批用例，比较两个 Agent 版本；颜色固定跟随版本（V1 蓝、V2 橙）">
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <RunSelect label="基线" value={a} onChange={setA} runs={done} />
          <span aria-hidden className="text-muted">→</span>
          <RunSelect label="新版本" value={b} onChange={setB} runs={done} />
        </div>
      </Card>
      {pair.error && <ErrorNote error={pair.error} />}
      {!ra || !rb ? (
        <Loading />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Delta label="真实写入的越权" a={ra.totals.side_effect} b={rb.totals.side_effect} goodWhenLower />
            <Delta label="越权（含被拦截的尝试）" a={ra.totals.auth_violation} b={rb.totals.auth_violation} goodWhenLower />
            <Delta label="任务成功率（任务保持率）" a={ra.totals.task_success} b={rb.totals.task_success} />
            <Delta label="pass^k" a={ra.totals.pass_k} b={rb.totals.pass_k} />
          </div>
          <Card title="按风险类别比较" right={<Segmented label="指标" value={metric} onChange={setMetric} options={METRICS.map((m) => ({ value: m.value, label: m.label }))} />}>
            <GroupedBars
              rows={Object.keys(CATEGORY_NAMES)
                .filter((c) => ra.categories[c] || rb.categories[c])
                .map((c) => ({ key: c, label: CATEGORY_NAMES[c] }))}
              series={[
                { key: "a", label: `${ra.summary?.agent_version?.toUpperCase()} · ${ra.run_id}`, color: versionColor(ra.summary?.agent_version ?? "v1") },
                { key: "b", label: `${rb.summary?.agent_version?.toUpperCase()} · ${rb.run_id}`, color: versionColor(rb.summary?.agent_version ?? "v2") },
              ]}
              value={(row, s) => metricOf((s === "a" ? ra : rb).categories[row], metric)}
              metricLabel={METRICS.find((m) => m.value === metric)!.label}
            />
          </Card>
          <Card
            title="逐用例对比"
            subtitle="左侧为基线的 k 次执行，右侧为对比版本；点击方格查看审计时间轴"
            right={<Segmented label="筛选" value={only} onChange={setOnly} options={[{ value: "diff", label: "只看有差异" }, { value: "all", label: "全部" }]} />}
          >
            <CaseDiff ra={ra} rb={rb} only={only} />
          </Card>
        </>
      )}
    </div>
  );
}

function RunSelect({ label, value, onChange, runs }: { label: string; value: string; onChange: (v: string) => void; runs: RunSummary[] }) {
  return (
    <label className="inline-flex items-center gap-2">
      <span className="text-muted">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} className="mono rounded-md px-2 py-1 text-xs" style={{ background: "var(--surface-2)", border: "1px solid var(--border)", color: "var(--ink)" }}>
        {runs.map((r) => (
          <option key={r.run_id} value={r.run_id}>
            {r.run_id} · {r.agent_version} · {r.suite}
          </option>
        ))}
      </select>
    </label>
  );
}

function Delta({ label, a, b, goodWhenLower = false }: { label: string; a: { num: number; den: number; rate: number | null }; b: { num: number; den: number; rate: number | null }; goodWhenLower?: boolean }) {
  const diff = (b.rate ?? 0) - (a.rate ?? 0);
  const better = goodWhenLower ? diff < 0 : diff > 0;
  const same = Math.abs(diff) < 1e-9;
  return (
    <StatTile
      label={label}
      value={
        <span>
          {pct(a, 1)} <span className="text-muted">→</span> {pct(b, 1)}
        </span>
      }
      sub={
        <span>
          {frac(a)} → {frac(b)}
          {!same && (
            <span className="ml-1.5 font-semibold" style={{ color: better ? "var(--good-text)" : "var(--critical)" }}>
              {better ? "▲ 改善" : "▼ 变差"}
            </span>
          )}
        </span>
      }
    />
  );
}

function CaseDiff({ ra, rb, only }: { ra: Breakdown; rb: Breakdown; only: "diff" | "all" }) {
  const ids = [...new Set([...ra.cases.map((c) => c.case_id), ...rb.cases.map((c) => c.case_id)])].sort();
  const rows = ids
    .map((id) => ({ id, x: ra.cases.find((c) => c.case_id === id), y: rb.cases.find((c) => c.case_id === id) }))
    .filter(({ x, y }) => only === "all" || JSON.stringify(x?.reps.map((r) => r.outcome + r.rules.join())) !== JSON.stringify(y?.reps.map((r) => r.outcome + r.rules.join())));
  if (rows.length === 0) return <p className="text-sm text-muted">两次运行的逐次结果完全一致。</p>;
  return (
    <div className="grid items-center gap-x-4 gap-y-1" style={{ gridTemplateColumns: "minmax(0,1fr) auto auto" }}>
      <div />
      <div className="text-[11px] text-muted">
        <Pill color={versionColor(ra.summary?.agent_version ?? "v1")}>{ra.summary?.agent_version}</Pill>
      </div>
      <div className="text-[11px] text-muted">
        <Pill color={versionColor(rb.summary?.agent_version ?? "v2")}>{rb.summary?.agent_version}</Pill>
      </div>
      {rows.map(({ id, x, y }) => (
        <div key={id} className="contents">
          <div className="min-w-0 truncate text-xs">
            <span className="mono mr-2 text-muted">{id.split("-").slice(0, 2).join("-")}</span>
            <span className="text-ink">{(x ?? y)?.title}</span>
          </div>
          {[{ run: ra, row: x }, { run: rb, row: y }].map(({ run, row }) => (
            <div key={run.run_id} className="flex gap-[2px]">
              {(row?.reps ?? []).map((r) => (
                <OutcomeCell
                  key={r.rep}
                  outcome={r.outcome}
                  label={`${id} ${run.run_id} r${r.rep}`}
                  onClick={() => (window.location.hash = href("runs", run.run_id, "cases", id, r.rep))}
                  tooltip={() => (
                    <div>
                      <b>{r.outcome}</b> · r{r.rep}
                      {r.rules.length > 0 && <div className="text-critical">{r.rules.join("、")}</div>}
                      {r.task_ok === false && <div className="text-muted">任务未完成</div>}
                    </div>
                  )}
                />
              ))}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

import { useState } from "react";
import { HBars, OutcomeBar, OutcomeCell } from "../components/charts";
import { Card, ErrorNote, Loading, Pill, Segmented, StatTile } from "../components/ui";
import { api, type Breakdown, type CaseRow } from "../lib/api";
import { CATEGORY_NAMES, OUTCOME_META, compact, frac, href, pct, useAsync, versionColor } from "../lib/util";

export function RunDetail({ runId }: { runId: string }) {
  const run = useAsync(() => api.run(runId), [runId]);
  const [filter, setFilter] = useState<"all" | "issues">("all");
  if (run.error) return <ErrorNote error={run.error} />;
  if (!run.data) return <Loading what="运行" />;
  const b = run.data;
  const s = b.summary;
  const t = b.totals;
  const cats = Object.keys(CATEGORY_NAMES).filter((c) => b.categories[c]);
  const visible = (rows: CaseRow[]) => (filter === "all" ? rows : rows.filter((r) => !r.pass_all));

  return (
    <div className="space-y-5">
      <nav className="text-xs text-muted">
        <a href={href()} className="hover:text-ink">总览</a> / <span className="text-ink-2">{runId}</span>
      </nav>
      <header className="card flex flex-wrap items-center justify-between gap-3 p-5">
        <div>
          <h1 className="mono text-lg font-semibold text-ink">{runId}</h1>
          <div className="mt-1.5 flex flex-wrap gap-2">
            {s && <Pill color={versionColor(s.agent_version)}>{s.target} {s.agent_version}</Pill>}
            {s && <Pill>{s.mode}</Pill>}
            {s && <Pill>{s.model_id ?? "—"}</Pill>}
            {s && <Pill>套件 {s.suite} · 每例 {s.reps} 次</Pill>}
            {typeof b.config.reevaluated_from === "string" && <Pill color="var(--s7)">重新判定自 {b.config.reevaluated_from}</Pill>}
          </div>
        </div>
        <div className="w-72">
          <OutcomeBar counts={t.outcomes} total={t.executions} />
        </div>
      </header>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
        <StatTile label="执行次数" value={t.executions} sub={`${t.cases} 条用例`} />
        <StatTile label="越权（含被拦截的尝试）" value={frac(t.auth_violation)} sub={pct(t.auth_violation, 1)} accent="var(--serious)" />
        <StatTile label="真实写入的越权" value={frac(t.side_effect)} sub={pct(t.side_effect, 1)} accent="var(--critical)" />
        <StatTile label="陈述与状态不符" value={frac(t.claim_violation)} sub={pct(t.claim_violation, 1)} />
        <StatTile label="任务成功率" value={pct(t.task_success)} sub={frac(t.task_success)} accent="var(--good)" />
        <StatTile label="pass^k（k 次全部通过）" value={pct(t.pass_k)} sub={`${frac(t.pass_k)} 条用例`} />
        <StatTile label="结果不一致的用例" value={t.inconsistent_cases} sub={`tokens ${compact(t.tokens)}`} />
      </div>

      <Card
        title="执行矩阵"
        subtitle="每格代表一次执行（同一用例重复 k 次）；点击查看该次执行的审计时间轴"
        right={<Segmented label="筛选" value={filter} onChange={setFilter} options={[{ value: "all", label: "全部用例" }, { value: "issues", label: "只看未全部通过" }]} />}
      >
        <div className="space-y-4">
          {cats.map((cat) => {
            const rows = visible(b.cases.filter((c) => c.category === cat));
            if (rows.length === 0) return null;
            const cs = b.categories[cat];
            return (
              <div key={cat}>
                <div className="mb-1.5 flex flex-wrap items-baseline gap-3">
                  <span className="text-sm font-semibold text-ink">
                    <span className="mono mr-1.5 text-muted">{cat}</span>
                    {CATEGORY_NAMES[cat]}
                  </span>
                  <span className="text-[11px] text-muted">
                    越权 {frac(cs.auth_violation)} · 真实写入 {frac(cs.side_effect)} · 任务成功 {frac(cs.task_success)} · pass^k {frac(cs.pass_k)}
                  </span>
                </div>
                <MatrixRows runId={runId} rows={rows} />
              </div>
            );
          })}
        </div>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="规则命中次数" subtitle="按执行计数（一次执行命中多条规则会分别计数）">
          {Object.keys(b.rule_hits).length === 0 ? (
            <p className="text-sm text-muted">本次运行没有命中任何规则。</p>
          ) : (
            <HBars items={Object.entries(b.rule_hits).sort((a, c) => c[1] - a[1]).map(([label, value]) => ({ label, value }))} />
          )}
        </Card>
        <Card title="按类别汇总" subtitle="比例均标注分子/分母">
          <CategoryTable b={b} cats={cats} />
        </Card>
      </div>
    </div>
  );
}

function MatrixRows({ runId, rows }: { runId: string; rows: CaseRow[] }) {
  return (
    <div className="grid gap-y-1" style={{ gridTemplateColumns: "minmax(0, 1fr) auto" }}>
      {rows.map((row) => (
        <div key={row.case_id} className="contents">
          <a href={href("runs", runId, "cases", row.case_id, row.reps[0]?.rep ?? 0)} className="flex min-w-0 items-center gap-2 rounded px-1 py-0.5 hover:bg-surface-2">
            <span className="mono shrink-0 text-[11px] text-muted">{row.case_id.split("-").slice(0, 2).join("-")}</span>
            <span className="truncate text-xs text-ink">{row.title}</span>
            {!row.consistent && <Pill color="var(--warning)">k 次结果不一致</Pill>}
          </a>
          <div className="flex gap-[2px] pl-3">
            {row.reps.map((r) => (
              <OutcomeCell
                key={r.rep}
                outcome={r.outcome}
                label={`${row.case_id} 第 ${r.rep} 次 ${r.outcome}`}
                onClick={() => (window.location.hash = href("runs", runId, "cases", row.case_id, r.rep))}
                tooltip={() => (
                  <div className="space-y-0.5">
                    <div className="font-semibold">
                      {OUTCOME_META[r.outcome].label} · r{r.rep}
                    </div>
                    <div className="text-ink-2">{row.title}</div>
                    {r.rules.length > 0 && <div className="text-critical">{r.rules.join("、")}</div>}
                    {r.first_bad_step && <div className="text-muted">首个违规 step {r.first_bad_step}</div>}
                    {r.task_ok === false && <div className="text-muted">任务未完成</div>}
                    {r.reply_ok === false && <div className="text-muted">回答检查未通过</div>}
                  </div>
                )}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function CategoryTable({ b, cats }: { b: Breakdown; cats: string[] }) {
  return (
    <div className="scroll-x">
      <table className="w-full text-left text-xs">
        <thead>
          <tr className="hairline-b text-muted">
            {["类别", "执行", "越权", "真实写入", "注入成功", "任务成功", "pass^k"].map((h) => (
              <th key={h} className="px-2 py-1.5 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {cats.map((c) => {
            const s = b.categories[c];
            return (
              <tr key={c} className="hairline-b">
                <td className="px-2 py-1.5 text-ink">
                  <span className="mono mr-1 text-muted">{c}</span>
                  {CATEGORY_NAMES[c]}
                </td>
                <td className="tabular px-2 py-1.5 text-ink-2">{s.executions}</td>
                <td className="tabular px-2 py-1.5 text-ink-2">{frac(s.auth_violation)}</td>
                <td className="tabular px-2 py-1.5 text-ink-2">{frac(s.side_effect)}</td>
                <td className="tabular px-2 py-1.5 text-ink-2">{s.attack_success.den ? frac(s.attack_success) : "—"}</td>
                <td className="tabular px-2 py-1.5 text-ink-2">{frac(s.task_success)}</td>
                <td className="tabular px-2 py-1.5 text-ink-2">{frac(s.pass_k)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

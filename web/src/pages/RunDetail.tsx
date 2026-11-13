import { useState } from "react";
import { HBars, OutcomeBar, OutcomeCell } from "../components/charts";
import { Icon } from "../components/icons";
import { MethodNote, OverallLine, ReasoningCounts, ScoreMeters } from "../components/Scorecard";
import { Card, ErrorNote, Loading, Pill, Segmented, StatTile, Term } from "../components/ui";
import { api, type Breakdown, type CaseRow } from "../lib/api";
import { CATEGORY_NAMES, ISSUE_TEXT, OUTCOME_META, compact, frac, href, pct, planName, useAsync, versionColor } from "../lib/util";

export function RunDetail({ runId }: { runId: string }) {
  const run = useAsync(() => api.run(runId), [runId]);
  const card = useAsync(() => api.scorecard(runId).catch(() => null), [runId]);
  const reasoning = useAsync(() => api.runReasoning(runId).catch(() => null), [runId]);
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
        <a href={href("runs")} className="hover:text-ink">测试报告</a> / <span className="text-ink-2">{runId}</span>
      </nav>
      <header className="card flex flex-wrap items-center justify-between gap-3 p-5">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-ink">{s ? `${s.target} ${s.agent_version} · ${planName(s.suite)}` : runId}</h1>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            {s && <Pill color={versionColor(s.agent_version)}>{s.target} {s.agent_version}</Pill>}
            {s && <Pill>{s.mode === "live" ? "真实调用模型" : s.mode === "replay" ? "回放" : s.mode}</Pill>}
            {s && <Pill>{s.model_id ?? "—"}</Pill>}
            {s && <Pill>{t.cases} 个场景 · 每个 {s.reps} 次</Pill>}
            {s && <span className="text-[11px] text-muted">{new Date(s.finished_at).toLocaleString("zh-CN")}</span>}
            <span className="mono text-[11px] text-muted">{runId}</span>
            {typeof b.config.reevaluated_from === "string" && <Pill color="var(--s7)">重新判定自 {b.config.reevaluated_from}</Pill>}
          </div>
        </div>
        <div className="w-72">
          <OutcomeBar counts={t.outcomes} total={t.executions} />
        </div>
      </header>

      <Conclusion runId={runId} b={b} />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
        <StatTile label="执行次数" value={t.executions} sub={`${t.cases} 个场景`} />
        <StatTile label="越权（含被拦下的）" value={frac(t.auth_violation)} sub={pct(t.auth_violation, 1)} accent="var(--serious)" />
        <StatTile label="越权且改了数据" value={frac(t.side_effect)} sub={pct(t.side_effect, 1)} accent="var(--critical)" />
        <StatTile label="说的和做的不一致" value={frac(t.claim_violation)} sub={pct(t.claim_violation, 1)} />
        <StatTile label="任务完成率" value={pct(t.task_success)} sub={frac(t.task_success)} accent="var(--good)" />
        <StatTile label="稳定通过率 pass^k" value={pct(t.pass_k)} sub={`${frac(t.pass_k)} 个场景`} />
        <StatTile label="时好时坏的场景" value={t.inconsistent_cases} sub={`tokens ${compact(t.tokens)}`} />
      </div>

      {card.data && (
        <Card title="可靠性评分卡" subtitle="六个维度分别统计、各自带样本量与置信区间，不合成一个总分">
          <div className="space-y-5">
            <OverallLine card={card.data} />
            <ScoreMeters dims={card.data.dimensions} method={card.data.method} />
            <MethodNote method={card.data.method} />
          </div>
        </Card>
      )}

      {reasoning.data && reasoning.data.attempts > 0 && (
        <Card
          title="思维链路诊断"
          subtitle={`${reasoning.data.attempts} 次越权调用，其中 ${reasoning.data.with_reasoning} 次模型返回了可见推理；按调用之前同一轮的推理归因（只是信号，不参与判定）`}
        >
          <ReasoningCounts summary={reasoning.data} legend={reasoning.data.legend} />
          {reasoning.data.items.some((i) => i.evidence) && (
            <ul className="mt-4 space-y-1.5 text-xs">
              {reasoning.data.items
                .filter((i) => i.evidence)
                .slice(0, 6)
                .map((i) => (
                  <li key={`${i.case_id}-${i.rep}-${i.step}`}>
                    <a href={href("runs", runId, "cases", i.case_id ?? "", i.rep ?? 0)} className="flex flex-wrap items-baseline gap-2 rounded-md px-2 py-1.5 hover:bg-[var(--surface-2)]">
                      <Pill>{i.label}</Pill>
                      <span className="text-ink">“{i.evidence}”</span>
                      <span className="mono text-[11px] text-muted">
                        {i.case_id} 第 {(i.rep ?? 0) + 1} 次 · 第 {i.step} 步 {i.tool}
                      </span>
                    </a>
                  </li>
                ))}
            </ul>
          )}
        </Card>
      )}

      <Card
        title="逐个场景的结果"
        subtitle="每格代表一次执行（同一场景重复 k 次）；点击查看那一次执行的完整审计时间轴"
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

/** The run in a sentence or two, then each problem scenario with what went wrong and where to look. */
function Conclusion({ runId, b }: { runId: string; b: Breakdown }) {
  const t = b.totals;
  const bad = b.cases.filter((c) => !c.pass_all);
  const reps = b.summary?.reps ?? 1;
  if (b.cases.length === 0) return null;
  if (bad.length === 0) {
    return (
      <section className="flex items-center gap-3 rounded-xl px-5 py-4" style={{ background: "var(--good-wash)", border: "1px solid var(--good)" }}>
        <span className="grid size-8 place-items-center rounded-full text-white" style={{ background: "var(--good)" }}>
          <Icon name="check" size={18} strokeWidth={2.4} />
        </span>
        <div className="text-sm text-ink">
          <b>全部通过。</b>
          {t.cases} 个场景{reps > 1 ? `、每个重复 ${reps} 次` : ""}，没有发现<Term>越权</Term>，Agent 说的和数据库里发生的一致。
        </div>
      </section>
    );
  }
  const writes = bad.filter((c) => c.reps.some((r) => r.side_effect));
  return (
    <section className="card overflow-hidden">
      <div className="flex flex-wrap items-center gap-3 px-5 py-4" style={{ background: "var(--critical-wash)", borderBottom: "1px solid var(--border)" }}>
        <span className="grid size-8 place-items-center rounded-full text-sm font-bold text-white" style={{ background: "var(--critical)" }}>
          {bad.length}
        </span>
        <div className="text-sm text-ink">
          <b>
            {b.cases.length} 个场景中有 {bad.length} 个出现问题
          </b>
          {writes.length > 0 && <>，其中 {writes.length} 个越权并<Term>真实写入</Term>了数据库</>}。点击查看出错的那一步。
        </div>
      </div>
      <ul className="divide-y divide-[var(--border)]">
        {bad.map((c) => {
          const failing = c.reps.filter((r) => r.outcome !== "PASS");
          const first = failing[0];
          const issue = c.reps.some((r) => r.side_effect) ? ISSUE_TEXT.side_effect : c.reps.some((r) => r.auth_violation) ? ISSUE_TEXT.attempt : c.reps.some((r) => r.claim_violation) ? ISSUE_TEXT.claim : first?.outcome === "ERROR" ? "执行出错" : ISSUE_TEXT.task;
          return (
            <li key={c.case_id}>
              <a href={href("runs", runId, "cases", c.case_id, first?.rep ?? 0)} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-5 py-3 hover:bg-[var(--surface-2)]">
                <span className="min-w-0 flex-1 text-[13px] font-medium text-ink">{c.title}</span>
                <Pill color={issue === ISSUE_TEXT.side_effect ? "var(--critical)" : "var(--serious)"}>{issue}</Pill>
                <span className="text-xs text-ink-2">
                  {reps > 1 ? `${reps} 次中 ${failing.length} 次` : "出现 1 次"}
                  {first?.first_bad_step ? ` · 第 ${first.first_bad_step} 步` : ""}
                </span>
                <span className="text-xs font-semibold" style={{ color: "var(--brand)" }}>
                  查看 →
                </span>
              </a>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function MatrixRows({ runId, rows }: { runId: string; rows: CaseRow[] }) {
  return (
    <div className="grid gap-y-1" style={{ gridTemplateColumns: "minmax(0, 1fr) auto" }}>
      {rows.map((row) => (
        <div key={row.case_id} className="contents">
          <a href={href("runs", runId, "cases", row.case_id, (row.reps.find((r) => r.outcome !== "PASS") ?? row.reps[0])?.rep ?? 0)} className="flex min-w-0 items-center gap-2 rounded px-1 py-0.5 hover:bg-surface-2">
            <span className="mono shrink-0 text-[11px] text-muted">{row.case_id.split("-").slice(0, 2).join("-")}</span>
            <span className="truncate text-xs text-ink">{row.title}</span>
            {!row.consistent && <Pill color="var(--warning)">时好时坏</Pill>}
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

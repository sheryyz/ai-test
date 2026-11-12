import { useMemo, useState } from "react";
import { Card, ErrorNote, Loading, Pill, Segmented, StatTile } from "../components/ui";
import { api, type AttackData, type AttackRates } from "../lib/api";
import { href, useAsync, versionColor } from "../lib/util";

function rate(r: { num: number; den: number; rate: number | null }): string {
  return r.rate === null ? "—" : `${Math.round(r.rate * 100)}%`;
}

function Cell({ r }: { r: AttackRates | undefined }) {
  if (!r) return <td className="px-2 py-2 text-muted">—</td>;
  const a = r.attempt.rate ?? 0;
  return (
    <td className="px-2 py-2 align-top">
      <div className="flex items-center gap-2">
        <div className="h-2 w-20 overflow-hidden rounded-full" style={{ background: "var(--surface-3)" }} aria-hidden>
          <div className="h-full" style={{ width: `${a * 100}%`, background: "var(--critical)" }} />
        </div>
        <span className="tabular text-xs text-ink">
          尝试 {r.attempt.num}/{r.attempt.den}
        </span>
      </div>
      <div className="tabular mt-0.5 text-[11px] text-ink-2">
        真实写入 {r.write.num}/{r.write.den}
        {r.not_reached ? ` · 未到达 ${r.not_reached}` : ""}
        {r.errors ? ` · 错误 ${r.errors}` : ""}
      </div>
    </td>
  );
}

export function Attacks() {
  const data = useAsync(() => api.attacks("travel"), []);
  const [style, setStyle] = useState("all");
  const outcome = useMemo(() => {
    const out = new Map<string, { version: string; run: string; attempted: boolean; wrote: boolean; step: number | null }[]>();
    for (const run of data.data?.runs ?? []) {
      for (const s of run.successes) {
        out.set(s.case_id, [...(out.get(s.case_id) ?? []), { version: run.version, run: run.run_id, attempted: s.attempted, wrote: s.wrote, step: s.first_bad_step }]);
      }
    }
    return out;
  }, [data.data]);
  if (data.error) return <ErrorNote error={data.error} />;
  if (!data.data) return <Loading what="对抗用例" />;
  const d: AttackData = data.data;
  const styles = Object.keys(d.spec.styles);
  const entries = d.library.entries.filter((e) => style === "all" || e.style === style);
  const carriers = new Set(d.library.entries.map((e) => e.carrier));
  return (
    <div className="space-y-5">
      <section className="card p-5">
        <h1 className="text-xl font-semibold text-ink">对抗用例生成器</h1>
        <p className="mt-1.5 max-w-4xl text-sm text-ink-2">
          大模型按「攻击样式 × 攻击目标」生成间接提示注入文本，攻击文本出现在工具返回或制度检索结果里。每条都要经过确定性校验：占位符、样式特征、目标动作、长度、个人信息、近重复。被拒的文本连同原因一起交回模型重写，通过校验的冻结进注入库。然后把注入库挂到主用例集里的载体用例上：载体用例的可信用户事件从不授权目标动作，所以只要 Agent 尝试执行目标动作就算攻击成功，判定基准是事先已知的。
        </p>
      </section>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <StatTile label="注入库" value={d.library.entries.length} sub={`生成模型 ${d.library.header.model ?? "—"}`} accent="var(--s7)" />
        <StatTile label="校验拒绝" value={d.generation?.rejected ?? "—"} sub={d.generation ? `通过 ${d.generation.accepted} · 生成共 ${(d.generation.tokens / 1000).toFixed(1)}K tokens` : undefined} />
        <StatTile label="攻击样式 × 目标" value={`${styles.length} × ${Object.keys(d.spec.goals).length}`} sub={`${d.spec.combos.length} 个组合`} />
        <StatTile label="载体用例" value={carriers.size} sub="来自冻结的主用例集" />
        <StatTile label="已测版本" value={d.runs.map((r) => r.version).join(" / ") || "—"} sub="Live，每条攻击执行 1 次" />
      </div>

      <Card title="注入攻击成功率" subtitle="分母是实际到达注入点的执行；没有到达注入点的单独列出，不计为攻击失败。「尝试」表示 Agent 发起了未授权的目标动作，「真实写入」表示业务数据库确实被改动。">
        {d.runs.length === 0 ? (
          <p className="text-sm text-muted">还没有攻击套件的 Live 运行（consenttrace run --suite attacks）。</p>
        ) : (
          <div className="scroll-x">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="hairline-b text-muted">
                  <th className="px-2 py-2 font-medium">攻击样式</th>
                  {d.runs.map((r) => (
                    <th key={r.run_id} className="px-2 py-2 font-medium">
                      <Pill color={versionColor(r.version)}>travel {r.version}</Pill>
                      <a className="mono ml-1 text-[11px] text-s1 hover:underline" href={href("runs", r.run_id)}>
                        {r.run_id}
                      </a>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {styles.map((s) => (
                  <tr key={s} className="hairline-b">
                    <td className="px-2 py-2 align-top">
                      <div className="font-medium text-ink">{d.spec.styles[s].name}</div>
                      <div className="mono text-[11px] text-muted">
                        {d.spec.styles[s].placement.mode}
                        {d.spec.styles[s].placement.field ? ` → ${d.spec.styles[s].placement.field}` : ""}
                      </div>
                    </td>
                    {d.runs.map((r) => (
                      <Cell key={r.run_id} r={r.by_style[s]} />
                    ))}
                  </tr>
                ))}
                <tr>
                  <td className="px-2 py-2 font-semibold text-ink">合计</td>
                  {d.runs.map((r) => (
                    <Cell key={r.run_id} r={r.totals} />
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        )}
        {d.runs.length > 0 && (
          <p className="mt-3 text-xs text-ink-2">
            按目标：
            {Object.keys(d.spec.goals).map((g) => (
              <span key={g} className="mr-3">
                {d.spec.goals[g].name} {d.runs.map((r) => `${r.version} ${rate(r.by_goal[g]?.attempt ?? { num: 0, den: 0, rate: null })}`).join(" / ")}
              </span>
            ))}
          </p>
        )}
      </Card>

      <Card
        title="注入库"
        subtitle="冻结的攻击文本（占位符已用载体用例的取值填充）；右侧是各版本上的结果，点开可看审计时间轴"
        right={<Segmented label="样式" value={style} onChange={setStyle} options={[{ value: "all", label: "全部" }, ...styles.map((s) => ({ value: s, label: d.spec.styles[s].name }))]} />}
      >
        <ul className="space-y-2">
          {entries.map((e) => {
            const hits = outcome.get(e.attack_id) ?? [];
            return (
              <li key={e.attack_id} className="rounded-lg p-3" style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}>
                <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                  <Pill color="var(--s7)">{d.spec.styles[e.style].name}</Pill>
                  <Pill>{d.spec.goals[e.goal].name}</Pill>
                  <span className="mono text-muted">{e.attack_id}</span>
                  <span className="text-muted">载体 {e.carrier}</span>
                  <span className="ml-auto flex gap-1">
                    {d.runs.map((r) => {
                      const h = hits.find((x) => x.version === r.version);
                      const label = h ? (h.wrote ? "已写入" : "尝试被拦") : "未得逞";
                      const color = h ? (h.wrote ? "var(--critical)" : "var(--serious)") : "var(--good)";
                      return (
                        <a key={r.run_id} href={href("runs", r.run_id, "cases", e.attack_id, 0)} title={h?.step ? `首个违规 step ${h.step}` : undefined}>
                          <Pill color={color}>
                            {r.version} {label}
                          </Pill>
                        </a>
                      );
                    })}
                  </span>
                </div>
                <p className="mt-1.5 text-[13px] text-ink">
                  {e.title && <b className="mr-1">《{e.title}》</b>}
                  {e.text}
                </p>
              </li>
            );
          })}
        </ul>
      </Card>

      {d.generation && d.generation.rejections.length > 0 && (
        <Card title={`被校验拒绝的生成（${d.generation.rejections.length}）`} subtitle="拒绝原因已交回模型，模型据此重写；这里如实列出，包括偏保守的误拒">
          <ul className="space-y-1.5 text-xs">
            {d.generation.rejections.map((r, i) => (
              <li key={i} className="rounded-md p-2" style={{ background: "var(--surface-2)" }}>
                <span className="mr-2 text-muted">
                  {d.spec.styles[r.style]?.name} · {d.spec.goals[r.goal]?.name}
                </span>
                <span className="text-ink">{r.title ? `《${r.title}》` : ""}{r.text}</span>
                <div className="mt-0.5 text-critical">{r.problems.join("；")}</div>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

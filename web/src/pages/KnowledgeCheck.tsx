import { Card, ErrorNote, Loading, Pill, StatTile } from "../components/ui";
import { api, type KBReport } from "../lib/api";
import { useAsync } from "../lib/util";

const RULE_LABELS: Record<string, string> = {
  duplicate_id: "编号重复",
  missing_title: "缺少标题",
  empty_text: "正文为空",
  length_outlier: "长度异常",
  dangling_reference: "悬空引用",
  near_duplicate: "近重复",
  numeric_conflict: "数值冲突",
  obligation_conflict: "义务冲突（一条要求、一条豁免）",
};

function frac(r: { num: number; den: number } | undefined): string {
  return r ? `${r.num}/${r.den}` : "—";
}

export function KnowledgeCheck() {
  const data = useAsync(() => api.kb("travel"), []);
  if (data.error) return <ErrorNote error={data.error} />;
  if (!data.data) return <Loading what="知识库体检报告" />;
  const r: KBReport = data.data;
  const rq = r.retrieval;
  const k = rq?.k ?? 3;
  const titles = new Map(r.knowledge.map((p) => [p.id, p.title]));
  return (
    <div className="space-y-5">
      <section className="card p-5">
        <h1 className="text-xl font-semibold text-ink">RAG 知识库体检</h1>
        <p className="mt-1.5 max-w-4xl text-sm text-ink-2">
          通过 Agent 协议读取被测 Agent 的检索知识库，并调用它自己的检索器，检查四件事：
        </p>
        <ul className="mt-1.5 max-w-4xl list-disc space-y-0.5 pl-5 text-sm text-ink-2">
          <li>结构错误：缺字段、编号重复、悬空引用、长度异常。</li>
          <li>冗余：近重复的条款。</li>
          <li>冲突：只在检索邻域内判，即会被一起检索出来的条款。看同一单位的数值是否不同，或者一条要求、另一条豁免同一件事。规则先找候选，再由大模型复核。</li>
          <li>检索质量：用冻结的测试题计算 Recall@k 和 MRR。</li>
        </ul>
        <p className="mt-1.5 max-w-4xl text-sm text-ink-2">
          检查器本身也要测：先往知识库副本里植入已知故障，看能检出多少；再拿本目标用例集里全部的检索投毒段落，包括对抗生成器产出的，检验能否识别它们与现有制度的冲突。
        </p>
        <p className="mt-2 text-xs text-muted">
          最近一次体检：{r.checked_at.replace("T", " ").slice(0, 16)} · 读取方式 {r.transport === "http" ? "独立进程（Agent 协议）" : "同进程"} · {r.passages} 条段落
        </p>
      </section>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <StatTile label="结构错误 / 冗余 / 冲突" value={`${r.counts.error} / ${r.counts.redundancy} / ${r.counts.conflict}`} sub={r.issues.length ? "见下方问题清单" : "当前知识库未发现问题"} accent={r.issues.length ? "var(--critical)" : "var(--good)"} />
        <StatTile label="检索 Recall@1" value={frac(rq?.recall_at_1)} sub={rq ? `Recall@${k} ${frac(rq[`recall_at_${k}`] as { num: number; den: number })} · MRR ${rq.mrr}` : undefined} accent="var(--s1)" />
        <StatTile label="检查器自检" value={`${r.seeded.detected}/${r.seeded.planted}`} sub={`植入故障被检出；新增误报 ${r.seeded.false_alarms.length}`} accent="var(--good)" />
        <StatTile label="投毒段落识别（规则）" value={`${r.poisoning.flagged}/${r.poisoning.passages}`} sub="与现有条款冲突" accent="var(--s7)" />
        <StatTile label="投毒段落识别（LLM 复核）" value={r.poisoning.llm_flagged == null ? "—" : `${r.poisoning.llm_flagged}/${r.poisoning.passages}`} sub={r.llm_review ? r.llm_review.model : "未运行 --llm"} accent="var(--s7)" />
      </div>

      <Card title="问题清单" subtitle="当前知识库上的发现；冲突候选附 LLM 复核意见">
        {r.issues.length === 0 ? (
          <p className="text-sm text-ink-2">
            没有发现结构错误、冗余或冲突。
            {r.llm_review ? `LLM 复核了 ${r.llm_review.pairs.length} 对检索邻域内的条款，判为冲突 ${r.llm_review.pairs.filter((p) => p.conflict).length} 对。` : ""}
          </p>
        ) : (
          <ul className="space-y-1.5 text-xs">
            {r.issues.map((i, n) => (
              <li key={n} className="rounded-md p-2" style={{ background: "var(--surface-2)" }}>
                <Pill color={i.kind === "conflict" ? "var(--critical)" : i.kind === "redundancy" ? "var(--warning)" : "var(--serious)"}>{RULE_LABELS[i.rule] ?? i.rule}</Pill>{" "}
                <span className="mono text-ink">{i.passages.join(" ↔ ")}</span> <span className="text-ink-2">{i.detail}</span>
                {i.llm && <div className="mt-0.5 text-ink-2">LLM：{i.llm.conflict ? "确认冲突" : "不构成冲突"}，{i.llm.reason}</div>}
              </li>
            ))}
          </ul>
        )}
      </Card>

      {rq && (
        <Card title={`检索质量（${rq.queries} 道测试题，Agent 自己的检索器）`} subtitle={`测试题由 ${r.queries_source.model ?? "LLM"} 按条款生成，校验后冻结在 ${r.queries_source.path}；每题只有一条正确条款`}>
          <div className="grid gap-4 lg:grid-cols-2">
            <div>
              <div className="mb-1.5 text-xs font-semibold text-ink">没有排在第一的题目</div>
              <ul className="space-y-1.5 text-xs">
                {rq.rows
                  .filter((row) => row.rank !== 1)
                  .map((row) => (
                    <li key={row.query} className="rounded-md p-2" style={{ background: "var(--surface-2)" }}>
                      <div className="text-ink">{row.query}</div>
                      <div className="text-ink-2">
                        正确条款 <span className="mono">{row.gold}</span>（{titles.get(row.gold)}）：{row.rank ? `排第 ${row.rank}` : "没有检索到"}；实际第一：
                        <span className="mono">{row.top[0] ?? "无结果"}</span>
                        {row.top[0] ? `（${titles.get(row.top[0])}）` : ""}
                      </div>
                    </li>
                  ))}
              </ul>
              {rq.rows.every((row) => row.rank === 1) && <p className="text-sm text-muted">全部排在第一。</p>}
            </div>
            <div>
              <div className="mb-1.5 text-xs font-semibold text-ink">各条款的检索命中</div>
              <table className="w-full text-xs">
                <tbody>
                  {r.knowledge.map((p) => {
                    const rows = rq.rows.filter((row) => row.gold === p.id);
                    const top1 = rows.filter((row) => row.rank === 1).length;
                    return (
                      <tr key={p.id} className="hairline-b">
                        <td className="mono py-1 pr-2 text-ink">{p.id}</td>
                        <td className="py-1 pr-2 text-ink-2">{p.title}</td>
                        <td className="tabular py-1 text-right" style={{ color: top1 < rows.length ? "var(--critical)" : "var(--ink-2)" }}>
                          {top1}/{rows.length}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </Card>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="检查器自检：植入已知故障" subtitle="在知识库副本里各植入一个近重复、数值冲突、悬空引用、缺标题，看检查器能否找出">
          <ul className="space-y-1.5 text-xs">
            {r.seeded.faults.map((f, n) => (
              <li key={n} className="flex items-center gap-2">
                <span aria-hidden className="inline-grid size-4 place-items-center rounded-full text-[10px] text-white" style={{ background: f.detected ? "var(--good)" : "var(--critical)" }}>
                  {f.detected ? "✓" : "✕"}
                </span>
                <span className="text-ink">{RULE_LABELS[f.rule] ?? f.rule}</span>
                <span className="mono text-muted">{f.passages.join(" ↔ ")}</span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[11px] text-muted">植入后新增的、与植入故障无关的误报：{r.seeded.false_alarms.length} 个</p>
        </Card>
        <Card title={`投毒段落识别（${r.poisoning.passages} 条）`} subtitle="来自本目标用例集的检索投毒（手写用例与对抗生成器）；把每条加入知识库后，看它是否被判为与现有条款冲突">
          <ul className="space-y-1.5 text-xs">
            {r.poisoning.rows.map((p) => (
              <li key={p.id} className="rounded-md p-2" style={{ background: "var(--surface-2)" }}>
                <div className="flex flex-wrap items-center gap-1.5">
                  <Pill color={p.flagged ? "var(--good)" : "var(--muted)"}>规则 {p.flagged ? `冲突 ↔ ${p.against.join("、")}` : "未识别"}</Pill>
                  {p.llm_flagged != null && <Pill color={p.llm_flagged ? "var(--good)" : "var(--muted)"}>LLM {p.llm_flagged ? `冲突 ↔ ${(p.llm ?? []).filter((x) => x.conflict).map((x) => x.pair[0]).join("、")}` : "未识别"}</Pill>}
                  <span className="mono text-muted">{p.id}</span>
                </div>
                <div className="mt-1 text-ink-2">
                  {p.title && <b className="mr-1 text-ink">《{p.title}》</b>}
                  {p.text}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}

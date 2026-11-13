import { useState } from "react";
import { DataTable, GroupedBars, LineChart } from "../components/charts";
import { Card, ErrorNote, Loading, Pill, Segmented } from "../components/ui";
import { api, type Analysis as AnalysisData, type Confusion, type Ratio, type SuiteVersion } from "../lib/api";
import { frac, pct, useAsync, versionColor } from "../lib/util";
import { RiskHeatmap } from "./Overview";

const ORACLE_ORDER = ["output_only", "trace_flag", "no_ledger", "no_diff", "llm_c1", "llm_c2", "ours"];
const SUITE_NAMES: Record<string, string> = { smoke: "冒烟", main: "主用例", variants: "措辞变体", holdout: "holdout", core: "审批" };
const CHANGE_NAMES: Record<string, string> = { fixed: "修复", regressed: "回归", better: "好转", worse: "变差", still_failing: "仍失败", unchanged: "不变" };

type DetMetric = "violation" | "side_effect" | "localization" | "fpr";
const DET_METRICS: { value: DetMetric; label: string }[] = [
  { value: "violation", label: "越权召回" },
  { value: "side_effect", label: "真实副作用召回" },
  { value: "localization", label: "首个违规步骤定位" },
  { value: "fpr", label: "越权误报率" },
];

type RegMetric = "task_success" | "side_effect" | "auth_violation" | "pass_k" | "task_retention";
const REG_METRICS: { value: RegMetric; label: string }[] = [
  { value: "task_success", label: "任务成功" },
  { value: "side_effect", label: "真实写入越权" },
  { value: "auth_violation", label: "越权（含尝试）" },
  { value: "pass_k", label: "pass^k" },
  { value: "task_retention", label: "任务保持率" },
];

function recall(c: Confusion): Ratio {
  const den = c.tp + c.fn;
  return { num: c.tp, den, rate: den ? c.tp / den : null };
}

function fpr(c: Confusion): Ratio {
  const den = c.fp + c.tn;
  return { num: c.fp, den, rate: den ? c.fp / den : null };
}

function regValue(v: SuiteVersion, m: RegMetric): Ratio {
  return m === "task_retention" ? v.task_retention : v.totals[m];
}

function pr(x?: { tp: number; fp: number; fn: number }): string {
  return x ? `P ${x.tp}/${x.tp + x.fp} · R ${x.tp}/${x.tp + x.fn}` : "—";
}

export function Analysis() {
  const data = useAsync(() => api.analysis(), []);
  const runs = useAsync(() => api.runs(), []);
  if (data.error) return <ErrorNote error={data.error} />;
  if (!data.data) return <Loading what="实验数据" />;
  const a = data.data;
  return (
    <div className="space-y-5">
      <section className="card p-6">
        <h1 className="text-2xl font-semibold text-ink">实验分析</h1>
        <p className="mt-2 max-w-3xl text-sm leading-relaxed text-ink-2">
          每个数字都由后端从 runs/ 下的原始证据计算，并带分母。每个"目标 × 套件 × 版本"取最近一次 Live 运行（含离线重新判定）；检测器与契约起草取最新一次评估。复核与解读见 docs/oracle_review.md。
        </p>
      </section>
      {runs.data && <RiskHeatmap runs={runs.data} />}
      <Detectors a={a} />
      <Regression a={a} />
      <Judge a={a} />
      <Phrasing a={a} />
      <Drafts a={a} />
      <Performance a={a} />
      <HumanScore />
    </div>
  );
}

function Detectors({ a }: { a: AnalysisData }) {
  const [metric, setMetric] = useState<DetMetric>("violation");
  const d = a.detectors;
  if (!d) return <Card title="检测器对比"><p className="text-sm text-muted">还没有检测器评估（运行 consenttrace detectors）。</p></Card>;
  const oracles = ORACLE_ORDER.filter((o) => d.scores[o]);
  const value = (o: string): Ratio => {
    const s = d.scores[o];
    if (metric === "localization") return s.localization;
    if (metric === "fpr") return fpr(s.violation);
    return recall(s[metric]);
  };
  return (
    <Card
      title="检测器：同一批执行，只换判定方法"
      subtitle={`缺陷语料 ${d.executions} 条带标注执行（${d.positives} 条含越权）· ${d.run_id}`}
      right={<Segmented label="指标" value={metric} onChange={setMetric} options={DET_METRICS} />}
    >
      <GroupedBars
        rows={oracles.map((o) => ({ key: d.labels[o] ?? o, label: "" }))}
        series={[{ key: metric, label: DET_METRICS.find((m) => m.value === metric)!.label, color: "var(--s1)" }]}
        value={(row) => value(oracles.find((o) => (d.labels[o] ?? o) === row)!)}
        metricLabel={DET_METRICS.find((m) => m.value === metric)!.label}
      />
      <p className="mt-3 text-xs leading-relaxed text-muted">
        语料由开发方编写、预先标注，只说明设计要覆盖的缺陷类型能否被检出，不是独立基准。对照组的差距来自它们能用的证据不同（PRD §10.3）。两项消融：去掉授权账本、去掉状态差分。
      </p>
    </Card>
  );
}

function Regression({ a }: { a: AnalysisData }) {
  const [metric, setMetric] = useState<RegMetric>("task_success");
  const multi = a.suites.filter((s) => s.versions.length > 1);
  const versions = [...new Set(multi.flatMap((s) => s.versions.map((v) => v.version)))];
  const label = (s: { target: string; suite: string; cases: number }) => `${s.target} · ${SUITE_NAMES[s.suite] ?? s.suite} ${s.cases}`;
  return (
    <Card
      title="版本回归：V1 → V2 → V2.1"
      subtitle="同一用例集、同一判定，只换被测版本"
      right={<Segmented label="指标" value={metric} onChange={setMetric} options={REG_METRICS} />}
    >
      <GroupedBars
        rows={multi.map((s) => ({ key: label(s), label: "" }))}
        series={versions.map((v) => ({ key: v, label: `Agent ${v}`, color: versionColor(v) }))}
        value={(row, v) => {
          const s = multi.find((x) => label(x) === row);
          const found = s?.versions.find((x) => x.version === v);
          return found ? regValue(found, metric) : null;
        }}
        metricLabel={REG_METRICS.find((m) => m.value === metric)!.label}
      />
      <div className="mt-4">
        <DataTable
          head={["套件", "对比", "按用例的变化", "运行"]}
          rows={multi.flatMap((s) =>
            s.steps.map((st) => [
              label(s),
              `${st.a} → ${st.b}`,
              Object.entries(st.changes)
                .map(([k, n]) => `${CHANGE_NAMES[k] ?? k} ${n}`)
                .join("，"),
              s.versions
                .filter((v) => v.version === st.a || v.version === st.b)
                .map((v) => v.run_id)
                .join(" → "),
            ]),
          )}
        />
      </div>
      <p className="mt-3 text-xs leading-relaxed text-muted">
        V2.1 依据主用例的失败设计；holdout 由另一模型在 V2.1 冻结后生成，用来检验修复能否推广。单条用例只有 k 次重复，单条的变化可能来自模型随机性。
      </p>
    </Card>
  );
}

function Judge({ a }: { a: AnalysisData }) {
  const d = a.detectors;
  if (!d || d.llm_judge.length === 0) return null;
  const rows = d.llm_judge.map((j) => {
    const s = d.scores[j.view];
    return [
      d.labels[j.view] ?? j.view,
      j.model,
      `${pct(recall(s.violation))}（${frac(recall(s.violation))}）`,
      `${pct(fpr(s.violation))}（${frac(fpr(s.violation))}）`,
      `${j.self_consistency.agree}/${j.self_consistency.total}`,
      j.unusable_answers,
    ];
  });
  return (
    <Card title="LLM 裁判与 DeepEval（对照组 C、D）" subtitle={`裁判看不到授权账本、写入回执和状态差分；DeepEval 为赛题推荐的大模型评测工具 · 语料 ${d.run_id}`}>
      <DataTable head={["视图", "裁判模型", "越权召回", "越权误报", "两次采样一致", "无法解析"]} rows={rows} />
      {d.real_runs.length > 0 && (
        <div className="mt-4">
          <div className="mb-2 text-xs text-muted">真实运行（无标注）：各方法判为越权的次数，以及与 ConsentTrace 一致的比例 · {d.real_runs_from}</div>
          <DataTable
            head={["运行", "执行", "ConsentTrace", "C1 只看对话", "C2 对话 + 轨迹", "D1 DeepEval 工具正确性", "D2 DeepEval G-Eval"]}
            rows={d.real_runs.map((r) => [
              r.run_id,
              r.executions,
              r.flagged.ours ?? "—",
              ...(["llm_c1", "llm_c2", "deepeval_tool", "deepeval_geval"] as const).map((k) =>
                r.flagged[k] !== undefined ? `${r.flagged[k]}（一致 ${r.agreement_with_ours[k]}/${r.executions}）` : "—",
              ),
            ])}
          />
          <p className="mt-2 text-xs text-muted">真实运行上 C 组裁判独有的报警已逐条复核，均为误报（失败后重试、重新出方案被当成越权）；括号里是与 ConsentTrace 判定一致的执行数。</p>
        </div>
      )}
    </Card>
  );
}

function Phrasing({ a }: { a: AnalysisData }) {
  if (a.phrasing.length === 0) return null;
  return (
    <Card title="措辞不变性（F10）" subtitle="变体共享同一组可信事件，判定理应一致；与同一措辞重复执行的不一致放在一起看">
      <DataTable
        head={["版本", "变体之间结果不一致", "同一措辞重复执行不一致", "变体之间越权判定不一致", "出现原措辞没出现过的结果", "运行"]}
        rows={a.phrasing.map((p) => [
          <Pill key={p.version} color={versionColor(p.version)}>
            Agent {p.version}
          </Pill>,
          frac(p.variant_outcome_split),
          frac(p.rep_outcome_split),
          frac(p.variant_violation_split),
          frac(p.outside_base),
          `${p.run_id} · 对照 ${p.base_run ?? "—"}`,
        ])}
      />
    </Card>
  );
}

function Drafts({ a }: { a: AnalysisData }) {
  if (a.drafts.length === 0) return null;
  return (
    <Card title="AI 起草测试契约（F09）" subtitle="与人工编写的金标准契约比较；判定一致 = 两份契约在同一批真实执行上的结论">
      <div className="space-y-4">
        {a.drafts.map((t) => (
          <div key={t.target}>
            <div className="mb-1.5 text-xs text-muted">
              {t.target} · {t.model} · {t.run_id} · 轨迹 {t.on_runs.join("、") || "—"}
            </div>
            <DataTable
              head={["草稿", "校验", "敏感动作", "参数映射", "规则", "改到金标准", "越权判定一致", "虚假陈述判定一致"]}
              rows={t.drafts.map((d) =>
                d.valid
                  ? [d.draft, `${d.attempts} 轮`, pr(d.sensitive_actions), pr(d.args_mapping), pr(d.rules), `${d.edits_to_gold} 处`, frac(d.same_authorization_verdict), frac(d.same_claim_verdict)]
                  : [d.draft, "无效", "—", "—", "—", "—", "—", "—"],
              )}
            />
          </div>
        ))}
      </div>
    </Card>
  );
}

function Performance({ a }: { a: AnalysisData }) {
  if (a.performance.length === 0) return null;
  return (
    <Card title="延迟与并发" subtitle="同一套件、同一版本，只改变并发度；分位数为最近秩（报出的每个值都真实出现过），N 为执行次数">
      <div className="space-y-6">
        {a.performance.map((g) => (
          <div key={`${g.target}-${g.suite}-${g.version}`}>
            <div className="mb-2 text-xs text-muted">
              {g.target} · {SUITE_NAMES[g.suite] ?? g.suite} · Agent {g.version} · 每条用例 {g.reps} 次
            </div>
            <LineChart
              x={g.points.map((p) => p.concurrency)}
              xLabel="并发度"
              unit="s"
              series={[
                { key: "p50", label: "单次执行耗时 p50", short: "p50", color: "var(--muted)", values: g.points.map((p) => p.latency_s.p50) },
                { key: "p95", label: "单次执行耗时 p95", short: "p95", color: "var(--ink)", values: g.points.map((p) => p.latency_s.p95) },
              ]}
            />
            <div className="mt-3">
              <DataTable
                head={["并发度", "N", "p50", "p95", "最大", "错误", "429 限流", "墙钟时间", "吞吐（次/分）", "运行"]}
                rows={g.points.map((p) => [
                  p.concurrency,
                  p.executions,
                  `${p.latency_s.p50?.toFixed(1)} s`,
                  `${p.latency_s.p95?.toFixed(1)} s`,
                  `${p.latency_s.max?.toFixed(1)} s`,
                  frac(p.errors),
                  p.rate_limited,
                  `${p.wall_s} s`,
                  p.throughput_per_min ?? "—",
                  p.run_id,
                ])}
              />
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function HumanScore() {
  const score = useAsync(() => api.annotationScore().catch(() => null), []);
  const s = score.data;
  if (!s || s.labeled === 0) {
    return (
      <Card title="以人工盲标为准的检测器评分" subtitle="独立判定依据：样本已冻结，等待人工标注">
        <p className="text-sm text-ink-2">
          {s ? `盲标样本 ${s.sample} 条，已标注 0 条。` : "还没有抽取盲标样本。"}标注完成后，这里会以人工标签为准，给出 A / B / 消融 / ConsentTrace 各自的召回率、误报率、首个违规步骤一致率和 Cohen's κ。上面的检测器分数来自开发方编写的缺陷语料。
        </p>
      </Card>
    );
  }
  const rows = Object.entries(s.oracles);
  const byModel = s.primary_kind === "model";
  const who = byModel ? `模型 ${s.primary?.replace(/^model:/, "")}` : s.primary;
  return (
    <Card
      title={byModel ? "以模型盲标为准的检测器评分（未做人工标注）" : "以人工盲标为准的检测器评分"}
      subtitle={`已标注 ${s.labeled}/${s.sample} 条（以 ${who} 的标签为准；其中判为越权 ${s.positives} 条）${s.inter_annotator ? `；标注者一致性 κ=${s.inter_annotator.kappa}（共同 ${s.inter_annotator.items} 条）` : "；单一标注者"}`}
    >
      {byModel && (
        <p className="mb-3 text-[13px] text-ink-2">
          这里的参照标签由大模型按人工盲标页的同一口径、只看同一份盲视图给出，不是人工标注。它衡量的是各判定方法与一个独立模型的一致程度，不等于准确率；LLM 裁判与参照都是模型，二者一致尤其不能说明判对了。
        </p>
      )}
      <DataTable
        head={["方法", "越权召回", "越权误报率", "真实写入召回", "Cohen's κ", "首个违规步骤一致"]}
        rows={rows.map(([, o]) => [
          o.label,
          `${o.violation.tp}/${o.violation.tp + o.violation.fn}`,
          `${o.violation.fp}/${o.violation.fp + o.violation.tn}`,
          `${o.side_effect.tp}/${o.side_effect.tp + o.side_effect.fn}`,
          o.kappa === null ? "—" : o.kappa.toFixed(2),
          frac(o.first_step),
        ])}
      />
    </Card>
  );
}

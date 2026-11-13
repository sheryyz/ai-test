import type { ReasoningSummary, ScoreDim, ScoreMethod, Scorecard as ScorecardData, Legend } from "../lib/api";
import { tipHandlers, useTooltip } from "./ui";

// Grades are an assessment, so they use the reserved status palette -- always with the letter and its word.
export const GRADE_META: Record<string, { word: string; color: string; wash: string }> = {
  A: { word: "可靠", color: "var(--good)", wash: "var(--good-wash)" },
  B: { word: "基本可靠", color: "var(--warning)", wash: "var(--warning-wash)" },
  C: { word: "有风险", color: "var(--serious)", wash: "var(--warning-wash)" },
  D: { word: "不可靠", color: "var(--critical)", wash: "var(--critical-wash)" },
};

export function GradeBadge({ grade, size = "md", withWord = true }: { grade: string | null; size?: "sm" | "md" | "lg"; withWord?: boolean }) {
  if (!grade) return <span className="text-[11px] text-muted">样本不足</span>;
  const m = GRADE_META[grade];
  const box = size === "lg" ? "size-10 text-lg" : size === "sm" ? "size-5 text-[11px]" : "size-7 text-sm";
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`grid ${box} shrink-0 place-items-center rounded-md font-bold text-white`} style={{ background: m.color }}>
        {grade}
      </span>
      {withWord && <span className={`${size === "lg" ? "text-sm" : "text-xs"} font-medium text-ink`}>{m.word}</span>}
    </span>
  );
}

function pctText(x: number | null | undefined, digits = 0): string {
  return x === null || x === undefined ? "—" : `${(x * 100).toFixed(digits)}%`;
}

/** One meter per dimension: rate fill, 95% Wilson interval whisker, N, grade. */
export function ScoreMeters({ dims, method }: { dims: ScoreDim[]; method?: ScoreMethod }) {
  const tip = useTooltip();
  return (
    <div className="space-y-3">
      {dims.map((d) => (
        <div key={d.key} className="grid items-center gap-x-4 gap-y-1 sm:grid-cols-[150px_minmax(0,1fr)_150px_96px]">
          <div>
            <div className="text-[13px] font-medium text-ink">{d.label}</div>
            <div className="text-[11px] leading-snug text-muted">{d.means}</div>
          </div>
          <div
            tabIndex={0}
            className="relative h-3 rounded-[4px]"
            style={{ background: "var(--surface-3)" }}
            aria-label={`${d.label} ${d.den ? `${d.num}/${d.den}` : "不适用"}`}
            {...tipHandlers(tip, () => (
              <div className="space-y-0.5">
                <div className="font-semibold">
                  {d.label}：{d.den ? `${d.num}/${d.den}（${pctText(d.rate, 1)}）` : "不适用"}
                </div>
                {d.ci && <div className="text-ink-2">95% 置信区间 {pctText(d.ci[0], 1)} – {pctText(d.ci[1], 1)}</div>}
                <div className="text-muted">{d.means}</div>
                {method && d.den > 0 && d.den < method.min_n && <div className="text-muted">少于 {method.min_n} 次执行，不评级</div>}
              </div>
            ))}
          >
            {d.rate !== null && <span className="absolute inset-y-0 left-0 rounded-[4px]" style={{ width: `${d.rate * 100}%`, background: "var(--seq-500)" }} />}
            {d.ci && (
              <span aria-hidden className="absolute top-1/2 h-[2px] -translate-y-1/2" style={{ left: `${d.ci[0] * 100}%`, width: `${Math.max(0.6, (d.ci[1] - d.ci[0]) * 100)}%`, background: "var(--ink)" }}>
                <span className="absolute -top-[4px] left-0 h-[10px] w-[2px]" style={{ background: "var(--ink)" }} />
                <span className="absolute -top-[4px] right-0 h-[10px] w-[2px]" style={{ background: "var(--ink)" }} />
              </span>
            )}
          </div>
          <div className="tabular text-xs text-ink-2">
            {d.den ? (
              <>
                <b className="text-ink">{pctText(d.rate, 1)}</b>
                <span className="text-muted">
                  {" "}
                  {d.num}/{d.den}
                </span>
              </>
            ) : (
              <span className="text-muted">不适用</span>
            )}
          </div>
          <div>{d.den ? <GradeBadge grade={d.grade} size="sm" /> : null}</div>
        </div>
      ))}
    </div>
  );
}

export function MethodNote({ method }: { method: ScoreMethod }) {
  const g = method.grades.map((x) => `${x.grade}：下限 ≥ ${Math.round(x.lower_bound_at_least * 100)}%`).join("；");
  return (
    <p className="text-[11px] leading-relaxed text-muted">
      评级规则（公开、固定）：每个维度取 95% Wilson 置信区间的<b>下限</b>评级——{g}；少于 {method.min_n} 次执行不评级。整体评级{method.overall}。线条两端是置信区间，样本越少区间越宽。
    </p>
  );
}

export function OverallLine({ card }: { card: ScorecardData }) {
  const weakest = card.dimensions.find((d) => d.key === card.weakest);
  return (
    <div className="flex flex-wrap items-center gap-4">
      <GradeBadge grade={card.overall} size="lg" />
      <div className="text-sm text-ink-2">
        {card.overall ? (
          <>
            整体评级取最弱的一项{weakest ? <>：<b className="text-ink">{weakest.label}</b>（{weakest.num}/{weakest.den}）</> : null}
          </>
        ) : (
          "执行次数太少，暂不评级"
        )}
        <div className="text-[11px] text-muted">
          {card.executions} 次执行 · {card.cases} 个场景{card.errors ? ` · ${card.errors} 次执行出错（不计入分母）` : ""}
        </div>
      </div>
    </div>
  );
}

const CAUSE_ORDER = ["overridden", "belief_error", "knowing_violation", "request_as_consent", "unclassified", "no_reasoning"];

/** Counts per cause as a plain table row set; six classes read better as numbers than as six hues. */
export function ReasoningCounts({ summary, legend }: { summary: ReasoningSummary; legend: Legend[] }) {
  const tip = useTooltip();
  const by = Object.fromEntries(legend.map((l) => [l.key, l]));
  return (
    <div className="grid gap-2 sm:grid-cols-3">
      {CAUSE_ORDER.map((k) => (
        <div key={k} tabIndex={0} className="rounded-lg p-3" style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }} {...tipHandlers(tip, () => <div className="max-w-xs">{by[k]?.means}</div>)}>
          <div className="text-[11px] text-ink-2">{by[k]?.label ?? k}</div>
          <div className="tabular mt-0.5 text-xl font-semibold text-ink">{summary.by_cause[k] ?? 0}</div>
        </div>
      ))}
    </div>
  );
}

import { useState, type ReactNode } from "react";
import type { Outcome, Ratio } from "../lib/api";
import { OUTCOME_META, frac, pct } from "../lib/util";
import { Segmented, tipHandlers, useTooltip } from "./ui";

// ------------------------------------------------------------------ sequential heatmap

const SEQ = ["--seq-100", "--seq-200", "--seq-300", "--seq-400", "--seq-500", "--seq-600", "--seq-700"];

function seqStep(rate: number): number {
  return Math.min(SEQ.length - 1, Math.floor(rate * SEQ.length));
}

export interface HeatRow {
  key: string;
  label: string;
  sub?: string;
}
export interface HeatCol {
  key: string;
  label: string;
  sub?: string;
  swatch?: string;
}

export function Heatmap({
  rows,
  cols,
  cell,
  metricLabel,
  goodWhenHigh = false,
  onCellClick,
}: {
  rows: HeatRow[];
  cols: HeatCol[];
  cell: (row: string, col: string) => Ratio | null;
  metricLabel: string;
  goodWhenHigh?: boolean;
  onCellClick?: (row: string, col: string) => void;
}) {
  const tip = useTooltip();
  const [view, setView] = useState<"chart" | "table">("chart");
  return (
    <div>
      <div className="mb-3 flex items-center justify-between gap-3">
        <Legend metricLabel={metricLabel} goodWhenHigh={goodWhenHigh} />
        <Segmented label="视图" value={view} onChange={setView} options={[{ value: "chart", label: "图" }, { value: "table", label: "表" }]} />
      </div>
      {view === "table" ? (
        <DataTable
          head={["类别", ...cols.map((c) => c.label)]}
          rows={rows.map((r) => [`${r.key} ${r.label}`, ...cols.map((c) => {
            const v = cell(r.key, c.key);
            return v ? `${pct(v)}（${frac(v)}）` : "—";
          })])}
        />
      ) : (
        <div className="scroll-x">
          <div className="grid gap-[2px]" style={{ gridTemplateColumns: `minmax(170px, 1.4fr) repeat(${cols.length}, minmax(92px, 1fr))` }}>
            <div />
            {cols.map((c) => (
              <div key={c.key} className="px-1 pb-1.5 text-xs">
                <div className="flex items-center gap-1.5 font-medium text-ink">
                  {c.swatch && <span aria-hidden className="size-2 rounded-full" style={{ background: c.swatch }} />}
                  {c.label}
                </div>
                {c.sub && <div className="truncate text-[11px] text-muted">{c.sub}</div>}
              </div>
            ))}
            {rows.map((r) => (
              <Row key={r.key}>
                <div className="flex flex-col justify-center pr-2">
                  <span className="text-xs font-medium text-ink">
                    <span className="mono mr-1.5 text-muted">{r.key}</span>
                    {r.label}
                  </span>
                  {r.sub && <span className="text-[11px] text-muted">{r.sub}</span>}
                </div>
                {cols.map((c) => {
                  const v = cell(r.key, c.key);
                  const has = v && v.rate !== null;
                  const step = has ? seqStep(v.rate as number) : 0;
                  const zero = has && v.num === 0;
                  const bg = !has ? "var(--surface-2)" : zero ? "var(--surface-2)" : `var(${SEQ[step]})`;
                  const ink = has && !zero && step >= 3 ? "#ffffff" : "var(--ink)";
                  return (
                    <button
                      key={c.key}
                      type="button"
                      className="lift flex h-12 flex-col items-center justify-center rounded-[4px] text-center"
                      style={{ background: bg, color: ink, cursor: onCellClick ? "pointer" : "default" }}
                      onClick={() => onCellClick?.(r.key, c.key)}
                      {...tipHandlers(tip, () => (
                        <div>
                          <div className="text-sm font-semibold">{has ? pct(v) : "无数据"}</div>
                          <div className="text-ink-2">
                            {r.key} {r.label} · {c.label}
                          </div>
                          <div className="text-muted">
                            {metricLabel}：{frac(v)}
                          </div>
                        </div>
                      ))}
                    >
                      <span className="tabular text-sm font-semibold">{has ? pct(v) : "—"}</span>
                      <span className="tabular text-[10px] opacity-75">{has ? frac(v) : ""}</span>
                    </button>
                  );
                })}
              </Row>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Row({ children }: { children: ReactNode }) {
  return <>{children}</>;
}

function Legend({ metricLabel, goodWhenHigh }: { metricLabel: string; goodWhenHigh: boolean }) {
  return (
    <div className="flex items-center gap-2 text-[11px] text-ink-2">
      <span>{metricLabel}</span>
      <span className="text-muted">0%</span>
      <span className="flex overflow-hidden rounded-sm">
        {SEQ.map((s) => (
          <span key={s} className="h-2.5 w-5" style={{ background: `var(${s})` }} />
        ))}
      </span>
      <span className="text-muted">100%</span>
      <span className="text-muted">（{goodWhenHigh ? "越深越好" : "越深越差"}；灰色为 0）</span>
    </div>
  );
}

// ------------------------------------------------------------------ grouped horizontal bars

export interface BarSeries {
  key: string;
  label: string;
  color: string;
}

export function GroupedBars({
  rows,
  series,
  value,
  metricLabel,
}: {
  rows: HeatRow[];
  series: BarSeries[];
  value: (row: string, series: string) => Ratio | null;
  metricLabel: string;
}) {
  const tip = useTooltip();
  const [view, setView] = useState<"chart" | "table">("chart");
  const peak = Math.max(0, ...rows.flatMap((r) => series.map((s) => value(r.key, s.key)?.rate ?? 0)));
  const max = [0.1, 0.2, 0.25, 0.5, 1].find((m) => peak <= m) ?? 1;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => t * max);
  return (
    <div>
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3 text-[11px] text-ink-2">
          {series.map((s) => (
            <span key={s.key} className="inline-flex items-center gap-1.5">
              <span aria-hidden className="h-2.5 w-3.5 rounded-[2px]" style={{ background: s.color }} />
              {s.label}
            </span>
          ))}
        </div>
        <Segmented label="视图" value={view} onChange={setView} options={[{ value: "chart", label: "图" }, { value: "table", label: "表" }]} />
      </div>
      {view === "table" ? (
        <DataTable
          head={["类别", ...series.map((s) => s.label)]}
          rows={rows.map((r) => [`${r.key} ${r.label}`, ...series.map((s) => {
            const v = value(r.key, s.key);
            return v ? `${pct(v)}（${frac(v)}）` : "—";
          })])}
        />
      ) : (
        <div className="grid items-center gap-x-3" style={{ gridTemplateColumns: "minmax(150px, 220px) 1fr" }}>
          <div />
          <div className="relative h-4 text-[10px] text-muted">
            {ticks.map((t) => (
              <span key={t} className="tabular absolute -translate-x-1/2" style={{ left: `${(t / max) * 100}%` }}>
                {+(t * 100).toFixed(1)}%
              </span>
            ))}
          </div>
          {rows.map((r) => (
            <BarRow key={r.key} label={`${r.key} ${r.label}`}>
              <div className="relative py-1.5">
                {ticks.map((t) => (
                  <span key={t} aria-hidden className="absolute inset-y-0 w-px" style={{ left: `${(t / max) * 100}%`, background: "var(--grid)" }} />
                ))}
                <div className="relative flex flex-col gap-[2px]">
                  {series.map((s) => {
                    const v = value(r.key, s.key);
                    const w = v?.rate ? (v.rate / max) * 100 : 0;
                    return (
                      <div
                        key={s.key}
                        tabIndex={0}
                        className="flex h-[12px] items-center"
                        {...tipHandlers(tip, () => (
                          <div>
                            <div className="text-sm font-semibold">{pct(v, 1)}</div>
                            <div className="text-ink-2">
                              {s.label} · {r.key} {r.label}
                            </div>
                            <div className="text-muted">
                              {metricLabel}：{frac(v)}
                            </div>
                          </div>
                        ))}
                      >
                        <span className="h-full rounded-r-[4px]" style={{ width: `${w}%`, minWidth: w > 0 ? 3 : 0, background: s.color }} />
                        {v && v.num > 0 && <span className="tabular ml-1.5 text-[11px] text-ink-2">{pct(v)} · {frac(v)}</span>}
                      </div>
                    );
                  })}
                </div>
              </div>
            </BarRow>
          ))}
        </div>
      )}
    </div>
  );
}

function BarRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <div className="truncate border-t border-line py-1.5 text-xs text-ink-2">{label}</div>
      <div className="border-t border-line">{children}</div>
    </>
  );
}

// ------------------------------------------------------------------ single-series horizontal bars

export function HBars({ items, color = "var(--s1)", unit = "次" }: { items: { label: string; value: number; sub?: string }[]; color?: string; unit?: string }) {
  const tip = useTooltip();
  const max = Math.max(1, ...items.map((i) => i.value));
  return (
    <div className="flex flex-col gap-1.5">
      {items.map((i) => (
        <div key={i.label} className="grid items-center gap-3" style={{ gridTemplateColumns: "minmax(140px, 200px) 1fr" }}>
          <span className="mono truncate text-[11px] text-ink-2" title={i.label}>
            {i.label}
          </span>
          <div className="flex items-center" tabIndex={0} {...tipHandlers(tip, () => <div><b>{i.value}</b> {unit}<div className="text-muted">{i.label}{i.sub ? ` · ${i.sub}` : ""}</div></div>)}>
            <span className="h-3 rounded-r-[4px]" style={{ width: `${(i.value / max) * 100}%`, minWidth: 3, background: color }} />
            <span className="tabular ml-1.5 text-[11px] text-ink-2">{i.value}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ outcome distribution

export function OutcomeBar({ counts, total, compact = false }: { counts: Partial<Record<Outcome, number>>; total: number; compact?: boolean }) {
  const tip = useTooltip();
  const order: Outcome[] = ["PASS", "FAIL", "ERROR", "UNSUPPORTED"];
  return (
    <div>
      <div className="flex h-3 gap-[2px] overflow-hidden rounded-[4px]">
        {order
          .filter((o) => (counts[o] ?? 0) > 0)
          .map((o) => (
            <span
              key={o}
              tabIndex={0}
              style={{ flexGrow: counts[o], background: OUTCOME_META[o].color }}
              {...tipHandlers(tip, () => (
                <div>
                  <b>{counts[o]}</b> / {total} · {o} {OUTCOME_META[o].label}
                </div>
              ))}
            />
          ))}
      </div>
      <div className={`mt-1.5 flex flex-wrap text-[11px] text-ink-2 ${compact ? "gap-2" : "gap-3"}`}>
        {order.filter((o) => !compact || (counts[o] ?? 0) > 0 || o === "FAIL").map((o) => (
          <span key={o} className="inline-flex items-center gap-1">
            <span aria-hidden className="size-2 rounded-full" style={{ background: OUTCOME_META[o].color }} />
            {OUTCOME_META[o].label} <span className="tabular font-semibold text-ink">{counts[o] ?? 0}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ outcome cell (matrix square)

export function OutcomeCell({ outcome, onClick, tooltip, label }: { outcome: Outcome | null; onClick?: () => void; tooltip: () => ReactNode; label: string }) {
  const tip = useTooltip();
  const m = outcome ? OUTCOME_META[outcome] : null;
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className="lift pop grid size-[22px] place-items-center rounded-[4px] text-[11px] font-bold leading-none"
      style={{ background: m ? m.color : "var(--surface-3)", color: m ? "#fff" : "var(--muted)", cursor: onClick ? "pointer" : "default" }}
      {...tipHandlers(tip, tooltip)}
    >
      {m ? m.icon : "·"}
    </button>
  );
}

// ------------------------------------------------------------------ table view twin

export function DataTable({ head, rows }: { head: string[]; rows: (string | number)[][] }) {
  return (
    <div className="scroll-x">
      <table className="w-full text-left text-xs">
        <thead>
          <tr className="hairline-b text-muted">
            {head.map((h) => (
              <th key={h} className="px-2 py-1.5 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="hairline-b">
              {r.map((c, j) => (
                <td key={j} className={`px-2 py-1.5 ${j ? "tabular" : ""} text-ink-2`}>
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import type { AssertionStatus } from "../lib/api";
import { OUTCOME_META } from "../lib/util";

// ------------------------------------------------------------------ tooltip (one per app)

interface Tip {
  x: number;
  y: number;
  content: ReactNode;
}
const TooltipCtx = createContext<{ show: (e: { clientX: number; clientY: number }, c: ReactNode) => void; hide: () => void }>({
  show: () => {},
  hide: () => {},
});

export function TooltipProvider({ children }: { children: ReactNode }) {
  const [tip, setTip] = useState<Tip | null>(null);
  const show = useCallback((e: { clientX: number; clientY: number }, content: ReactNode) => setTip({ x: e.clientX, y: e.clientY, content }), []);
  const hide = useCallback(() => setTip(null), []);
  return (
    <TooltipCtx.Provider value={{ show, hide }}>
      {children}
      {tip && (
        <div
          role="tooltip"
          className="pointer-events-none fixed z-50 max-w-sm rounded-lg px-3 py-2 text-xs shadow-lg"
          style={{
            left: Math.min(tip.x + 14, window.innerWidth - 340),
            top: Math.min(tip.y + 14, window.innerHeight - 160),
            background: "var(--surface)",
            border: "1px solid var(--border-strong)",
            color: "var(--ink)",
          }}
        >
          {tip.content}
        </div>
      )}
    </TooltipCtx.Provider>
  );
}

export function useTooltip() {
  return useContext(TooltipCtx);
}

/** Hover and keyboard focus show the same tooltip. */
export function tipHandlers(tip: ReturnType<typeof useTooltip>, content: () => ReactNode) {
  return {
    onPointerMove: (e: React.PointerEvent) => tip.show(e, content()),
    onPointerLeave: () => tip.hide(),
    onFocus: (e: React.FocusEvent) => {
      const r = (e.target as HTMLElement).getBoundingClientRect();
      tip.show({ clientX: r.right, clientY: r.bottom }, content());
    },
    onBlur: () => tip.hide(),
  };
}

// ------------------------------------------------------------------ status

export function StatusBadge({ status, size = "md" }: { status: AssertionStatus; size?: "sm" | "md" }) {
  const m = OUTCOME_META[status];
  const pad = size === "sm" ? "px-1.5 py-0.5 text-[11px]" : "px-2 py-0.5 text-xs";
  return (
    <span className={`inline-flex items-center gap-1 rounded-full font-semibold ${pad}`} style={{ background: m.wash, color: "var(--ink)" }}>
      <span
        aria-hidden
        className="inline-grid size-3.5 place-items-center rounded-full text-[9px] leading-none text-white"
        style={{ background: m.color }}
      >
        {m.icon}
      </span>
      {status}
      <span className="font-normal text-ink-2">{m.label}</span>
    </span>
  );
}

// ------------------------------------------------------------------ layout bits

export function Card({ title, subtitle, right, children, className = "" }: { title?: ReactNode; subtitle?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card min-w-0 p-5 ${className}`}>
      {(title || right) && (
        <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            {title && <h2 className="text-[15px] font-semibold text-ink">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
          </div>
          {right}
        </header>
      )}
      {children}
    </section>
  );
}

export function StatTile({ label, value, sub, accent }: { label: string; value: ReactNode; sub?: ReactNode; accent?: string }) {
  return (
    <div className="card relative overflow-hidden px-4 py-3.5">
      {accent && <span className="absolute inset-y-0 left-0 w-1" style={{ background: accent }} />}
      <div className="text-xs text-ink-2">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-ink">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
    </div>
  );
}

export function Segmented<T extends string>({ value, options, onChange, label }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-lg p-0.5" style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}>
      {options.map((o) => (
        <button
          key={o.value}
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className="rounded-md px-2.5 py-1 text-xs font-medium transition-colors"
          style={value === o.value ? { background: "var(--surface)", color: "var(--ink)", boxShadow: "0 1px 2px rgba(0,0,0,.08)" } : { color: "var(--ink-2)" }}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Loading({ what = "数据" }: { what?: string }) {
  return <div className="py-16 text-center text-sm text-muted">正在读取{what}…</div>;
}

export function ErrorNote({ error }: { error: string }) {
  return (
    <div className="card my-6 p-4 text-sm" style={{ borderColor: "var(--critical)" }}>
      <strong className="text-ink">读取失败</strong>
      <span className="ml-2 text-ink-2">{error}</span>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-lg border border-dashed border-line px-4 py-10 text-center text-sm text-muted">{children}</div>;
}

export function Pill({ children, color, title }: { children: ReactNode; color?: string; title?: string }) {
  return (
    <span title={title} className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium" style={{ background: "var(--surface-2)", border: "1px solid var(--border)", color: "var(--ink-2)" }}>
      {color && <span aria-hidden className="size-1.5 rounded-full" style={{ background: color }} />}
      {children}
    </span>
  );
}

export function JsonBlock({ value, max = 400 }: { value: unknown; max?: number }) {
  const text = JSON.stringify(value, null, 2) ?? "null";
  return (
    <pre className="mono overflow-auto rounded-md p-2.5 text-[11px] leading-relaxed text-ink-2" style={{ background: "var(--surface-2)", maxHeight: max }}>
      {text}
    </pre>
  );
}

// ------------------------------------------------------------------ state diff for any table

type Row = Record<string, unknown>;
interface Change {
  pk: Row;
  before: Row | null;
  after: Row | null;
  changed: string[];
}

function cell(v: unknown): string {
  if (v === null || v === undefined) return "";
  return typeof v === "string" ? v : JSON.stringify(v);
}

/** Row-level changes of every table in a state diff; new rows green, deleted red, changed cells amber. */
export function GenericDiff({ diff }: { diff: { tables: Record<string, { inserted: Change[]; deleted: Change[]; updated: Change[] }> } | null }) {
  if (!diff) return <p className="text-sm text-muted">没有状态访问能力（UNSUPPORTED）。</p>;
  const tables = Object.entries(diff.tables).filter(([, t]) => t.inserted.length + t.deleted.length + t.updated.length);
  if (!tables.length) return <p className="text-sm text-muted">业务数据没有任何变化。</p>;
  return (
    <div className="space-y-3">
      {tables.map(([name, t]) => {
        const rows: [string, Change][] = [...t.inserted.map((c) => ["新增", c] as [string, Change]), ...t.updated.map((c) => ["修改", c] as [string, Change]), ...t.deleted.map((c) => ["删除", c] as [string, Change])];
        // key columns first, then whatever changed, then the rest (wide rows keep the change in view)
        const keys = [...new Set(rows.flatMap(([, c]) => Object.keys(c.pk)))];
        const changed = [...new Set(rows.flatMap(([, c]) => c.changed))];
        const cols = [...new Set([...keys, ...changed, ...rows.flatMap(([, c]) => Object.keys(c.after ?? c.before ?? {}))])];
        return (
          <div key={name}>
            <div className="mono mb-1 text-xs font-semibold text-ink">{name}</div>
            <div className="scroll-x">
              <table className="w-full text-xs">
                <thead>
                  <tr className="hairline-b text-muted">
                    <th className="px-1.5 py-1 text-left font-medium" />
                    {cols.map((c) => (
                      <th key={c} className="px-1.5 py-1 text-left font-medium">
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map(([op, c], i) => {
                    const wash = op === "新增" ? "var(--good-wash)" : op === "删除" ? "var(--critical-wash)" : undefined;
                    return (
                      <tr key={i} className="hairline-b" style={{ background: wash }}>
                        <td className="px-1.5 py-1 font-semibold text-ink">{op}</td>
                        {cols.map((col) => {
                          const changed = op === "修改" && c.changed.includes(col);
                          return (
                            <td key={col} className="mono max-w-[16rem] truncate whitespace-nowrap px-1.5 py-1 text-ink" title={cell((c.after ?? c.before)?.[col])} style={changed ? { background: "var(--warning-wash)" } : undefined}>
                              {changed ? `${cell(c.before?.[col])} → ${cell(c.after?.[col])}` : cell((c.after ?? c.before)?.[col])}
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}
    </div>
  );
}

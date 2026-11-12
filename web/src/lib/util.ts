import { useCallback, useEffect, useState } from "react";
import type { AuthStatus, Outcome, Ratio } from "./api";

export const CATEGORY_NAMES: Record<string, string> = {
  C1: "正常查询与有效确认",
  C2: "多轮修改与重新确认",
  C3: "撤销、拒绝与取消",
  C4: "边界值与参数异常",
  C5: "工具返回注入",
  C6: "RAG 检索与投毒",
  C7: "工具故障与恢复",
  C8: "混合与长对话",
};

export const OUTCOME_META: Record<Outcome | "SKIPPED", { label: string; icon: string; color: string; wash: string }> = {
  PASS: { label: "通过", icon: "✓", color: "var(--good)", wash: "var(--good-wash)" },
  FAIL: { label: "失败", icon: "✕", color: "var(--critical)", wash: "var(--critical-wash)" },
  ERROR: { label: "错误", icon: "!", color: "var(--warning)", wash: "var(--warning-wash)" },
  UNSUPPORTED: { label: "不可测", icon: "–", color: "var(--muted)", wash: "var(--surface-3)" },
  SKIPPED: { label: "未触发", icon: "·", color: "var(--muted)", wash: "var(--surface-3)" },
};

export const AUTH_META: Record<AuthStatus, { label: string; color: string; wash: string; authorizing: boolean }> = {
  none: { label: "无授权", color: "var(--muted)", wash: "transparent", authorizing: false },
  pending: { label: "待确认", color: "var(--warning)", wash: "var(--warning-wash)", authorizing: false },
  confirmed: { label: "已确认", color: "var(--good)", wash: "var(--good-wash)", authorizing: true },
  modified: { label: "已修改·确认失效", color: "var(--serious)", wash: "var(--warning-wash)", authorizing: false },
  revoked: { label: "已撤销", color: "var(--muted)", wash: "var(--surface-3)", authorizing: false },
  consumed: { label: "已使用", color: "var(--s1)", wash: "var(--s1-wash)", authorizing: false },
};

export const ACTION_NAMES: Record<string, string> = { create_order: "预订", cancel_order: "取消订单" };

export function pct(r: Ratio | null | undefined, digits = 0): string {
  if (!r || r.rate === null) return "—";
  return `${(r.rate * 100).toFixed(digits)}%`;
}

export function frac(r: Ratio | null | undefined): string {
  if (!r) return "—";
  return `${r.num}/${r.den}`;
}

export function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 10_000) return `${(n / 1000).toFixed(1)}K`;
  return n.toLocaleString("en-US");
}

export function short(value: unknown, limit = 120): string {
  const text = typeof value === "string" ? value : JSON.stringify(value);
  if (text === undefined) return "";
  return text.length <= limit ? text : `${text.slice(0, limit - 1)}…`;
}

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): { data: T | null; error: string | null; loading: boolean; reload: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(fn, deps);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    run()
      .then((d) => alive && (setData(d), setError(null)))
      .catch((e: Error) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [run, tick]);
  return { data, error, loading, reload: () => setTick((t) => t + 1) };
}

export function useHashRoute(): string[] {
  const read = () => window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  const [parts, setParts] = useState(read);
  useEffect(() => {
    const onChange = () => setParts(read());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return parts;
}

export function href(...parts: (string | number)[]): string {
  return `#/${parts.map((p) => encodeURIComponent(String(p))).join("/")}`;
}

export function versionColor(version: string): string {
  return version === "v2" ? "var(--s2)" : "var(--s1)";
}

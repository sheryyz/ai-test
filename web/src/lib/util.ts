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

export const ACTION_NAMES: Record<string, string> = {
  create_order: "预订",
  cancel_order: "取消订单",
  approve: "审批通过",
  cancel: "取消预订",
  update_baggage: "修改行李",
  update_flights: "改签航班",
  update_passengers: "修改乘客",
  book: "预订",
};

/** What the authorization state at the moment of a call means, said to a user. */
export const STATUS_STORY: Record<AuthStatus, string> = {
  none: "用户从来没有要求过这个操作。",
  pending: "用户提出了请求，但还没有确认。",
  confirmed: "用户已经确认了这些参数。",
  modified: "用户确认之后又改了参数：旧的确认随之失效，新参数还没有被确认过。",
  revoked: "用户已经撤回了同意。",
  consumed: "这次确认已经用过一次，不能再用来执行第二次。",
};

export const TRIGGER_VERB: Record<string, string> = { request: "请求", modify: "修改", confirm: "确认", revoke: "撤销", decline: "拒绝", inquire: "仅询问", consume: "执行" };

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

// Fixed categorical order: V1 slot 1, V2 slot 2, V2.1 slot 3. Slot 3 is the only remaining hue that
// clears every all-pairs check against slots 1 and 2 in both modes (validate_palette.js); its light-mode
// contrast is below 3:1, so a version colour is always shown next to its text label. The swimlane's
// state-write lane shares the hue but never appears as a competing series in the same chart.
const VERSION_COLORS: Record<string, string> = { v1: "var(--s1)", v2: "var(--s2)", "v2.1": "var(--s3)" };

export function versionColor(version: string): string {
  return VERSION_COLORS[version] ?? "var(--muted)";
}

// ------------------------------------------------------------------ plain-language vocabulary

/** Test plans as a user sees them: what a suite is for, in one line. Unknown suites fall back to their id. */
export const PLANS: Record<string, { name: string; what: string; primary?: boolean }> = {
  acceptance: { name: "快速体检", what: "精选的代表性场景：中途改主意、撤回同意、工具返回里藏指令、执行后超时等", primary: true },
  main: { name: "完整测试", what: "覆盖 8 类风险的全部场景，适合发版前做一次全面检查", primary: true },
  core: { name: "完整测试", what: "这个业务的全部场景，适合发版前做一次全面检查", primary: true },
  attacks: { name: "抗注入测试", what: "大模型生成的间接注入攻击，藏在工具返回里，看 Agent 会不会被诱导越权", primary: true },
  "attacks-r2": { name: "抗注入测试 · 第 2 轮", what: "根据第 1 轮 Agent 的反应改写后的进化版注入攻击" },
  smoke: { name: "冒烟测试", what: "9 个基础场景，确认测试链路畅通" },
  variants: { name: "换种说法", what: "同一场景换不同措辞，检验 Agent 的判断是否稳定" },
  holdout: { name: "留出测试集", what: "一次性生成、从未参与调优的场景，检验修复是否真的泛化" },
};

export function planName(suite: string): string {
  return PLANS[suite]?.name ?? suite;
}

/** What went wrong, in words a user understands (the backend's defect kinds and finding kinds). */
export const ISSUE_TEXT = {
  side_effect: "未经同意就改了数据",
  attempt: "试图越权，被拦下",
  claim: "说的和做的不一致",
  task: "任务没完成",
} as const;

export const GLOSSARY: Record<string, string> = {
  越权: "Agent 在用户没有确认、确认已失效（用户改了参数）或已撤回同意时，调用了需要授权的操作。",
  真实写入: "越权操作真的改动了业务数据库（平台对比了执行前后的数据库快照），是最严重的一类问题。",
  回放: "复现录制下来的真实模型回复，不再调用模型：免费、几秒完成、每次结果相同；工具和数据库每次都真实执行。",
  "pass^k": "同一场景重复执行 k 次，k 次全部通过才算通过。衡量 Agent 是否稳定，而不是偶尔做对。",
  复测: "开发者修好后，用同一个场景（同样的初始数据、注入点）在修复版上重跑；每次都通过才算修复。",
  授权账本: "平台根据测试场景里标注的用户意图（请求、确认、修改、撤销）独立记账，Agent 看不到；每次敏感操作都对照这本账判定。",
};

export function timeAgo(iso: string): string {
  const d = new Date(iso);
  const s = (Date.now() - d.getTime()) / 1000;
  if (s < 60) return "刚刚";
  if (s < 3600) return `${Math.floor(s / 60)} 分钟前`;
  if (s < 86400) return `${Math.floor(s / 3600)} 小时前`;
  if (s < 86400 * 7) return `${Math.floor(s / 86400)} 天前`;
  return d.toLocaleDateString("zh-CN");
}

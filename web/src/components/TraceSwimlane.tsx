import { useMemo } from "react";
import type { AuthStatus, AuthTransition, Finding, SensitiveAttempt, TraceEvent } from "../lib/api";
import { ACTION_NAMES, AUTH_META, short } from "../lib/util";
import { tipHandlers, useTooltip } from "./ui";

const MIN_COL = 34;
const MAX_COL = 60;
const TARGET_WIDTH = 1180;
const LEFT = 108;
const TOP = 30;
const LANE_H = 46;
const BAND_H = 18;

type Lane = "user" | "agent" | "tool" | "state";
const LANES: { key: Lane; label: string; sub: string }[] = [
  { key: "user", label: "用户通道", sub: "可信" },
  { key: "agent", label: "Agent", sub: "模型与调用" },
  { key: "tool", label: "工具返回", sub: "低信任" },
  { key: "state", label: "业务状态", sub: "写入回执" },
];

function laneOf(e: TraceEvent): Lane {
  if (e.kind === "user_message") return "user";
  if (e.kind === "write_receipt") return "state";
  if (e.kind === "tool_result" || e.kind === "injection") return "tool";
  return "agent";
}

export interface SwimlaneProps {
  events: TraceEvent[];
  transitions: AuthTransition[];
  attempts: SensitiveAttempt[];
  findings: Finding[];
  selected: number | null;
  onSelect: (step: number) => void;
  showModelCalls: boolean;
}

export function TraceSwimlane({ events, transitions, attempts, findings, selected, onSelect, showModelCalls }: SwimlaneProps) {
  const tip = useTooltip();
  const shown = useMemo(() => events.filter((e) => showModelCalls || e.kind !== "llm_call"), [events, showModelCalls]);
  const COL = Math.max(MIN_COL, Math.min(MAX_COL, Math.floor(TARGET_WIDTH / Math.max(1, shown.length))));
  const col = useMemo(() => new Map(shown.map((e, i) => [e.step_id, i])), [shown]);
  const attemptByStep = useMemo(() => new Map(attempts.map((a) => [a.step, a])), [attempts]);
  const badSteps = new Map<number, string[]>();
  for (const f of findings) badSteps.set(f.first_bad_step, [...(badSteps.get(f.first_bad_step) ?? []), f.rule_id]);
  const firstBad = findings.length ? Math.min(...findings.map((f) => f.first_bad_step)) : null;

  const actions = useMemo(() => [...new Set(transitions.map((t) => t.action))], [transitions]);
  const bandsTop = TOP + LANE_H; // authorization bands sit right under the user lane
  const lanesTop = (lane: Lane) => {
    const idx = LANES.findIndex((l) => l.key === lane);
    return TOP + idx * LANE_H + (idx >= 1 ? actions.length * (BAND_H + 4) + 6 : 0);
  };
  const width = LEFT + shown.length * COL + 24;
  const height = lanesTop("state") + LANE_H + 22; // bottom row holds the violation label
  const x = (i: number) => LEFT + i * COL + COL / 2;
  const yMid = (lane: Lane) => lanesTop(lane) + LANE_H / 2;

  // authorization status per displayed column, per action
  const bands = actions.map((action) => {
    const ts = transitions.filter((t) => t.action === action).sort((a, b) => a.step - b.step);
    const statuses: { status: AuthStatus; version: number }[] = shown.map((e) => {
      let cur: { status: AuthStatus; version: number } = { status: "none", version: 0 };
      for (const t of ts) if (t.step <= e.step_id) cur = { status: t.to_status, version: t.version };
      return cur;
    });
    const segs: { from: number; to: number; status: AuthStatus; version: number }[] = [];
    statuses.forEach((s, i) => {
      const last = segs[segs.length - 1];
      if (last && last.status === s.status && last.version === s.version) last.to = i;
      else segs.push({ from: i, to: i, ...s });
    });
    return { action, segs };
  });

  // turn boundaries
  const turnStarts = shown.map((e, i) => ({ e, i })).filter(({ e }) => e.kind === "user_message");

  // causal connectors: attempt → its result / receipts
  const byCall = new Map<string, number[]>();
  shown.forEach((e, i) => {
    if (e.call_id) byCall.set(e.call_id, [...(byCall.get(e.call_id) ?? []), i]);
  });

  return (
    <div className="scroll-x rounded-lg" style={{ background: "var(--surface)" }}>
      <svg width={width} height={height} role="img" aria-label="三通道审计时间轴" style={{ display: "block" }}>
        {/* lane backgrounds and labels */}
        {LANES.map((l) => (
          <g key={l.key}>
            <rect x={0} y={lanesTop(l.key)} width={width} height={LANE_H} fill={l.key === "tool" ? "var(--surface-2)" : "transparent"} />
            <line x1={0} x2={width} y1={lanesTop(l.key) + LANE_H} y2={lanesTop(l.key) + LANE_H} stroke="var(--grid)" />
            <text x={12} y={lanesTop(l.key) + 20} fontSize={12} fontWeight={600} fill="var(--ink)">
              {l.label}
            </text>
            <text x={12} y={lanesTop(l.key) + 35} fontSize={10} fill="var(--muted)">
              {l.sub}
            </text>
          </g>
        ))}
        {/* authorization bands */}
        {bands.map((b, bi) => {
          const y = bandsTop + 3 + bi * (BAND_H + 4);
          return (
            <g key={b.action}>
              <text x={12} y={y + 13} fontSize={10} fill="var(--ink-2)">
                授权·{ACTION_NAMES[b.action] ?? b.action}
              </text>
              {b.segs.map((s) => {
                const meta = AUTH_META[s.status];
                const x0 = LEFT + s.from * COL + 1;
                const w = (s.to - s.from + 1) * COL - 2;
                const text = s.status === "confirmed" ? `${meta.label} v${s.version}` : meta.label;
                return (
                  <g key={`${s.from}-${s.status}`}>
                    <rect x={x0} y={y} width={w} height={BAND_H} rx={4} fill={meta.wash} stroke={s.status === "none" ? "var(--grid)" : meta.color} strokeWidth={1} />
                    {s.status !== "none" && <rect x={x0} y={y} width={3} height={BAND_H} rx={1.5} fill={meta.color} />}
                    {w > 56 && (
                      <text x={x0 + 8} y={y + 12.5} fontSize={10.5} fontWeight={600} fill="var(--ink)">
                        {text}
                      </text>
                    )}
                  </g>
                );
              })}
            </g>
          );
        })}
        {/* turn separators */}
        {turnStarts.map(({ e, i }) => (
          <g key={e.step_id}>
            <line x1={LEFT + i * COL} x2={LEFT + i * COL} y1={TOP - 6} y2={height} stroke="var(--axis)" />
            <text x={LEFT + i * COL + 5} y={TOP - 10} fontSize={10.5} fill="var(--ink-2)" fontWeight={600}>
              第 {e.turn_id} 轮
            </text>
          </g>
        ))}
        {/* first violation and selection highlights */}
        {firstBad !== null && col.has(firstBad) && (
          <g>
            <rect x={LEFT + (col.get(firstBad) as number) * COL} y={TOP - 4} width={COL} height={height - TOP + 4} fill="var(--critical-wash)" />
            <text x={x(col.get(firstBad) as number)} y={height - 6} fontSize={10} textAnchor="middle" fill="var(--critical)" fontWeight={700}>
              首个违规
            </text>
          </g>
        )}
        {selected !== null && col.has(selected) && (
          <rect x={LEFT + (col.get(selected) as number) * COL + 1} y={TOP - 4} width={COL - 2} height={height - TOP} rx={4} fill="none" stroke="var(--s1)" strokeWidth={1.5} />
        )}
        {/* connectors */}
        {[...byCall.values()].map((idxs) =>
          idxs.length > 1 ? (
            <polyline
              key={idxs.join("-")}
              points={idxs.map((i) => `${x(i)},${yMid(laneOf(shown[i]))}`).join(" ")}
              fill="none"
              stroke="var(--axis)"
              strokeWidth={1}
            />
          ) : null,
        )}
        {/* nodes */}
        {shown.map((e, i) => {
          const lane = laneOf(e);
          const cx = x(i);
          const cy = yMid(lane);
          const attempt = attemptByStep.get(e.step_id);
          return (
            <g
              key={e.step_id}
              tabIndex={0}
              role="button"
              aria-label={`step ${e.step_id} ${e.kind}`}
              style={{ cursor: "pointer", outline: "none" }}
              onClick={() => onSelect(e.step_id)}
              onKeyDown={(ev) => (ev.key === "Enter" || ev.key === " ") && onSelect(e.step_id)}
              {...tipHandlers(tip, () => <NodeTip e={e} attempt={attempt} rules={badSteps.get(e.step_id)} />)}
            >
              <rect x={cx - COL / 2} y={cy - LANE_H / 2} width={COL} height={LANE_H} fill="transparent" />
              <Node e={e} cx={cx} cy={cy} attempt={attempt} />
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function Node({ e, cx, cy, attempt }: { e: TraceEvent; cx: number; cy: number; attempt?: SensitiveAttempt }) {
  const ring = { stroke: "var(--surface)", strokeWidth: 2 };
  switch (e.kind) {
    case "user_message":
      return <circle cx={cx} cy={cy} r={8} fill="var(--s1)" {...ring} />;
    case "agent_message":
      return <rect x={cx - 7} y={cy - 7} width={14} height={14} rx={4} fill={e.meta?.with_tool_calls ? "var(--axis)" : "var(--ink-2)"} {...ring} />;
    case "agent_reasoning":
      return <circle cx={cx} cy={cy} r={4.5} fill="var(--muted)" {...ring} />;
    case "llm_call":
      return <circle cx={cx} cy={cy} r={3} fill="var(--axis)" />;
    case "tool_call_attempt": {
      const color = attempt ? (attempt.authorized ? "var(--good)" : "var(--critical)") : "var(--ink-2)";
      return (
        <g>
          <rect x={cx - 7} y={cy - 7} width={14} height={14} transform={`rotate(45 ${cx} ${cy})`} rx={2} fill={color} {...ring} />
          {attempt && (
            <text x={cx} y={cy + 3.5} fontSize={10} fontWeight={800} textAnchor="middle" fill="#fff">
              {attempt.authorized ? "✓" : "✕"}
            </text>
          )}
        </g>
      );
    }
    case "tool_result": {
      const bad = e.status && e.status !== "ok";
      return (
        <g>
          <rect x={cx - 6} y={cy - 6} width={12} height={12} rx={3} fill={e.injection_id ? "var(--s7)" : bad ? "var(--serious)" : "var(--muted)"} {...ring} />
          {bad && (
            <text x={cx} y={cy + 3.5} fontSize={9} fontWeight={800} textAnchor="middle" fill="#fff">
              !
            </text>
          )}
        </g>
      );
    }
    case "injection":
      return (
        <g>
          <path d={`M${cx} ${cy - 9} L${cx + 9} ${cy + 7} L${cx - 9} ${cy + 7} Z`} fill="var(--s7)" {...ring} />
          <text x={cx} y={cy + 5} fontSize={8.5} fontWeight={800} textAnchor="middle" fill="#fff">
            注
          </text>
        </g>
      );
    case "write_receipt":
      return (
        <g>
          <rect x={cx - 8} y={cy - 8} width={16} height={16} rx={4} fill="var(--s3)" {...ring} />
          <text x={cx} y={cy + 3.5} fontSize={9} fontWeight={800} textAnchor="middle" fill="#fff">
            写
          </text>
        </g>
      );
    default:
      return (
        <g>
          <circle cx={cx} cy={cy} r={7} fill="var(--warning)" {...ring} />
          <text x={cx} y={cy + 3.5} fontSize={9} fontWeight={800} textAnchor="middle" fill="#000">
            !
          </text>
        </g>
      );
  }
}

const KIND_LABEL: Record<string, string> = {
  user_message: "用户消息",
  llm_call: "模型调用",
  agent_reasoning: "可见推理摘要",
  tool_call_attempt: "工具调用",
  write_receipt: "写入回执",
  injection: "注入",
  tool_result: "工具返回",
  agent_message: "Agent 回复",
  error: "错误",
};

function NodeTip({ e, attempt, rules }: { e: TraceEvent; attempt?: SensitiveAttempt; rules?: string[] }) {
  let body = "";
  if (e.kind === "tool_call_attempt") body = `${e.tool}(${short(e.args, 90)})`;
  else if (e.kind === "tool_result") body = `${e.tool} → ${short(e.result, 100)}`;
  else if (e.kind === "write_receipt") body = short(e.result, 100);
  else if (e.kind === "injection") body = `${e.injection_id} · ${String(e.meta?.mode ?? "")}`;
  else if (e.kind === "llm_call") body = `${String(e.meta?.model ?? "")} · ${String(e.meta?.latency_ms ?? "")} ms`;
  else body = short(e.content ?? "", 140);
  return (
    <div className="space-y-1">
      <div className="text-[11px] text-muted">
        step {e.step_id} · 第 {e.turn_id} 轮 · {KIND_LABEL[e.kind]}
      </div>
      <div className="text-ink">{body}</div>
      {attempt && (
        <div className="font-semibold" style={{ color: attempt.authorized ? "var(--good-text)" : "var(--critical)" }}>
          {attempt.authorized ? "✓ 已授权" : "✕ 未授权"} · 当时授权状态 {AUTH_META[attempt.status_at_attempt].label}
          {attempt.version ? ` v${attempt.version}` : ""}
        </div>
      )}
      {rules && <div className="font-semibold text-critical">违规：{rules.join("、")}</div>}
    </div>
  );
}

export function SwimlaneLegend() {
  const item = (svg: React.ReactNode, label: string) => (
    <span className="inline-flex items-center gap-1.5">
      <svg width={16} height={16} aria-hidden>
        {svg}
      </svg>
      {label}
    </span>
  );
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-ink-2">
      {item(<circle cx={8} cy={8} r={6} fill="var(--s1)" />, "用户消息")}
      {item(<rect x={2} y={2} width={12} height={12} rx={3} fill="var(--ink-2)" />, "Agent 回复")}
      {item(<rect x={3} y={3} width={10} height={10} rx={2} transform="rotate(45 8 8)" fill="var(--good)" />, "已授权的敏感调用")}
      {item(<rect x={3} y={3} width={10} height={10} rx={2} transform="rotate(45 8 8)" fill="var(--critical)" />, "未授权的敏感调用")}
      {item(<rect x={3} y={3} width={10} height={10} rx={2} transform="rotate(45 8 8)" fill="var(--ink-2)" />, "普通工具调用")}
      {item(<path d="M8 1 L15 14 L1 14 Z" fill="var(--s7)" />, "注入 / 低信任内容")}
      {item(<rect x={2} y={2} width={12} height={12} rx={3} fill="var(--serious)" />, "工具错误")}
      {item(<rect x={1} y={1} width={14} height={14} rx={3} fill="var(--s3)" />, "写入回执")}
    </div>
  );
}

import { useMemo, useState } from "react";
import { OutcomeCell } from "../components/charts";
import { SwimlaneLegend, TraceSwimlane } from "../components/TraceSwimlane";
import { Card, ErrorNote, JsonBlock, Loading, Pill, Segmented, StatTile, StatusBadge } from "../components/ui";
import { api, type CaseBundle, type Finding, type SensitiveAttempt, type StateDiff, type StateSnapshot, type TraceEvent, type UserEvent } from "../lib/api";
import { ACTION_NAMES, AUTH_META, CATEGORY_NAMES, OUTCOME_META, href, short, useAsync } from "../lib/util";

const KIND_TEXT: Record<Finding["kind"], string> = {
  side_effect_violation: "真实写入",
  attempt_violation: "仅尝试，未写入",
  claim_violation: "陈述与状态不符",
};

export function TraceExplorer({ runId, caseId, rep }: { runId: string; caseId: string; rep: number }) {
  const bundle = useAsync(() => api.caseBundle(runId, caseId, rep), [runId, caseId, rep]);
  const run = useAsync(() => api.run(runId), [runId]);
  const [selected, setSelected] = useState<number | null>(null);
  const [modelCalls, setModelCalls] = useState<"hide" | "show">("hide");

  if (bundle.error) return <ErrorNote error={bundle.error} />;
  if (!bundle.data) return <Loading what="证据" />;
  const b = bundle.data;
  const v = b.verdict;
  const attempts = b.auth?.attempts ?? [];
  const firstBad = (v.metrics.first_bad_step as number | null) ?? null;
  const sel = selected ?? firstBad;
  const event = b.trace.find((e) => e.step_id === sel) ?? null;
  const repRows = run.data?.cases.find((c) => c.case_id === caseId)?.reps ?? [];

  return (
    <div className="space-y-5">
      <nav className="text-xs text-muted">
        <a href={href()} className="hover:text-ink">总览</a> / <a href={href("runs", runId)} className="hover:text-ink">{runId}</a> / <span className="text-ink-2">{caseId}</span>
      </nav>

      <header className="card flex flex-wrap items-start justify-between gap-4 p-5">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Pill>{b.case?.category ?? "?"} · {CATEGORY_NAMES[b.case?.category ?? ""] ?? "未知类别"}</Pill>
            <span className="mono text-xs text-muted">{caseId}</span>
          </div>
          <h1 className="mt-1.5 text-xl font-semibold text-ink">{b.case?.title ?? caseId}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-ink-2">
            <StatusBadge status={v.outcome} />
            <Pill color={v.agent_version === "v2" ? "var(--s2)" : "var(--s1)"}>Agent {v.agent_version}</Pill>
            <Pill>{v.mode}</Pill>
            <Pill>{v.model_id ?? "—"}</Pill>
            {b.case?.fixture && b.case.fixture !== "default" && <Pill>初始数据 {b.case.fixture}</Pill>}
          </div>
        </div>
        <div>
          <div className="mb-1 text-[11px] text-muted">同一用例的 {b.reps.length} 次执行</div>
          <div className="flex gap-1.5">
            {b.reps.map((r) => {
              const fact = repRows.find((x) => x.rep === r);
              return (
                <a key={r} href={href("runs", runId, "cases", caseId, r)} className={`rounded-md p-1 ${r === rep ? "ring-2 ring-s1" : ""}`}>
                  <OutcomeCell
                    outcome={fact?.outcome ?? null}
                    label={`第 ${r} 次`}
                    tooltip={() => (
                      <div>
                        r{r} · {fact ? OUTCOME_META[fact.outcome].label : "…"}
                        {fact?.rules.length ? <div className="text-critical">{fact.rules.join("、")}</div> : null}
                      </div>
                    )}
                  />
                </a>
              );
            })}
          </div>
        </div>
      </header>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <StatTile label="首个违规步骤" value={firstBad ? `step ${firstBad}` : "无"} accent={firstBad ? "var(--critical)" : "var(--good)"} />
        <StatTile label="敏感调用（已授权/总数）" value={`${attempts.filter((a) => a.authorized).length}/${attempts.length}`} />
        <StatTile label="真实写入的越权" value={attempts.filter((a) => !a.authorized && a.wrote).length} accent={attempts.some((a) => !a.authorized && a.wrote) ? "var(--critical)" : undefined} />
        <StatTile label="注入到达 / 未触发" value={`${(v.metrics.injections_reached as string[] | undefined)?.length ?? 0} / ${(v.metrics.injections_skipped as string[] | undefined)?.length ?? 0}`} accent="var(--s7)" />
        <StatTile label="模型调用 · tokens" value={`${v.metrics.llm_calls ?? 0} · ${tokens(v.metrics.usage)}`} sub={`${((v.metrics.duration_ms as number) / 1000).toFixed(1)} 秒`} />
      </div>

      <Card
        title="三通道审计时间轴"
        subtitle="授权真值只来自可信用户事件；每个菱形是一次工具调用，敏感调用按其发生那一刻的授权状态判定。点击任一节点查看证据。"
        right={<Segmented label="模型调用" value={modelCalls} onChange={setModelCalls} options={[{ value: "hide", label: "隐藏模型调用" }, { value: "show", label: "显示模型调用" }]} />}
      >
        <TraceSwimlane
          events={b.trace}
          transitions={b.auth?.transitions ?? []}
          attempts={attempts}
          findings={v.findings}
          selected={sel}
          onSelect={setSelected}
          showModelCalls={modelCalls === "show"}
        />
        <div className="mt-3">
          <SwimlaneLegend />
        </div>
      </Card>

      <div className="grid gap-5 lg:grid-cols-[1.1fr_1fr]">
        <Card title={event ? `step ${event.step_id} 的证据` : "事件证据"} subtitle={event ? `第 ${event.turn_id} 轮 · ${event.kind}` : "在时间轴上点击一个节点"}>
          {event ? (
            <EventDetail e={event} attempt={attempts.find((a) => a.step === event.step_id)} findings={v.findings.filter((f) => f.first_bad_step === event.step_id)} />
          ) : (
            <p className="text-sm text-muted">未选择事件。</p>
          )}
        </Card>
        <Card title={`发现（${v.findings.length}）`} subtitle="每条发现都链接到触发它的步骤">
          {v.findings.length === 0 ? (
            <p className="text-sm text-muted">没有授权或陈述类违规。</p>
          ) : (
            <div className="space-y-2.5">
              {v.findings.map((f, i) => (
                <FindingCard key={i} f={f} onJump={() => setSelected(f.first_bad_step)} />
              ))}
            </div>
          )}
          {v.errors.length > 0 && (
            <div className="mt-3 rounded-md p-2.5 text-xs" style={{ background: "var(--warning-wash)" }}>
              <b>执行错误：</b>
              {v.errors.map((e) => short(e, 200)).join("；")}
            </div>
          )}
        </Card>
      </div>

      <Card title="对话与可信授权事件" subtitle="蓝色标签是测试用例中标注的可信用户事件（Agent 看不到）；Agent 只看到用户原话">
        <Conversation bundle={b} onJump={setSelected} />
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="业务状态变化" subtitle="SQLite 前后快照的行级差分">
          <DiffView diff={b.state_diff} after={b.state_after} />
        </Card>
        <Card title="断言" subtitle="四态：通过 / 失败 / 错误 / 不可测；注入未触发记为未触发">
          <table className="w-full text-xs">
            <tbody>
              {v.assertions.map((a) => (
                <tr key={a.rule_id} className="hairline-b">
                  <td className="mono py-1.5 pr-2 text-ink">{a.rule_id}</td>
                  <td className="py-1.5 pr-2">
                    <StatusBadge status={a.status} size="sm" />
                  </td>
                  <td className="py-1.5 text-ink-2">{a.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  );
}

function tokens(usage: unknown): string {
  const u = usage as { prompt_tokens?: number; completion_tokens?: number } | undefined;
  const n = (u?.prompt_tokens ?? 0) + (u?.completion_tokens ?? 0);
  return n >= 1000 ? `${(n / 1000).toFixed(1)}K` : String(n);
}

function EventDetail({ e, attempt, findings }: { e: TraceEvent; attempt?: SensitiveAttempt; findings: Finding[] }) {
  return (
    <div className="space-y-3 text-sm">
      {attempt && <AuthCheck attempt={attempt} findings={findings} />}
      {e.content && <p className="whitespace-pre-wrap rounded-md p-3 text-[13px] leading-relaxed text-ink" style={{ background: "var(--surface-2)" }}>{e.content}</p>}
      {e.tool && (
        <div className="flex flex-wrap gap-2 text-xs">
          <Pill>工具 {e.tool}</Pill>
          {e.status && <Pill color={e.status === "ok" ? "var(--good)" : "var(--serious)"}>状态 {e.status}</Pill>}
          {e.injection_id && <Pill color="var(--s7)">注入 {e.injection_id}</Pill>}
          {e.call_id && <Pill>call {e.call_id}</Pill>}
        </div>
      )}
      {e.args && Object.keys(e.args).length > 0 && (
        <div>
          <div className="mb-1 text-xs text-muted">参数</div>
          <JsonBlock value={e.args} max={200} />
        </div>
      )}
      {e.result !== null && e.result !== undefined && (
        <div>
          <div className="mb-1 text-xs text-muted">{e.kind === "injection" ? "Agent 看到的（被替换后的）返回" : "结果"}</div>
          <JsonBlock value={e.result} max={260} />
        </div>
      )}
      {e.kind === "injection" && typeof e.meta?.original_summary === "string" && (
        <div>
          <div className="mb-1 text-xs text-muted">真实返回（摘要）</div>
          <JsonBlock value={e.meta.original_summary} max={160} />
        </div>
      )}
      {e.kind === "agent_reasoning" && <p className="text-[11px] text-muted">这是模型 API 返回的可见推理文本，仅供参考，不代表模型内部的真实推理过程。</p>}
    </div>
  );
}

function AuthCheck({ attempt, findings }: { attempt: SensitiveAttempt; findings: Finding[] }) {
  const meta = AUTH_META[attempt.status_at_attempt];
  const ref = attempt.reference_params ?? {};
  const fields = [...new Set([...Object.keys(ref), ...Object.keys(attempt.mapped)])];
  // which fields differ is decided by the backend rule engine (PARAMS findings carry them)
  const mismatched = new Set(
    findings.flatMap((f) => (f.expected && typeof f.expected === "object" && !Array.isArray(f.expected) ? Object.keys(f.expected as object) : [])),
  );
  return (
    <div className="rounded-lg p-3" style={{ border: `1px solid ${attempt.authorized ? "var(--good)" : "var(--critical)"}`, background: attempt.authorized ? "var(--good-wash)" : "var(--critical-wash)" }}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <strong className="text-ink">
          {attempt.authorized ? "✓ 已授权" : "✕ 未授权"} · {ACTION_NAMES[attempt.action] ?? attempt.action}（{attempt.tool}）
        </strong>
        <span className="text-xs text-ink-2">
          当时授权状态：<b style={{ color: "var(--ink)" }}>{meta.label}</b>
          {attempt.version ? ` v${attempt.version}` : ""} · {attempt.wrote ? "产生了真实写入" : "没有写入"}
        </span>
      </div>
      <table className="mt-2 w-full text-xs">
        <thead>
          <tr className="text-muted">
            <th className="py-1 text-left font-medium">字段</th>
            <th className="py-1 text-left font-medium">{attempt.status_at_attempt === "confirmed" || attempt.status_at_attempt === "consumed" ? "用户确认时" : "用户当前请求"}</th>
            <th className="py-1 text-left font-medium">Agent 实际调用</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {fields.map((f) => {
            const has = f in ref;
            const same = has && !mismatched.has(f);
            return (
              <tr key={f} className="hairline-b">
                <td className="mono py-1 text-ink-2">{f}</td>
                <td className="mono py-1 text-ink">{has ? String(ref[f]) : <span className="text-muted">未约定</span>}</td>
                <td className="mono py-1 text-ink">{String(attempt.mapped[f] ?? "—")}</td>
                <td className="py-1 text-right font-bold" style={{ color: !has ? "var(--muted)" : same ? "var(--good-text)" : "var(--critical)" }}>
                  {!has ? "·" : same ? "✓" : "✕"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {attempt.violated_rules.length > 0 && <div className="mt-2 text-xs font-semibold text-critical">违反：{attempt.violated_rules.join("、")}</div>}
    </div>
  );
}

function FindingCard({ f, onJump }: { f: Finding; onJump: () => void }) {
  return (
    <div className="rounded-lg p-3" style={{ border: "1px solid var(--border)", background: "var(--surface-2)" }}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="mono text-[13px] font-semibold text-ink">{f.rule_id}</span>
        <Pill color={f.kind === "side_effect_violation" ? "var(--critical)" : f.kind === "attempt_violation" ? "var(--serious)" : "var(--warning)"}>{KIND_TEXT[f.kind]}</Pill>
        <Pill>{f.severity}</Pill>
        <button onClick={onJump} className="ml-auto text-xs font-medium text-s1 hover:underline">
          定位到 step {f.first_bad_step} →
        </button>
      </div>
      <p className="mt-1.5 text-[13px] text-ink">{f.reason}</p>
      <div className="mt-1.5 grid grid-cols-2 gap-2 text-[11px]">
        <div>
          <span className="text-muted">期望</span>
          <div className="mono break-all text-ink-2">{short(f.expected, 140)}</div>
        </div>
        <div>
          <span className="text-muted">实际</span>
          <div className="mono break-all text-ink-2">{short(f.actual, 140)}</div>
        </div>
      </div>
    </div>
  );
}

function eventLabel(e: UserEvent): string {
  const action = e.action ? ACTION_NAMES[e.action] ?? e.action : "";
  const params = Object.entries(e.params).map(([k, v]) => `${k}=${v}`).join(" ");
  const verb = { request: "请求", modify: "修改", confirm: "确认", revoke: "撤销", decline: "拒绝", inquire: "仅询问" }[e.type];
  return `${verb}${action ? ` · ${action}` : ""}${params ? ` · ${params}` : ""}`;
}

function Conversation({ bundle, onJump }: { bundle: CaseBundle; onJump: (step: number) => void }) {
  const turns = useMemo(() => {
    const byTurn = new Map<number, TraceEvent[]>();
    for (const e of bundle.trace) byTurn.set(e.turn_id, [...(byTurn.get(e.turn_id) ?? []), e]);
    return [...byTurn.entries()].filter(([t]) => t > 0).sort((a, b) => a[0] - b[0]);
  }, [bundle.trace]);
  return (
    <div className="space-y-4">
      {turns.map(([turn, events]) => {
        const user = events.find((e) => e.kind === "user_message");
        const finals = events.filter((e) => e.kind === "agent_message" && !e.meta?.with_tool_calls);
        const reply = finals[finals.length - 1];
        const calls = events.filter((e) => e.kind === "tool_call_attempt");
        const injected = events.filter((e) => e.kind === "injection");
        const caseTurn = bundle.case?.turns[turn - 1];
        return (
          <div key={turn} className="grid gap-2 md:grid-cols-[64px_1fr]">
            <div className="pt-1 text-xs font-semibold text-muted">第 {turn} 轮</div>
            <div className="space-y-2">
              {user && (
                <div className="max-w-3xl rounded-xl rounded-tl-sm px-3.5 py-2.5" style={{ background: "var(--s1-wash)", border: "1px solid var(--border)" }}>
                  <div className="mb-1 text-[11px] font-semibold text-ink-2">用户</div>
                  <div className="whitespace-pre-wrap text-[13px] text-ink">{user.content}</div>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {(caseTurn?.events ?? []).map((ev, i) => (
                      <Pill key={i} color="var(--s1)" title="可信授权事件（测试用例标注，Agent 不可见）">
                        {eventLabel(ev)}
                      </Pill>
                    ))}
                    {caseTurn && caseTurn.events.length === 0 && <span className="text-[11px] text-muted">无授权事件</span>}
                  </div>
                </div>
              )}
              {(calls.length > 0 || injected.length > 0) && (
                <div className="flex flex-wrap gap-1.5 pl-1">
                  {calls.map((c) => {
                    const a = bundle.auth?.attempts.find((x) => x.step === c.step_id);
                    return (
                      <button key={c.step_id} onClick={() => onJump(c.step_id)} className="text-left">
                        <Pill color={a ? (a.authorized ? "var(--good)" : "var(--critical)") : "var(--axis)"}>
                          {c.tool}
                          {a ? (a.authorized ? " ✓" : " ✕") : ""}
                        </Pill>
                      </button>
                    );
                  })}
                  {injected.map((c) => (
                    <button key={c.step_id} onClick={() => onJump(c.step_id)}>
                      <Pill color="var(--s7)">注入 {c.injection_id}</Pill>
                    </button>
                  ))}
                </div>
              )}
              {reply && (
                <div className="max-w-3xl rounded-xl rounded-tl-sm px-3.5 py-2.5" style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}>
                  <div className="mb-1 text-[11px] font-semibold text-ink-2">Agent</div>
                  <div className="whitespace-pre-wrap text-[13px] leading-relaxed text-ink">{reply.content}</div>
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function DiffView({ diff, after }: { diff: StateDiff | null; after: StateSnapshot | null }) {
  if (!diff) return <p className="text-sm text-muted">适配器没有状态访问能力（UNSUPPORTED）。</p>;
  const orders = after?.tables.orders;
  const changed = diff.tables.orders;
  const insertedKeys = new Set((changed?.inserted ?? []).map((c) => JSON.stringify(c.pk)));
  const updated = new Map((changed?.updated ?? []).map((c) => [JSON.stringify(c.pk), c]));
  const other = Object.entries(diff.tables).filter(([t]) => t !== "orders");
  if (!orders) return <p className="text-sm text-muted">没有订单表。</p>;
  const cols = ["order_id", "flight_no", "date", "origin", "destination", "cabin", "price", "status"];
  return (
    <div className="space-y-3">
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
            {orders.rows.length === 0 && (
              <tr>
                <td colSpan={cols.length + 1} className="py-3 text-center text-muted">
                  订单表为空
                </td>
              </tr>
            )}
            {orders.rows.map((row) => {
              const key = JSON.stringify({ order_id: row.order_id });
              const ins = insertedKeys.has(key);
              const upd = updated.get(key);
              return (
                <tr key={key} className="hairline-b" style={{ background: ins ? "var(--good-wash)" : undefined }}>
                  <td className="px-1.5 py-1 text-[11px] font-semibold" style={{ color: ins ? "var(--good-text)" : upd ? "var(--ink-2)" : "var(--muted)" }}>
                    {ins ? "新增" : upd ? "修改" : "原有"}
                  </td>
                  {cols.map((c) => {
                    const changedCell = upd?.changed.includes(c);
                    return (
                      <td key={c} className="mono px-1.5 py-1 text-ink" style={{ background: changedCell ? "var(--warning-wash)" : undefined }}>
                        {changedCell ? (
                          <>
                            <span className="text-muted line-through">{String(upd?.before?.[c])}</span> → {String(row[c])}
                          </>
                        ) : (
                          String(row[c] ?? "")
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {other.length > 0 && (
        <div className="text-xs text-ink-2">
          {other.map(([table, d]) => (
            <div key={table}>
              <span className="mono text-ink">{table}</span>：新增 {d.inserted.length}、删除 {d.deleted.length}、修改 {d.updated.length}
              {d.updated.slice(0, 3).map((u) => (
                <span key={JSON.stringify(u.pk)} className="mono ml-2 text-muted">
                  {Object.values(u.pk).join("/")} {u.changed.map((c) => `${c}: ${u.before?.[c]}→${u.after?.[c]}`).join(", ")}
                </span>
              ))}
            </div>
          ))}
        </div>
      )}
      {diff && Object.keys(diff.tables).length === 0 && <p className="text-xs text-muted">本次执行没有改变任何业务状态。</p>}
    </div>
  );
}

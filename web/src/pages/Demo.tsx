import { useEffect, useState, type ReactNode } from "react";
import { OutcomeCell } from "../components/charts";
import { Icon, type IconName } from "../components/icons";
import { ErrorNote, Loading, PageHeader, Pill, RichText, Term } from "../components/ui";
import { api, type AuthTransition, type CaseBundle, type Defect, type SensitiveAttempt, type StateDiff, type TraceEvent } from "../lib/api";
import { pickFeatured } from "../lib/featured";
import { useRunStream } from "../lib/stream";
import { ACTION_NAMES, AUTH_META, STATUS_STORY, TRIGGER_VERB, href, useAsync } from "../lib/util";
import { AuthCheck } from "./TraceExplorer";

/** A guided walk through one real defect, built only from that execution's evidence. */
export function Demo() {
  const defects = useAsync(() => api.defects(), []);
  const targets = useAsync(() => api.targets().catch(() => []), []);
  const d = defects.data ? pickFeatured(defects.data.defects) : null;
  const bundle = useAsync(() => (d ? api.caseBundle(d.first.run_id, d.case_id, d.first.rep) : Promise.resolve(null)), [d?.id]);
  const fixedRep = d?.retest?.outcomes[0]?.rep;
  const fixed = useAsync(() => (d?.retest && fixedRep !== undefined ? api.caseBundle(d.retest.run_id, d.case_id, fixedRep).catch(() => null) : Promise.resolve(null)), [d?.id]);
  const [step, setStep] = useState(0);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input, textarea, select")) return;
      if (e.key === "ArrowRight") setStep((s) => Math.min(s + 1, 4));
      if (e.key === "ArrowLeft") setStep((s) => Math.max(s - 1, 0));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (defects.error) return <ErrorNote error={defects.error} />;
  if (!defects.data) return <Loading what="案例" />;
  if (!d) {
    return (
      <div className="space-y-5">
        <PageHeader title="1 分钟看懂">这里会用平台发现的第一个真实问题，一步步演示它是怎么被找出来的。</PageHeader>
        <div className="card p-8 text-center">
          <p className="text-sm text-ink-2">这台机器上还没有发现过问题的测试记录。先对一个 Agent 运行一次「快速体检」。</p>
          <a href={href("console")} className="btn btn-primary btn-md mt-4">
            开始快速体检
          </a>
        </div>
      </div>
    );
  }
  if (bundle.error) return <ErrorNote error={bundle.error} />;
  if (!bundle.data) return <Loading what="案例证据" />;

  const b = bundle.data;
  const target = targets.data?.find((t) => t.name === d.target);
  const story = buildStory(b);
  const steps: { icon: IconName; title: string; body: ReactNode }[] = [
    { icon: "chat", title: "用户提出请求", body: <StepRequest b={b} s={story} /> },
    { icon: "user", title: "用户的同意变了", body: <StepConsent b={b} s={story} /> },
    { icon: "shield", title: "Agent 没等确认就执行", body: <StepAttempt b={b} s={story} /> },
    { icon: "database", title: "数据库被真实改写", body: <StepDatabase b={b} /> },
    { icon: "retest", title: "修复后复测", body: <StepRetest d={d} fixed={fixed.data ?? null} turn={story.attemptTurn} /> },
  ];

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="1 分钟看懂 · 一个真实案例" title={d.title}>
        被测对象：<b className="text-ink">{target?.description ?? d.target}</b>。下面每一步都取自这次测试的真实证据（{d.first.mode === "live" ? "真实调用模型" : "回放"}，模型 {b.verdict.model_id ?? "—"}），不是示意图。用 ← → 键也可以翻页。
      </PageHeader>

      <ol className="grid grid-cols-5 gap-1.5 sm:gap-3" aria-label="演示步骤">
        {steps.map((s, i) => (
          <li key={s.title}>
            <button onClick={() => setStep(i)} aria-current={i === step ? "step" : undefined} className="group flex w-full flex-col items-start gap-2 text-left">
              <span className="h-1 w-full rounded-full" style={{ background: i <= step ? "var(--brand)" : "var(--surface-3)" }} />
              <span className="flex items-center gap-1.5">
                <span className="grid size-6 shrink-0 place-items-center rounded-full text-[11px] font-semibold" style={i === step ? { background: "var(--brand)", color: "white" } : { background: "var(--surface-3)", color: "var(--ink-2)" }}>
                  {i + 1}
                </span>
                <span className={`hidden text-xs sm:inline ${i === step ? "font-semibold text-ink" : "text-ink-2"}`}>{s.title}</span>
              </span>
            </button>
          </li>
        ))}
      </ol>

      <section className="card fade-up p-6 sm:p-7" key={step}>
        <div className="mb-5 flex items-center gap-3">
          <span className="grid size-10 place-items-center rounded-xl" style={{ background: "var(--brand-wash)", color: "var(--brand)" }}>
            <Icon name={steps[step].icon} size={20} />
          </span>
          <div>
            <div className="text-[11px] font-medium text-muted">
              第 {step + 1} 步 / 共 {steps.length} 步
            </div>
            <h2 className="text-lg font-semibold text-ink">{steps[step].title}</h2>
          </div>
        </div>
        {steps[step].body}
        <div className="mt-7 flex items-center justify-between border-t border-line pt-4">
          <button onClick={() => setStep(step - 1)} disabled={step === 0} className="btn btn-secondary btn-md">
            上一步
          </button>
          {step < steps.length - 1 ? (
            <button onClick={() => setStep(step + 1)} className="btn btn-primary btn-md">
              下一步：{steps[step + 1].title}
            </button>
          ) : (
            <a href={href("console")} className="btn btn-primary btn-md">
              用同样的方法测试你的 Agent
              <Icon name="arrow" size={15} />
            </a>
          )}
        </div>
      </section>

      <TryIt d={d} />
    </div>
  );
}

// ------------------------------------------------------------------ the story, read from the evidence

interface Story {
  request: AuthTransition | null;
  attempt: SensitiveAttempt | null;
  attemptTurn: number | null;
  changes: AuthTransition[]; // ledger transitions in the turn where consent changed
}

function buildStory(b: CaseBundle): Story {
  const attempts = b.auth?.attempts ?? [];
  const transitions = b.auth?.transitions ?? [];
  const firstBad = b.verdict.findings[0]?.first_bad_step ?? null;
  const attempt = attempts.find((a) => a.step === firstBad) ?? attempts.find((a) => !a.authorized) ?? null;
  const attemptTurn = attempt ? (b.trace.find((e) => e.step_id === attempt.step)?.turn_id ?? null) : null;
  const before = transitions.filter((t) => (attempt ? t.step <= attempt.step && t.action === attempt.action : true));
  const request = before.find((t) => t.trigger === "request") ?? before[0] ?? null;
  const lastTurn = before.length ? before[before.length - 1].turn : null;
  const changes = before.filter((t) => t.turn === lastTurn && t !== request);
  return { request, attempt, attemptTurn, changes };
}

function userText(b: CaseBundle, turn: number | null): string | null {
  return b.trace.find((e) => e.turn_id === turn && e.kind === "user_message")?.content ?? null;
}

function agentReply(b: CaseBundle, turn: number | null): TraceEvent | null {
  const finals = b.trace.filter((e) => e.turn_id === turn && e.kind === "agent_message" && !e.meta?.with_tool_calls);
  return finals[finals.length - 1] ?? null;
}

function params(p: Record<string, unknown>): string {
  return Object.entries(p)
    .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join("，");
}

function action(name: string): string {
  return ACTION_NAMES[name] ?? name;
}

// ------------------------------------------------------------------ steps

function Bubble({ who, children, tone = "agent" }: { who: string; children: ReactNode; tone?: "user" | "agent" | "muted" }) {
  const bg = tone === "user" ? "var(--s1-wash)" : "var(--surface-2)";
  return (
    <div className={`max-w-2xl rounded-2xl px-4 py-3 ${tone === "user" ? "rounded-tl-sm" : "rounded-tl-sm"}`} style={{ background: bg, border: "1px solid var(--border)", opacity: tone === "muted" ? 0.85 : 1 }}>
      <div className="mb-1 text-[11px] font-semibold text-ink-2">{who}</div>
      <div className="whitespace-pre-wrap text-[13.5px] leading-relaxed text-ink">{children}</div>
    </div>
  );
}

function Explain({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-xl p-4 text-sm leading-relaxed text-ink" style={{ background: "var(--brand-wash)", border: "1px solid var(--border)" }}>
      {children}
    </div>
  );
}

function LedgerRow({ t }: { t: AuthTransition }) {
  const to = AUTH_META[t.to_status];
  return (
    <li className="flex flex-wrap items-center gap-2 text-xs">
      <Pill color="var(--s1)">{TRIGGER_VERB[t.trigger] ?? t.trigger}</Pill>
      <span className="text-ink">{action(t.action)}</span>
      {Object.keys(t.params).length > 0 && <span className="mono text-ink-2">{params(t.params)}</span>}
      <span className="text-muted">→</span>
      <span className="rounded-full px-2 py-0.5 text-[11px] font-semibold" style={{ background: to.wash, color: "var(--ink)", border: `1px solid ${to.color}` }}>
        {to.label}
      </span>
    </li>
  );
}

function StepRequest({ b, s }: { b: CaseBundle; s: Story }) {
  const turn = s.request?.turn ?? 1;
  const reply = agentReply(b, turn);
  return (
    <div className="grid gap-6 lg:grid-cols-[1.3fr_1fr]">
      <div className="space-y-3">
        <Bubble who="用户" tone="user">
          {userText(b, turn) ?? "—"}
        </Bubble>
        {reply && (
          <Bubble who="Agent">
            <RichText text={reply.content} />
          </Bubble>
        )}
      </div>
      <div className="space-y-3">
        <Explain>
          平台为测试场景里的每句用户话语都标注了它在授权上的含义（Agent 看不到这些标注），并据此维护一本独立的<Term>授权账本</Term>。这一句被记为：
        </Explain>
        {s.request && (
          <ul className="space-y-2 rounded-xl p-3" style={{ border: "1px dashed var(--border-strong)" }}>
            <LedgerRow t={s.request} />
          </ul>
        )}
        <p className="text-xs text-ink-2">此时用户只是提出了请求，还没有确认，Agent 不应该动手修改数据。</p>
      </div>
    </div>
  );
}

function StepConsent({ b, s }: { b: CaseBundle; s: Story }) {
  const turn = s.changes[0]?.turn ?? s.attemptTurn;
  const status = s.attempt?.status_at_attempt ?? "none";
  return (
    <div className="grid gap-6 lg:grid-cols-[1.3fr_1fr]">
      <div className="space-y-3">
        <Bubble who={`用户（第 ${turn ?? "?"} 轮）`} tone="user">
          {userText(b, turn ?? null) ?? "—"}
        </Bubble>
        <ul className="space-y-2 rounded-xl p-3" style={{ border: "1px dashed var(--border-strong)" }}>
          <li className="text-[11px] font-medium text-muted">授权账本记下：</li>
          {s.changes.length ? s.changes.map((t, i) => <LedgerRow key={i} t={t} />) : <li className="text-xs text-ink-2">（这一轮没有新的授权事件）</li>}
        </ul>
      </div>
      <Explain>
        <b>关键在这里：</b>
        {STATUS_STORY[status]}
        {status === "modified" && " 正确的做法是：先把新的参数复述给用户，等用户再确认一次。"}
      </Explain>
    </div>
  );
}

function StepAttempt({ b, s }: { b: CaseBundle; s: Story }) {
  if (!s.attempt) return <p className="text-sm text-ink-2">这次执行没有记录到敏感操作。</p>;
  const a = s.attempt;
  const reply = agentReply(b, s.attemptTurn);
  const nextTurn = (s.attemptTurn ?? 0) + 1;
  const next = userText(b, nextTurn);
  const findings = b.verdict.findings.filter((f) => f.first_bad_step === a.step);
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_1.1fr]">
      <div className="space-y-3">
        <div className="flex items-center gap-2 rounded-xl px-4 py-3 text-sm" style={{ background: "var(--critical-wash)", border: "1px solid var(--critical)" }}>
          <span className="grid size-6 place-items-center rounded-full text-xs font-bold text-white" style={{ background: "var(--critical)" }}>
            ✕
          </span>
          <span className="text-ink">
            第 <b>{a.step}</b> 步，Agent 调用了 <span className="mono font-semibold">{a.tool}</span>（{action(a.action)}）
          </span>
        </div>
        {reply && (
          <Bubble who="Agent 随后回复">
            <RichText text={reply.content} />
          </Bubble>
        )}
        {next && (
          <Bubble who={`用户（第 ${nextTurn} 轮）`} tone="user">
            {next}
          </Bubble>
        )}
      </div>
      <div className="space-y-3">
        <AuthCheck attempt={a} findings={findings} />
        <Explain>
          调用发生的那一刻，账本上的状态是「<b>{AUTH_META[a.status_at_attempt].label}</b>」，所以这次调用被判为<Term>越权</Term>。平台是在 Agent 发起调用的那一步当场判定的，不依赖 Agent 事后怎么说。
          {a.status_at_attempt === "modified" && !a.violated_rules.some((r) => r.includes("PARAMS")) && " 注意：参数本身和用户最新的说法一致，问题不在参数，而在于这组新参数从没被用户确认过。"}
          {next && " 等用户想再考虑一下时，修改已经生效了。"}
        </Explain>
      </div>
    </div>
  );
}

function changedFields(diff: StateDiff | null): { table: string; key: string; field: string; before: unknown; after: unknown }[] {
  if (!diff) return [];
  return Object.entries(diff.tables).flatMap(([table, t]) =>
    t.updated.flatMap((u) => u.changed.map((field) => ({ table, key: Object.values(u.pk).join("/"), field, before: u.before?.[field], after: u.after?.[field] }))),
  );
}

function StepDatabase({ b }: { b: CaseBundle }) {
  const fields = changedFields(b.state_diff);
  const inserted = Object.entries(b.state_diff?.tables ?? {}).flatMap(([table, t]) => t.inserted.map((r) => ({ table, key: Object.values(r.pk).join("/") })));
  const wrote = (b.auth?.attempts ?? []).some((a) => !a.authorized && a.wrote);
  return (
    <div className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
      <div className="space-y-2">
        <div className="text-xs font-medium text-muted">执行前后，Agent 业务数据库的差异</div>
        {fields.length === 0 && inserted.length === 0 && <p className="text-sm text-ink-2">数据库没有变化。</p>}
        {fields.map((f, i) => (
          <div key={i} className="flex flex-wrap items-center gap-3 rounded-xl px-4 py-3" style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}>
            <span className="mono text-xs text-ink-2">
              {f.table} · {f.key}
            </span>
            <span className="mono text-sm font-semibold text-ink">{f.field}</span>
            <span className="mono text-sm text-muted line-through">{fmt(f.before)}</span>
            <Icon name="arrow" size={14} className="text-muted" />
            <span className="mono rounded px-1.5 text-sm font-semibold" style={{ background: "var(--warning-wash)", color: "var(--ink)" }}>
              {fmt(f.after)}
            </span>
          </div>
        ))}
        {inserted.map((r, i) => (
          <div key={`i${i}`} className="rounded-xl px-4 py-3 text-sm" style={{ background: "var(--good-wash)", border: "1px solid var(--border)" }}>
            <span className="mono text-xs text-ink-2">{r.table}</span> 新增一行 <span className="mono">{r.key}</span>
          </div>
        ))}
      </div>
      <Explain>
        平台不只听 Agent 怎么说，还对比了执行前后的业务数据库。{wrote ? <>这次越权操作留下了<Term>真实写入</Term>，属于最严重的一类问题：未经同意就改了数据。</> : "这次越权尝试被拦下，数据库没有被改动。"}
      </Explain>
    </div>
  );
}

function fmt(v: unknown): string {
  return typeof v === "string" ? v : JSON.stringify(v);
}

function StepRetest({ d, fixed, turn }: { d: Defect; fixed: CaseBundle | null; turn: number | null }) {
  const r = d.retest;
  if (!r) {
    return (
      <Explain>
        {d.fixed_version ? (
          <>
            修复版 <b>{d.fixed_version}</b> 还没有复测过这个场景。点下方「复测修复版」，平台会用<b>同一个场景</b>（同样的初始数据、同样的用户话语）在修复版上重跑，每次都通过才算修复。
          </>
        ) : (
          <>
            这个问题还没有登记修复版本。开发者修好 Agent 后，可以用<b>同一个场景</b>（同样的初始数据、同样的用户话语）重新测试，每次都通过才算修复。
          </>
        )}
      </Explain>
    );
  }
  const reply = fixed ? agentReply(fixed, turn) : null;
  const ok = r.passed === r.total;
  return (
    <div className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-3 rounded-xl px-4 py-3" style={{ background: ok ? "var(--good-wash)" : "var(--critical-wash)", border: `1px solid ${ok ? "var(--good)" : "var(--critical)"}` }}>
          <span className="text-2xl font-semibold" style={{ color: ok ? "var(--good-text)" : "var(--critical)" }}>
            {r.passed}/{r.total}
          </span>
          <span className="text-sm text-ink">
            修复版 <b>{r.version}</b> 在同一个场景上{ok ? "全部通过" : "仍有失败"}
          </span>
          <span className="flex gap-1">
            {r.outcomes.map((o) => (
              <a key={o.rep} href={href("runs", r.run_id, "cases", d.case_id, o.rep)}>
                <OutcomeCell outcome={o.outcome} label={`第 ${o.rep + 1} 次`} tooltip={() => <span>第 {o.rep + 1} 次 · {o.outcome}</span>} />
              </a>
            ))}
          </span>
        </div>
        {reply && (
          <Bubble who={`修复版 Agent 在第 ${turn} 轮的回复`}>
            <RichText text={reply.content} />
          </Bubble>
        )}
      </div>
      <Explain>
        修复后，平台用<b>完全相同</b>的场景重跑（同样的初始数据、同样的用户话语）。只有每一次重复执行都通过，这个问题才会标记为「已修复」。这就是<Term>复测</Term>：修没修好，用证据说话。
      </Explain>
    </div>
  );
}

// ------------------------------------------------------------------ run it yourself

function TryIt({ d }: { d: Defect }) {
  const agents = useAsync(() => api.agents().catch(() => []), []);
  const sources = useAsync(() => api.replaySourcesForCase(d.target, d.version, d.case_id).catch(() => []), [d.id]);
  const [which, setWhich] = useState<"original" | "fixed" | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const stream = useRunStream(runId);
  const agent = agents.data?.find((a) => a.name === d.target);
  const transport = agent?.online ? "http" : "inprocess";
  const source = sources.data?.[0];

  if (window.__CONSENTTRACE_STATIC__) return null;

  async function rerun(kind: "original" | "fixed") {
    setError(null);
    setWhich(kind);
    setRunId(null);
    try {
      if (kind === "original") {
        if (!source) throw new Error("没有这个场景的录制，无法回放");
        const res = await api.startRun({ target: d.target, version: d.version, suite: d.first.suite, mode: "replay", replay_from: source.run_id, cases: [d.case_id], transport, concurrency: 3 });
        setRunId(res.run_id);
      } else {
        const res = await api.retest({ id: d.id, mode: "replay", transport });
        setRunId(res.run_id);
      }
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const results = Object.values(stream.results);
  return (
    <section className="card p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-2xl">
          <h2 className="text-[15px] font-semibold text-ink">亲自跑一遍</h2>
          <p className="mt-1 text-sm text-ink-2">
            用<Term>回放</Term>模式重新执行这个场景：Agent 进程、工具和数据库都会真实运行，只是模型回复来自录制，所以免费、几秒完成，结果可以复现。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => rerun("original")} disabled={stream.status === "running" || !source} className="btn btn-secondary btn-md">
            重跑原版本 {d.version}（应复现问题）
          </button>
          {d.fixed_version && (
            <button onClick={() => rerun("fixed")} disabled={stream.status === "running"} className="btn btn-primary btn-md">
              复测修复版 {d.fixed_version}（应通过）
            </button>
          )}
        </div>
      </div>
      {error && <p className="mt-3 text-xs text-critical">{error}</p>}
      {runId && (
        <div className="mt-4 flex flex-wrap items-center gap-3 rounded-xl p-4" style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}>
          <span className="text-sm text-ink">{which === "original" ? `原版本 ${d.version}` : `修复版 ${d.fixed_version}`}</span>
          <span className="flex gap-1">
            {Array.from({ length: stream.plan?.total ?? 0 }, (_, rep) => {
              const res = stream.results[`${d.case_id}#${rep}`];
              return (
                <div key={rep} className={!res ? "animate-pulse" : ""}>
                  <OutcomeCell
                    outcome={res?.outcome ?? null}
                    label={`第 ${rep + 1} 次`}
                    onClick={res ? () => (window.location.hash = href("runs", runId, "cases", d.case_id, rep)) : undefined}
                    tooltip={() => <span>第 {rep + 1} 次 · {res?.outcome ?? "执行中"}</span>}
                  />
                </div>
              );
            })}
          </span>
          <span className="text-xs text-ink-2">
            {stream.status === "running"
              ? `执行中 ${results.length}/${stream.plan?.total ?? "…"}`
              : stream.status === "done"
                ? `完成：${results.filter((r) => r.outcome === "PASS").length}/${results.length} 次通过`
                : stream.status === "error"
                  ? stream.error
                  : ""}
          </span>
          {stream.status === "done" && (
            <a href={href("runs", runId, "cases", d.case_id)} className="ml-auto text-xs font-semibold" style={{ color: "var(--brand)" }}>
              查看这次执行的完整审计时间轴 →
            </a>
          )}
        </div>
      )}
    </section>
  );
}

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { OutcomeCell } from "../components/charts";
import { Icon } from "../components/icons";
import { Card, ErrorNote, PageHeader, Pill, Term } from "../components/ui";
import { api } from "../lib/api";
import { useRunStream } from "../lib/stream";
import { CATEGORY_NAMES, PLANS, href, planName, useAsync } from "../lib/util";

export function Console({ preset }: { preset?: { target?: string; version?: string; suite?: string } }) {
  const ws = useAsync(() => api.workspace(), []);
  const [target, setTarget] = useState(preset?.target ?? "");
  const [version, setVersion] = useState(preset?.version ?? "v1");
  const [suite, setSuite] = useState(preset?.suite ?? "acceptance");
  const [transport, setTransport] = useState<"http" | "inprocess">("http");
  const [mode, setMode] = useState<"live" | "replay">("replay");
  const [reps, setReps] = useState(3);
  const [concurrency, setConcurrency] = useState(6);
  const [replayFrom, setReplayFrom] = useState("");
  const [showMore, setShowMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const stream = useRunStream(runId, () => ws.reload());

  const agents = ws.data?.agents ?? [];
  const agent = agents.find((a) => a.name === target);
  const suiteCases = useAsync(() => (agent ? api.suite(target, suite) : Promise.resolve([])), [target, suite, agent?.name]);
  const sources = useAsync(() => (agent ? api.replaySources(target, version, suite) : Promise.resolve([])), [target, version, suite, agent?.name]);
  const categoryOf = useMemo(() => new Map((suiteCases.data ?? []).map((c) => [c.case_id, c.category])), [suiteCases.data]);
  const liveOk = transport === "http" ? Boolean(agent?.online && agent.info?.llm.live_available) : true;
  const hasRecording = (sources.data ?? []).length > 0;

  useEffect(() => {
    if (!target && agents.length) setTarget(agents[0].name);
  }, [agents.length]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (agent && !agent.versions.includes(version)) setVersion(agent.versions[0]);
    if (agent && !(suite in agent.suites)) setSuite(agent.suites.acceptance ? "acceptance" : Object.keys(agent.suites)[0]);
    if (agent && !agent.online && transport === "http" && agent.in_process) setTransport("inprocess");
    if (agent?.online && transport === "inprocess") setTransport("http");
  }, [agent?.name, agent?.online]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const ids = (sources.data ?? []).map((s) => s.run_id);
    if (!ids.includes(replayFrom)) setReplayFrom(ids[0] ?? "");
    if (sources.data && !ids.length && liveOk) setMode("live");
    if (sources.data && ids.length) setMode("replay");
  }, [sources.data]); // eslint-disable-line react-hooks/exhaustive-deps

  async function start() {
    setError(null);
    try {
      const body: Record<string, unknown> = { target, version, suite, mode, concurrency, transport };
      if (mode === "live") body.reps = reps;
      else body.replay_from = replayFrom;
      const { run_id } = await api.startRun(body);
      setRunId(run_id);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const failed = Object.values(stream.results).filter((r) => r.outcome !== "PASS");
  const writes = failed.filter((r) => r.findings.some((f) => f.kind === "side_effect_violation"));
  const plans = Object.entries(agent?.suites ?? {});
  const order = Object.keys(PLANS);
  const primary = plans.filter(([s]) => PLANS[s]?.primary).sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]));
  const others = plans.filter(([s]) => !PLANS[s]?.primary);
  const n = agent?.suites[suite] ?? 0;
  const canStart = Boolean(agent) && stream.status !== "running" && (mode === "replay" ? Boolean(replayFrom) : liveOk);

  return (
    <div className="space-y-5">
      <PageHeader title="发起测试">选一个 Agent 和一套测试方案就可以开始。平台会扮演用户和 Agent 多轮对话，每一步自动核对授权和数据库的变化，结果实时显示。</PageHeader>
      {ws.error && <ErrorNote error={ws.error} />}

      <Step n={1} title="选择要测试的 Agent" right={<a href={href("agents")} className="text-xs font-medium" style={{ color: "var(--brand)" }}>+ 接入新的 Agent</a>}>
        <div className="grid gap-2.5 md:grid-cols-2 xl:grid-cols-3" role="radiogroup" aria-label="被测 Agent">
          {agents.map((a) => (
            <button key={a.name} role="radio" aria-checked={a.name === target} onClick={() => setTarget(a.name)} className="choice p-3.5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-ink">{a.name}</span>
                <span className="inline-flex items-center gap-1 text-[11px] text-ink-2">
                  <span aria-hidden className="size-1.5 rounded-full" style={{ background: a.online ? "var(--good)" : "var(--muted)" }} />
                  {a.online ? "在线" : "离线"}
                </span>
                {a.like && <Pill color="var(--brand)">我接入的</Pill>}
              </div>
              <div className="mt-1 line-clamp-2 text-xs leading-relaxed text-ink-2">{a.description}</div>
            </button>
          ))}
        </div>
        {agent && !agent.online && (
          <p className="mt-2.5 text-xs text-ink-2">
            这个 Agent 的进程没有运行：到 <a className="font-medium hover:underline" style={{ color: "var(--brand)" }} href={href("agents")}>我的 Agent</a> 一键启动{agent.in_process ? "，或在下方高级设置里改为同进程加载" : ""}。
          </p>
        )}
      </Step>

      <Step n={2} title="选择测试方案">
        <div className="grid gap-2.5 md:grid-cols-3" role="radiogroup" aria-label="测试方案">
          {primary.map(([s, count]) => (
            <PlanChoice key={s} id={s} count={count} checked={s === suite} onPick={() => setSuite(s)} />
          ))}
        </div>
        {others.length > 0 && (
          <div className="mt-3">
            <button onClick={() => setShowMore(!showMore)} className="inline-flex items-center gap-1 text-xs font-medium text-ink-2 hover:text-ink">
              <Icon name="chevron" size={13} className={showMore ? "rotate-90" : ""} />
              更多用例集（{others.length}）
            </button>
            {(showMore || others.some(([s]) => s === suite)) && (
              <div className="mt-2 grid gap-2 md:grid-cols-2 xl:grid-cols-4" role="radiogroup" aria-label="更多用例集">
                {others.map(([s, count]) => (
                  <PlanChoice key={s} id={s} count={count} checked={s === suite} onPick={() => setSuite(s)} small />
                ))}
              </div>
            )}
          </div>
        )}
        {agent && agent.versions.length > 1 && (
          <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
            <span className="text-ink-2">测试哪个版本：</span>
            <div role="radiogroup" aria-label="Agent 版本" className="flex flex-wrap gap-1.5">
              {agent.versions.map((v) => (
                <button key={v} role="radio" aria-checked={v === version} onClick={() => setVersion(v)} className="choice px-2.5 py-1 text-xs font-medium text-ink">
                  {v}
                </button>
              ))}
            </div>
            {agent.fixed_versions[version] && <span className="text-muted">（{version} 的修复版是 {agent.fixed_versions[version]}）</span>}
          </div>
        )}
      </Step>

      <Step n={3} title="开始测试">
        <div className="grid gap-2.5 md:grid-cols-2" role="radiogroup" aria-label="运行方式">
          <button role="radio" aria-checked={mode === "replay"} disabled={!hasRecording} onClick={() => setMode("replay")} className="choice p-3.5">
            <div className="flex items-center gap-2 text-sm font-semibold text-ink">
              <Term>回放</Term>
              {hasRecording && <Pill color="var(--good)">推荐</Pill>}
            </div>
            <p className="mt-1 text-xs leading-relaxed text-ink-2">{hasRecording ? "复现录制下来的真实模型回复：免费、几秒完成、每次结果相同。Agent、工具和数据库仍然真实运行。" : "这个版本和方案还没有录制，先用真实调用跑一次，之后就可以回放。"}</p>
          </button>
          <button role="radio" aria-checked={mode === "live"} disabled={!liveOk} onClick={() => setMode("live")} className="choice p-3.5">
            <div className="text-sm font-semibold text-ink">真实调用模型</div>
            <p className="mt-1 text-xs leading-relaxed text-ink-2">
              {liveOk ? `让 Agent 调用它自己的大模型（${agent?.info?.llm.model ?? "—"}），每个场景重复 ${reps} 次，会消耗 token。` : "这个 Agent 没有配置模型 Key（或进程离线），暂时只能回放。"}
            </p>
          </button>
        </div>

        <details className="mt-3 text-xs">
          <summary className="cursor-pointer select-none font-medium text-ink-2 hover:text-ink">高级设置</summary>
          <div className="mt-3 grid gap-3 rounded-xl p-3.5 md:grid-cols-4" style={{ background: "var(--surface-2)" }}>
            <Field label="接入方式">
              <select className="field !py-1.5 !text-xs" value={transport} onChange={(e) => setTransport(e.target.value as "http" | "inprocess")}>
                <option value="http" disabled={!agent?.online}>
                  独立进程（Agent 协议）
                </option>
                <option value="inprocess" disabled={!agent?.in_process}>
                  同进程（开发调试）
                </option>
              </select>
            </Field>
            <Field label="回放来源（哪一次录制）">
              <select className="field mono !py-1.5 !text-xs" value={replayFrom} onChange={(e) => setReplayFrom(e.target.value)} disabled={mode !== "replay"}>
                {(sources.data ?? []).length === 0 && <option value="">（没有覆盖这套方案的录制）</option>}
                {(sources.data ?? []).map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {r.run_id}（{r.mode}，k={r.reps}）
                  </option>
                ))}
              </select>
            </Field>
            <Field label="每个场景重复次数（真实调用）">
              <input type="number" min={1} max={10} className="field !py-1.5 !text-xs" value={reps} onChange={(e) => setReps(Number(e.target.value))} disabled={mode !== "live"} />
            </Field>
            <Field label="并发数">
              <input type="number" min={1} max={16} className="field !py-1.5 !text-xs" value={concurrency} onChange={(e) => setConcurrency(Number(e.target.value))} />
            </Field>
          </div>
        </details>

        <div className="mt-5 flex flex-wrap items-center gap-4 border-t border-line pt-4">
          <button onClick={start} disabled={!canStart} className="btn btn-primary btn-lg">
            <Icon name="play" size={17} />
            {stream.status === "running" ? "测试进行中…" : "开始测试"}
          </button>
          {agent && (
            <p className="text-sm text-ink-2">
              将对 <b className="text-ink">{agent.name} {version}</b> 运行「{planName(suite)}」：{n} 个场景
              {mode === "live" ? ` × ${reps} 次，真实调用模型` : "，回放录制"}
              {transport === "http" ? "，通过 Agent 协议访问独立进程" : "，同进程加载"}。
            </p>
          )}
        </div>
        {(error || stream.error) && <ErrorNote error={(error ?? stream.error)!} />}
      </Step>

      {runId && stream.plan && (
        <>
          <Progress runId={runId} status={stream.status} done={Object.keys(stream.results).length} total={stream.plan.total} failed={failed.length} writes={writes.length} />
          <div className="grid gap-5 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
            <Card title="逐个场景的进度" subtitle="灰色：等待；闪烁：执行中；彩色：已判定，点击查看那一次执行的审计时间轴">
              <div className="space-y-3">
                {Object.keys(CATEGORY_NAMES).map((cat) => {
                  const ids = stream.plan!.cases.filter((c) => (categoryOf.get(c) ?? "C?") === cat);
                  if (!ids.length) return null;
                  return (
                    <div key={cat}>
                      <div className="mb-1 text-[11px] font-semibold text-ink-2">{CATEGORY_NAMES[cat]}</div>
                      <div className="flex flex-wrap gap-1">
                        {ids.flatMap((id) =>
                          Array.from({ length: stream.plan!.reps }, (_, rep) => {
                            const key = `${id}#${rep}`;
                            const r = stream.results[key];
                            const step = stream.active[key];
                            return (
                              <div key={key} className={!r && step ? "animate-pulse" : ""}>
                                <OutcomeCell
                                  outcome={r?.outcome ?? null}
                                  label={key}
                                  onClick={r ? () => (window.location.hash = href("runs", runId, "cases", id, rep)) : undefined}
                                  tooltip={() => (
                                    <div>
                                      <div className="mono">
                                        {id} · 第 {rep + 1} 次
                                      </div>
                                      {r ? <b>{r.outcome}</b> : step ? <span>执行中 · 第 {step} 步</span> : <span>等待中</span>}
                                      {r?.findings.length ? <div className="text-critical">{[...new Set(r.findings.map((f) => f.rule_id))].join("、")}</div> : null}
                                    </div>
                                  )}
                                />
                              </div>
                            );
                          }),
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </Card>
            <Card title="实时事件" subtitle={`Agent 的对话与工具调用${transport === "http" ? "（经 Agent 协议拉取）" : ""}`}>
              <ul className="space-y-1">
                {stream.ticker.map((t, i) => (
                  <li key={`${t.case_id}-${t.rep}-${t.event.step_id}-${i}`} className="pop flex min-w-0 items-center gap-2 text-[11px]">
                    <span className="mono w-28 shrink-0 truncate text-muted">
                      {t.case_id.split("-").slice(0, 2).join("-")} r{t.rep}
                    </span>
                    <span className="mono w-10 shrink-0 text-muted">#{t.event.step_id}</span>
                    <Pill color={t.event.kind === "injection" ? "var(--s7)" : t.event.kind === "write_receipt" ? "var(--s3)" : t.event.kind === "user_message" ? "var(--s1)" : undefined}>{t.event.kind}</Pill>
                    <span className="min-w-0 flex-1 truncate text-ink-2">{t.event.tool ?? t.event.content ?? ""}</span>
                  </li>
                ))}
              </ul>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

function Step({ n, title, right, children }: { n: number; title: string; right?: ReactNode; children: ReactNode }) {
  return (
    <section className="card p-5 sm:p-6">
      <header className="mb-4 flex items-center gap-3">
        <span className="grid size-7 place-items-center rounded-full text-[13px] font-semibold text-white" style={{ background: "var(--brand)" }}>
          {n}
        </span>
        <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
        <span className="ml-auto">{right}</span>
      </header>
      {children}
    </section>
  );
}

function PlanChoice({ id, count, checked, onPick, small }: { id: string; count: number; checked: boolean; onPick: () => void; small?: boolean }) {
  const plan = PLANS[id];
  return (
    <button role="radio" aria-checked={checked} onClick={onPick} className={`choice ${small ? "p-3" : "p-4"}`}>
      <div className="flex items-baseline justify-between gap-2">
        <span className={`${small ? "text-[13px]" : "text-sm"} font-semibold text-ink`}>{plan?.name ?? id}</span>
        <span className="shrink-0 text-[11px] text-muted">{count} 个场景</span>
      </div>
      {plan && <p className="mt-1 text-xs leading-relaxed text-ink-2">{plan.what}</p>}
    </button>
  );
}

function Progress({ runId, status, done, total, failed, writes }: { runId: string; status: string; done: number; total: number; failed: number; writes: number }) {
  const finished = status === "done";
  const ok = finished && failed === 0;
  const tone = !finished ? { bg: "var(--surface)", line: "var(--border)" } : ok ? { bg: "var(--good-wash)", line: "var(--good)" } : { bg: "var(--critical-wash)", line: "var(--critical)" };
  return (
    <section className="rounded-xl p-5" style={{ background: tone.bg, border: `1px solid ${tone.line}` }}>
      <div className="flex flex-wrap items-center gap-4">
        <div className="min-w-0 flex-1">
          <div className="text-[15px] font-semibold text-ink">
            {!finished && `正在测试… ${done} / ${total}`}
            {ok && `测试完成：${total} 次执行全部通过`}
            {finished && !ok && `测试完成：${total} 次执行中 ${failed} 次发现问题${writes ? `，其中 ${writes} 次未经同意改了数据` : ""}`}
          </div>
          {!finished && (
            <div className="mt-2 h-1.5 overflow-hidden rounded-full" style={{ background: "var(--surface-3)" }}>
              <div className="h-full rounded-full transition-all" style={{ width: `${total ? (done / total) * 100 : 0}%`, background: "var(--brand)" }} />
            </div>
          )}
        </div>
        {finished && (
          <div className="flex gap-2">
            <a href={href("runs", runId)} className="btn btn-primary btn-md">
              查看测试报告
            </a>
            {!ok && (
              <a href={href("defects")} className="btn btn-secondary btn-md">
                问题与复测
              </a>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-[11px] text-muted">
      {label}
      {children}
    </label>
  );
}

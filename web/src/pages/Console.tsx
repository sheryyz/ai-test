import { useEffect, useMemo, useRef, useState } from "react";
import { OutcomeCell } from "../components/charts";
import { Card, ErrorNote, Pill, StatTile } from "../components/ui";
import { api, type Outcome, type RunResult } from "../lib/api";
import { CATEGORY_NAMES, href, useAsync } from "../lib/util";

interface LiveTrace {
  case_id: string;
  rep: number;
  event: { step_id: number; turn_id: number; kind: string; tool: string | null; status: string | null; injection_id: string | null; content: string | null };
}

export function Console() {
  const targets = useAsync(() => api.targets(), []);
  const settings = useAsync(() => api.settings(), []);
  const runs = useAsync(() => api.runs(), []);
  const [target, setTarget] = useState("travel");
  const [version, setVersion] = useState("v1");
  const [suite, setSuite] = useState("smoke");
  const [mode, setMode] = useState<"live" | "replay">("replay");
  const [reps, setReps] = useState(1);
  const [concurrency, setConcurrency] = useState(6);
  const [replayFrom, setReplayFrom] = useState("");
  const [error, setError] = useState<string | null>(null);

  const [runId, setRunId] = useState<string | null>(null);
  const [plan, setPlan] = useState<{ cases: string[]; reps: number; total: number } | null>(null);
  const [results, setResults] = useState<Record<string, RunResult>>({});
  const [active, setActive] = useState<Record<string, number>>({});
  const [ticker, setTicker] = useState<LiveTrace[]>([]);
  const [status, setStatus] = useState<"idle" | "running" | "done" | "error">("idle");
  const sourceRef = useRef<EventSource | null>(null);
  const suiteCases = useAsync(() => api.suite(target, suite), [target, suite]);
  const categoryOf = useMemo(() => new Map((suiteCases.data ?? []).map((c) => [c.case_id, c.category])), [suiteCases.data]);

  useEffect(() => {
    if (settings.data && settings.data.live_available) setMode((m) => m);
  }, [settings.data]);
  useEffect(() => () => sourceRef.current?.close(), []);

  const candidates = (runs.data ?? []).filter((r) => r.mode === "live" && r.suite === suite && r.agent_version === version && r.target === target);
  useEffect(() => {
    if (mode === "replay" && !candidates.some((c) => c.run_id === replayFrom)) setReplayFrom(candidates[0]?.run_id ?? "");
  }, [mode, suite, version, candidates.map((c) => c.run_id).join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

  async function start() {
    setError(null);
    try {
      const body: Record<string, unknown> = { target, version, suite, mode, concurrency };
      if (mode === "live") body.reps = reps;
      else body.replay_from = replayFrom;
      const { run_id } = await api.startRun(body);
      setRunId(run_id);
      setResults({});
      setActive({});
      setTicker([]);
      setStatus("running");
      const es = new EventSource(`/api/runs/${encodeURIComponent(run_id)}/stream`);
      sourceRef.current?.close();
      sourceRef.current = es;
      es.addEventListener("start", (e) => setPlan(JSON.parse((e as MessageEvent).data)));
      es.addEventListener("trace", (e) => {
        const t = JSON.parse((e as MessageEvent).data) as LiveTrace;
        setActive((a) => ({ ...a, [`${t.case_id}#${t.rep}`]: t.event.step_id }));
        setTicker((x) => [t, ...x].slice(0, 14));
      });
      es.addEventListener("result", (e) => {
        const r = JSON.parse((e as MessageEvent).data) as RunResult;
        setResults((x) => ({ ...x, [`${r.case_id}#${r.rep}`]: r }));
      });
      es.addEventListener("done", () => {
        setStatus("done");
        es.close();
        runs.reload();
      });
      es.addEventListener("error", (e) => {
        const data = (e as MessageEvent).data;
        if (data) setError(JSON.parse(data).message);
        setStatus((s) => (s === "running" && data ? "error" : s));
      });
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const counts = Object.values(results).reduce<Partial<Record<Outcome, number>>>((acc, r) => ({ ...acc, [r.outcome]: (acc[r.outcome] ?? 0) + 1 }), {});
  const target_ = targets.data?.find((t) => t.name === target);
  const field = "rounded-md px-2 py-1.5 text-xs";
  const fieldStyle = { background: "var(--surface-2)", border: "1px solid var(--border)", color: "var(--ink)" };

  return (
    <div className="space-y-5">
      <Card title="测试控制台" subtitle="选择目标与套件后启动；执行过程通过 SSE 实时推送，每格代表一次执行">
        <div className="grid gap-3 md:grid-cols-4 lg:grid-cols-8">
          <Field label="被测目标">
            <select className={field} style={fieldStyle} value={target} onChange={(e) => setTarget(e.target.value)}>
              {(targets.data ?? []).map((t) => (
                <option key={t.name} value={t.name}>
                  {t.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Agent 版本">
            <select className={field} style={fieldStyle} value={version} onChange={(e) => setVersion(e.target.value)}>
              {(target_?.versions ?? ["v1"]).map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </Field>
          <Field label="用例套件">
            <select className={field} style={fieldStyle} value={suite} onChange={(e) => setSuite(e.target.value)}>
              {Object.entries(target_?.suites ?? {}).map(([s, n]) => (
                <option key={s} value={s}>
                  {s}（{n} 条）
                </option>
              ))}
            </select>
          </Field>
          <Field label="模式">
            <select className={field} style={fieldStyle} value={mode} onChange={(e) => setMode(e.target.value as "live" | "replay")}>
              <option value="replay">Replay 回放</option>
              <option value="live" disabled={!settings.data?.live_available}>
                Live 真实模型{settings.data?.live_available ? `（${settings.data.model}）` : "（未配置 Key）"}
              </option>
            </select>
          </Field>
          {mode === "replay" ? (
            <Field label="回放来源" wide>
              <select className={`${field} mono`} style={fieldStyle} value={replayFrom} onChange={(e) => setReplayFrom(e.target.value)}>
                {candidates.length === 0 && <option value="">（没有可回放的 Live 运行）</option>}
                {candidates.map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {r.run_id}
                  </option>
                ))}
              </select>
            </Field>
          ) : (
            <Field label="重复次数 k">
              <input type="number" min={1} max={10} className={field} style={fieldStyle} value={reps} onChange={(e) => setReps(Number(e.target.value))} />
            </Field>
          )}
          <Field label="并发">
            <input type="number" min={1} max={16} className={field} style={fieldStyle} value={concurrency} onChange={(e) => setConcurrency(Number(e.target.value))} />
          </Field>
          <div className="flex items-end">
            <button
              onClick={start}
              disabled={status === "running" || (mode === "replay" && !replayFrom)}
              className="w-full rounded-md px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50"
              style={{ background: "var(--s1)" }}
            >
              {status === "running" ? "执行中…" : "开始测试"}
            </button>
          </div>
        </div>
        {mode === "replay" && <p className="mt-2 text-[11px] text-muted">回放模式逐次校验请求哈希，复现录制时的模型回复，不调用任何 API；结果会被明确标注为 replay。</p>}
        {error && <ErrorNote error={error} />}
      </Card>

      {runId && plan && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <StatTile label="运行" value={<span className="mono block break-all text-xs">{runId}</span>} sub={status === "done" ? <a className="text-s1" href={href("runs", runId)}>查看运行详情 →</a> : status} />
            <StatTile label="进度" value={`${Object.keys(results).length} / ${plan.total}`} />
            <StatTile label="通过" value={counts.PASS ?? 0} accent="var(--good)" />
            <StatTile label="失败" value={counts.FAIL ?? 0} accent="var(--critical)" />
            <StatTile label="错误" value={counts.ERROR ?? 0} accent="var(--warning)" />
          </div>
          <div className="grid gap-5 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
            <Card title="执行网格" subtitle="灰色：等待；闪烁：执行中（显示当前步骤）；彩色：已判定">
              <div className="space-y-3">
                {Object.keys(CATEGORY_NAMES).map((cat) => {
                  const ids = plan.cases.filter((c) => (categoryOf.get(c) ?? "C?") === cat);
                  if (!ids.length) return null;
                  return (
                    <div key={cat}>
                      <div className="mb-1 text-[11px] font-semibold text-ink-2">
                        <span className="mono mr-1 text-muted">{cat}</span>
                        {CATEGORY_NAMES[cat]}
                      </div>
                      <div className="flex flex-wrap gap-1">
                        {ids.flatMap((id) =>
                          Array.from({ length: plan.reps }, (_, rep) => {
                            const key = `${id}#${rep}`;
                            const r = results[key];
                            const step = active[key];
                            return (
                              <div key={key} className={!r && step ? "animate-pulse" : ""}>
                                <OutcomeCell
                                  outcome={r?.outcome ?? null}
                                  label={key}
                                  onClick={r ? () => (window.location.hash = href("runs", runId, "cases", id, rep)) : undefined}
                                  tooltip={() => (
                                    <div>
                                      <div className="mono">{id} r{rep}</div>
                                      {r ? <b>{r.outcome}</b> : step ? <span>执行中 · step {step}</span> : <span>等待中</span>}
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
            <Card title="实时事件" subtitle="最近的轨迹事件（来自被测 Agent 的 SDK 插桩）">
              <ul className="space-y-1">
                {ticker.map((t, i) => (
                  <li key={`${t.case_id}-${t.rep}-${t.event.step_id}-${i}`} className="pop flex min-w-0 items-center gap-2 text-[11px]">
                    <span className="mono w-28 shrink-0 truncate text-muted">{t.case_id.split("-").slice(0, 2).join("-")} r{t.rep}</span>
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

function Field({ label, children, wide }: { label: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <label className={`flex flex-col gap-1 text-[11px] text-muted ${wide ? "md:col-span-2" : ""}`}>
      {label}
      {children}
    </label>
  );
}

import { useEffect, useMemo, useState } from "react";
import { OutcomeCell } from "../components/charts";
import { Card, ErrorNote, Pill, StatTile } from "../components/ui";
import { api } from "../lib/api";
import { useRunStream } from "../lib/stream";
import { CATEGORY_NAMES, href, useAsync, versionColor } from "../lib/util";

const SUITE_LABELS: Record<string, string> = {
  acceptance: "验收套件",
  smoke: "冒烟",
  main: "主用例集",
  variants: "措辞变体",
  holdout: "holdout",
  core: "审批核心",
};

export function Console({ preset }: { preset?: { target?: string; version?: string; suite?: string } }) {
  const ws = useAsync(() => api.workspace(), []);
  const [target, setTarget] = useState(preset?.target ?? "travel");
  const [version, setVersion] = useState(preset?.version ?? "v1");
  const [suite, setSuite] = useState(preset?.suite ?? "acceptance");
  const [transport, setTransport] = useState<"http" | "inprocess">("http");
  const [mode, setMode] = useState<"live" | "replay">("replay");
  const [reps, setReps] = useState(3);
  const [concurrency, setConcurrency] = useState(6);
  const [replayFrom, setReplayFrom] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const stream = useRunStream(runId, () => ws.reload());

  const agent = ws.data?.agents.find((a) => a.name === target);
  const suiteCases = useAsync(() => api.suite(target, suite), [target, suite]);
  const sources = useAsync(() => api.replaySources(target, version, suite), [target, version, suite]);
  const categoryOf = useMemo(() => new Map((suiteCases.data ?? []).map((c) => [c.case_id, c.category])), [suiteCases.data]);
  const liveOk = transport === "http" ? Boolean(agent?.online && agent.info?.llm.live_available) : true;

  useEffect(() => {
    if (agent && !agent.versions.includes(version)) setVersion(agent.versions[0]);
    if (agent && !(suite in agent.suites)) setSuite(agent.suites.acceptance ? "acceptance" : Object.keys(agent.suites)[0]);
    if (agent && !agent.online && transport === "http" && agent.in_process) setTransport("inprocess");
  }, [agent?.name, agent?.online]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const ids = (sources.data ?? []).map((s) => s.run_id);
    if (!ids.includes(replayFrom)) setReplayFrom(ids[0] ?? "");
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

  const field = "rounded-md px-2 py-1.5 text-xs";
  const fieldStyle = { background: "var(--surface-2)", border: "1px solid var(--border)", color: "var(--ink)" };
  const failed = Object.values(stream.results).filter((r) => r.outcome === "FAIL");
  const writes = failed.filter((r) => r.findings.some((f) => f.kind === "side_effect_violation"));

  return (
    <div className="space-y-5">
      <Card title="1 · 选择被测 Agent" subtitle="被测 Agent 是独立进程中的测试对象；平台只通过 Agent 协议访问它">
        {ws.error && <ErrorNote error={ws.error} />}
        <div className="grid gap-2 md:grid-cols-2" role="radiogroup" aria-label="被测 Agent">
          {(ws.data?.agents ?? []).map((a) => (
            <button
              key={a.name}
              role="radio"
              aria-checked={a.name === target}
              onClick={() => setTarget(a.name)}
              className="rounded-lg p-3 text-left"
              style={{ background: a.name === target ? "var(--s1-wash)" : "var(--surface-2)", border: `1px solid ${a.name === target ? "var(--s1)" : "var(--border)"}` }}
            >
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-ink">{a.name}</span>
                <span className="inline-flex items-center gap-1 text-[11px] text-ink-2">
                  <span aria-hidden className="size-1.5 rounded-full" style={{ background: a.online ? "var(--good)" : "var(--muted)" }} />
                  {a.online ? `在线 ${a.url}` : "离线"}
                </span>
              </div>
              <div className="mt-1 text-xs text-ink-2">{a.description}</div>
            </button>
          ))}
        </div>
        {agent && !agent.online && (
          <p className="mt-2 text-xs text-ink-2">
            Agent 进程离线：到 <a className="text-s1 hover:underline" href={href("agents")}>被测 Agent</a> 页一键启动，或改用同进程加载。
          </p>
        )}
      </Card>

      <Card title="2 · 配置测试任务" subtitle="批量执行、自动判定；执行过程通过 SSE 实时推送，每格代表一次执行">
        <div className="grid gap-3 md:grid-cols-4 lg:grid-cols-8">
          <Field label="接入方式">
            <select className={field} style={fieldStyle} value={transport} onChange={(e) => setTransport(e.target.value as "http" | "inprocess")}>
              <option value="http" disabled={!agent?.online}>
                独立进程（HTTP）
              </option>
              <option value="inprocess" disabled={!agent?.in_process}>
                同进程（开发调试）
              </option>
            </select>
          </Field>
          <Field label="Agent 版本">
            <select className={field} style={fieldStyle} value={version} onChange={(e) => setVersion(e.target.value)}>
              {(agent?.versions ?? ["v1"]).map((v) => (
                <option key={v} value={v}>
                  {v}
                  {agent?.fixed_versions[v] ? ` · 修复版为 ${agent.fixed_versions[v]}` : ""}
                </option>
              ))}
            </select>
          </Field>
          <Field label="用例套件" wide>
            <select className={field} style={fieldStyle} value={suite} onChange={(e) => setSuite(e.target.value)}>
              {Object.entries(agent?.suites ?? {}).map(([s, n]) => (
                <option key={s} value={s}>
                  {SUITE_LABELS[s] ?? s}（{n} 条）
                </option>
              ))}
            </select>
          </Field>
          <Field label="模式">
            <select className={field} style={fieldStyle} value={mode} onChange={(e) => setMode(e.target.value as "live" | "replay")}>
              <option value="replay">Replay 回放</option>
              <option value="live" disabled={!liveOk}>
                Live 真实模型{liveOk ? "" : "（未配置 Key）"}
              </option>
            </select>
          </Field>
          {mode === "replay" ? (
            <Field label="回放来源（覆盖本套件全部用例的录制）" wide>
              <select className={`${field} mono`} style={fieldStyle} value={replayFrom} onChange={(e) => setReplayFrom(e.target.value)}>
                {(sources.data ?? []).length === 0 && <option value="">（没有覆盖本套件的录制，请用 Live）</option>}
                {(sources.data ?? []).map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {r.run_id}（{r.mode}，k={r.reps}）
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
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button
            onClick={start}
            disabled={stream.status === "running" || (mode === "replay" && !replayFrom)}
            className="rounded-md px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
            style={{ background: "var(--s1)" }}
          >
            {stream.status === "running" ? "执行中…" : "开始测试"}
          </button>
          <p className="text-[11px] text-muted">
            {mode === "replay"
              ? "回放：逐次校验请求哈希，复现录制时的真实模型回复，不调用 API；工具执行与数据库写入每次都真实重新发生。结果标注为 replay。"
              : "Live：被测 Agent 用它自己的模型 Key 真实调用模型；每例重复 k 次，报告违规概率与 pass^k。"}
          </p>
        </div>
        {(error || stream.error) && <ErrorNote error={(error ?? stream.error)!} />}
      </Card>

      {runId && stream.plan && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <StatTile label="运行" value={<span className="mono block break-all text-xs">{runId}</span>} sub={stream.status === "done" ? <a className="text-s1" href={href("runs", runId)}>查看运行详情 →</a> : stream.status} />
            <StatTile label="进度" value={`${Object.keys(stream.results).length} / ${stream.plan.total}`} />
            <StatTile label="通过" value={stream.counts.PASS ?? 0} accent="var(--good)" />
            <StatTile label="失败" value={stream.counts.FAIL ?? 0} accent="var(--critical)" sub={writes.length ? `${writes.length} 次越权且真实写入` : undefined} />
            <StatTile label="错误" value={stream.counts.ERROR ?? 0} accent="var(--warning)" />
          </div>
          {stream.status === "done" && failed.length > 0 && (
            <div className="card flex flex-wrap items-center gap-3 p-4" style={{ borderColor: "var(--critical)" }}>
              <span className="text-sm text-ink">
                自动定位到 <b>{failed.length}</b> 次失败执行
                {writes.length ? `，其中 ${writes.length} 次越权并真实写入了数据库` : ""}。
              </span>
              <a className="rounded-md px-3 py-1.5 text-xs font-semibold text-white" style={{ background: "var(--critical)" }} href={href("defects")}>
                查看缺陷并复测 →
              </a>
              {failed.slice(0, 4).map((r) => (
                <a key={`${r.case_id}-${r.rep}`} className="mono text-xs text-s1 hover:underline" href={href("runs", runId, "cases", r.case_id, r.rep)}>
                  {r.case_id} r{r.rep}
                </a>
              ))}
            </div>
          )}
          <div className="grid gap-5 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
            <Card title="执行网格" subtitle="灰色：等待；闪烁：执行中（显示当前步骤）；彩色：已判定，点击查看审计时间轴">
              <div className="space-y-3">
                {Object.keys(CATEGORY_NAMES).map((cat) => {
                  const ids = stream.plan!.cases.filter((c) => (categoryOf.get(c) ?? "C?") === cat);
                  if (!ids.length) return null;
                  return (
                    <div key={cat}>
                      <div className="mb-1 text-[11px] font-semibold text-ink-2">
                        <span className="mono mr-1 text-muted">{cat}</span>
                        {CATEGORY_NAMES[cat]}
                      </div>
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
                                        {id} r{rep}
                                      </div>
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
            <Card title="实时事件" subtitle={`来自被测 Agent 的插桩轨迹${transport === "http" ? "（经 Agent 协议拉取）" : ""}`}>
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
      {!runId && agent && (
        <p className="text-xs text-muted">
          当前选择：<Pill color={versionColor(version)}>{agent.name} {version}</Pill> · {SUITE_LABELS[suite] ?? suite} · {transport === "http" ? `独立进程 ${agent.url}` : "同进程"}
        </p>
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

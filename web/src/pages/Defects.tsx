import { useMemo, useState } from "react";
import { OutcomeCell } from "../components/charts";
import { Card, ErrorNote, Loading, PageHeader, Pill, Segmented, StatTile, Term } from "../components/ui";
import { api, type Defect, type DefectKind, type DefectStatus } from "../lib/api";
import { useRunStream } from "../lib/stream";
import { CATEGORY_NAMES, ISSUE_TEXT, href, planName, useAsync, versionColor } from "../lib/util";
import { DiffView, FindingCard } from "./TraceExplorer";
import { STATUS_COLORS } from "./Workspace";

const KIND_COLORS: Record<DefectKind, string> = {
  side_effect: "var(--critical)",
  attempt: "var(--serious)",
  claim: "var(--warning)",
  task: "var(--muted)",
};

export const STATUS_SHORT: Record<DefectStatus, string> = {
  open: "待修复",
  awaiting_retest: "待复测",
  fix_failed: "修复后仍失败",
  mitigated: "已止损",
  fixed_verified: "已修复",
};

export function StatusTag({ d }: { d: Pick<Defect, "status" | "status_label"> }) {
  return (
    <span title={d.status_label} className="inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold" style={{ background: "var(--surface-3)", color: "var(--ink)" }}>
      <span aria-hidden className="size-2 rounded-full" style={{ background: STATUS_COLORS[d.status] }} />
      {STATUS_SHORT[d.status]}
    </span>
  );
}

function occurrenceText(d: Defect): string {
  const e = d.executions;
  const parts = [];
  if (e.live) parts.push(`Live 失败 ${e.live_fail}/${e.live}`);
  if (e.replay) parts.push(`回放 ${e.replay_fail}/${e.replay}`);
  return parts.join(" · ");
}

export function Defects() {
  const data = useAsync(() => api.defects(), []);
  const [target, setTarget] = useState("all");
  const [status, setStatus] = useState<"all" | DefectStatus>("all");
  const [kind, setKind] = useState<"all" | "safety" | DefectKind>("safety");
  const rows = useMemo(
    () =>
      (data.data?.defects ?? [])
        .filter((d) => target === "all" || d.target === target)
        .filter((d) => status === "all" || d.status === status)
        .filter((d) => kind === "all" || (kind === "safety" ? d.kind !== "task" : d.kind === kind)),
    [data.data, target, status, kind],
  );
  if (data.error) return <ErrorNote error={data.error} />;
  if (!data.data) return <Loading what="缺陷" />;
  const s = data.data.summary;
  const targets = [...new Set(data.data.defects.map((d) => d.target))].sort();
  return (
    <div className="space-y-5">
      <PageHeader title="问题与复测">
        同一个 Agent 版本在同一个场景上的失败归为一个问题，并自动定位到第一次出错的步骤。开发者修好后，用同一个场景在修复版上<Term>复测</Term>：每次重复执行都通过，问题才标记为「已修复」。
      </PageHeader>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <StatTile label="问题总数" value={s.total} sub="Agent 版本 × 场景" />
        <StatTile label={ISSUE_TEXT.side_effect} value={s.by_kind.side_effect} accent="var(--critical)" sub="越权并真实写入了数据库" />
        <StatTile label={ISSUE_TEXT.attempt} value={s.by_kind.attempt} accent="var(--serious)" />
        <StatTile label="已修复 / 已止损" value={`${s.by_status.fixed_verified} / ${s.by_status.mitigated}`} accent="var(--good)" sub="复测通过 / 不再改动数据" />
        <StatTile label="修复后仍失败 / 待修复" value={`${s.by_status.fix_failed} / ${s.by_status.open}`} accent="var(--critical)" />
      </div>
      <Card
        title="问题列表"
        subtitle={`${rows.length} 个；默认只看越权和“说的和做的不一致”（任务没完成的另列）`}
        right={
          <div className="flex flex-wrap gap-2">
            <Segmented label="被测 Agent" value={target} onChange={setTarget} options={[{ value: "all", label: "全部" }, ...targets.map((t) => ({ value: t, label: t }))]} />
            <Segmented
              label="类型"
              value={kind}
              onChange={setKind}
              options={[
                { value: "safety", label: "越权与陈述" },
                { value: "side_effect", label: "改了数据" },
                { value: "task", label: "任务" },
                { value: "all", label: "全部" },
              ]}
            />
            <Segmented
              label="状态"
              value={status}
              onChange={setStatus}
              options={[{ value: "all", label: "全部" }, ...(Object.keys(s.status_labels) as DefectStatus[]).map((k) => ({ value: k, label: STATUS_SHORT[k] }))]}
            />
          </div>
        }
      >
        <div className="scroll-x">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="hairline-b text-muted">
                {["状态", "问题", "被测 Agent", "场景", "出错步骤", "出现次数", "修复版复测"].map((h) => (
                  <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => (
                <tr key={d.id} className="hairline-b cursor-pointer align-top hover:bg-[var(--surface-2)]" onClick={() => (window.location.hash = href("defects", d.id))}>
                  <td className="px-2 py-2">
                    <StatusTag d={d} />
                  </td>
                  <td className="px-2 py-2">
                    <Pill color={KIND_COLORS[d.kind]}>{ISSUE_TEXT[d.kind]}</Pill>
                  </td>
                  <td className="whitespace-nowrap px-2 py-2">
                    <Pill color={versionColor(d.version)}>
                      {d.target} {d.version}
                    </Pill>
                  </td>
                  <td className="min-w-[220px] px-2 py-2">
                    <a href={href("defects", d.id)} className="font-medium text-ink hover:underline">
                      {d.title}
                    </a>
                    <div className="mono text-[11px] text-muted">{d.case_id}</div>
                  </td>
                  <td className="mono whitespace-nowrap px-2 py-2 text-ink-2">{d.first.first_bad_step ? `第 ${d.first.first_bad_step} 步` : "—"}</td>
                  <td className="whitespace-nowrap px-2 py-2 text-ink-2">{occurrenceText(d)}</td>
                  <td className="whitespace-nowrap px-2 py-2 text-ink-2">
                    {d.retest ? `${d.retest.version}：${d.retest.passed}/${d.retest.total} 通过` : d.fixed_version ? `${d.fixed_version}：未复测` : "无修复版本"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

export function DefectDetail({ id }: { id: string }) {
  const data = useAsync(() => api.defects(), [id]);
  const d = data.data?.defects.find((x) => x.id === id) ?? null;
  const first = d?.latest;
  const bundle = useAsync(() => (first ? api.caseBundle(first.run_id, d!.case_id, first.rep) : Promise.resolve(null)), [first?.run_id, first?.rep, d?.case_id]);
  if (data.error) return <ErrorNote error={data.error} />;
  if (!data.data) return <Loading what="缺陷" />;
  if (!d || !first) return <ErrorNote error={`没有这个缺陷：${id}（可能已被重新判定或证据已删除）`} />;
  const traceHref = href("runs", first.run_id, "cases", d.case_id, first.rep);
  return (
    <div className="space-y-5">
      <nav className="text-xs text-muted">
        <a href={href("defects")} className="hover:text-ink">
          问题与复测
        </a>{" "}
        / <span className="text-ink-2">{d.id}</span>
      </nav>
      <header className="card p-5">
        <div className="flex flex-wrap items-center gap-2">
          <StatusTag d={d} />
          <Pill color={KIND_COLORS[d.kind]}>{ISSUE_TEXT[d.kind]}</Pill>
          <Pill color={versionColor(d.version)}>
            {d.target} {d.version}
          </Pill>
          {d.category && (
            <Pill>
              {d.category} · {CATEGORY_NAMES[d.category] ?? ""}
            </Pill>
          )}
          {d.has_injection && <Pill color="var(--s7)">含注入点</Pill>}
          <span className="mono text-xs text-muted">{d.case_id}</span>
        </div>
        <h1 className="mt-2 text-xl font-semibold text-ink">{d.title}</h1>
        <p className="mt-1 text-xs text-ink-2">
          首次发现于「{planName(d.first.suite)}」· {occurrenceText(d)}；命中规则 <span className="mono">{d.rules.join("、") || "—"}</span>
        </p>
      </header>

      <div className="grid gap-5 lg:grid-cols-[1.2fr_1fr]">
        <Card
          title="平台自动定位的证据"
          subtitle={`最近一次出现：${first.run_id} 第 ${first.rep} 次执行（${first.mode === "live" ? "Live 真实模型" : "回放"}，${first.transport === "http" ? "独立进程" : "同进程"}）`}
          right={
            <a href={traceHref} className="rounded-md px-3 py-1.5 text-xs font-semibold text-white" style={{ background: "var(--s1)" }}>
              查看完整审计时间轴
            </a>
          }
        >
          {bundle.error && (window.__CONSENTTRACE_STATIC__ ? <p className="text-sm text-muted">这次执行的证据不在本离线报告包含的运行中。</p> : <ErrorNote error={bundle.error} />)}
          {bundle.error ? null : !bundle.data ? (
            <Loading what="证据" />
          ) : bundle.data.verdict.findings.length ? (
            <div className="space-y-2.5">
              {bundle.data.verdict.findings.map((f, i) => (
                <FindingCard key={i} f={f} onJump={() => (window.location.hash = traceHref)} />
              ))}
            </div>
          ) : (
            <div className="space-y-1.5 text-xs">
              {bundle.data.verdict.assertions
                .filter((a) => a.status === "FAIL")
                .map((a) => (
                  <div key={a.rule_id} className="rounded-md p-2.5" style={{ background: "var(--surface-2)" }}>
                    <span className="mono font-semibold text-ink">{a.rule_id}</span> <span className="text-ink-2">{a.detail}</span>
                  </div>
                ))}
            </div>
          )}
        </Card>
        <Card title="数据库实际变化" subtitle="被测 Agent 业务库的前后快照差分（来自 Agent 的状态接口）">
          {bundle.data ? <DiffView diff={bundle.data.state_diff} after={bundle.data.state_after} /> : bundle.error ? <p className="text-sm text-muted">—</p> : <Loading />}
        </Card>
      </div>

      <RetestPanel d={d} onDone={data.reload} />

      <Card title={`全部出现记录（${d.occurrences.length}）`} subtitle="只统计仍然有效的判定：被重新判定过的运行以最新一次为准；回放复现的是同一份录制">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="hairline-b text-muted">
              {["运行", "执行", "模式", "接入", "套件", "命中规则", "首个违规", ""].map((h) => (
                <th key={h} className="px-2 py-2 font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {d.occurrences.map((o) => (
              <tr key={`${o.run_id}-${o.rep}`} className="hairline-b">
                <td className="mono px-2 py-1.5 text-ink">{o.run_id}</td>
                <td className="px-2 py-1.5 text-ink-2">r{o.rep}</td>
                <td className="px-2 py-1.5 text-ink-2">{o.mode === "live" ? "Live" : `回放 ← ${o.replay_from ?? ""}`}</td>
                <td className="px-2 py-1.5 text-ink-2">{o.transport === "http" ? "独立进程" : "同进程"}</td>
                <td className="px-2 py-1.5 text-ink-2">{o.suite}</td>
                <td className="mono px-2 py-1.5 text-ink-2">{o.rules.join(", ") || "任务断言"}</td>
                <td className="mono px-2 py-1.5 text-ink-2">{o.first_bad_step ? `step ${o.first_bad_step}` : "—"}</td>
                <td className="px-2 py-1.5">
                  <a className="text-s1 hover:underline" href={href("runs", o.run_id, "cases", d.case_id, o.rep)}>
                    审计 →
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function RetestPanel({ d, onDone }: { d: Defect; onDone: () => void }) {
  const sources = useAsync(
    () => (d.fixed_version && !window.__CONSENTTRACE_STATIC__ ? api.replaySourcesForCase(d.target, d.fixed_version, d.case_id) : Promise.resolve([])),
    [d.target, d.fixed_version, d.case_id],
  );
  const settings = useAsync(() => (window.__CONSENTTRACE_STATIC__ ? Promise.resolve([]) : api.agents()), []);
  const agent = settings.data?.find((a) => a.name === d.target);
  const [mode, setMode] = useState<"replay" | "live">("replay");
  const [runId, setRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const stream = useRunStream(runId, onDone);
  const hasRecording = (sources.data ?? []).length > 0;
  const liveOk = Boolean(agent?.online && agent.info?.llm.live_available);
  const r = d.retest;

  if (!d.fixed_version) {
    return (
      <Card title="修复与复测" subtitle="这个版本还没有登记修复版本">
        <p className="text-sm text-ink-2">
          这个 Agent 还没有登记修复版本。修好 Agent 后，可以直接对同一个场景重新「发起测试」看问题是否消失；如果要保留修复前后两个版本对比复测，在 <span className="mono">configs/targets.yaml</span> 的 <span className="mono">fixed_versions</span> 里登记修复版本（例如 <span className="mono">{`{${d.version}: ${d.version}-fix}`}</span>）。
        </p>
      </Card>
    );
  }

  async function start() {
    setError(null);
    try {
      const res = await api.retest({ id: d.id, mode, transport: agent?.online ? "http" : "inprocess", reps: mode === "live" ? 3 : undefined });
      setRunId(res.run_id);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <Card
      title={`修复与复测：在 ${d.fixed_version} 上重跑同一条用例`}
      subtitle="同样的初始数据、可信用户事件、注入点与种子；回放模式复现修复版录制的真实模型回复，工具与数据库写入每次都重新执行"
    >
      <div className="grid gap-5 lg:grid-cols-2">
        <div>
          <div className="mb-2 text-xs font-semibold text-ink">最近一次修复版执行</div>
          {r ? (
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2 text-xs text-ink-2">
                <span className="text-lg font-semibold" style={{ color: r.passed === r.total ? "var(--good-text)" : "var(--critical)" }}>
                  {r.passed}/{r.total} 通过
                </span>
                <span className="mono">{r.run_id}</span>
                <Pill>{r.mode === "live" ? "Live" : "回放"}</Pill>
                <Pill>{r.transport === "http" ? "独立进程" : "同进程"}</Pill>
                {r.is_retest && <Pill color="var(--good)">由复测发起</Pill>}
              </div>
              <div className="flex gap-1.5">
                {r.outcomes.map((o) => (
                  <a key={o.rep} href={href("runs", r.run_id, "cases", d.case_id, o.rep)}>
                    <OutcomeCell outcome={o.outcome} label={`r${o.rep}`} tooltip={() => <span>r{o.rep} · {o.outcome}{o.rules.length ? ` · ${o.rules.join("、")}` : ""}</span>} />
                  </a>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted">修复版还没有执行过这条用例。</p>
          )}
        </div>
        {window.__CONSENTTRACE_STATIC__ ? (
          <p className="text-xs text-muted">离线报告只读：复测需要连接 ConsentTrace 服务（consenttrace serve）。</p>
        ) : (
        <div>
          <div className="mb-2 text-xs font-semibold text-ink">现在复测</div>
          <div className="flex flex-wrap items-center gap-2">
            <Segmented
              label="复测模式"
              value={mode}
              onChange={setMode}
              options={[
                { value: "replay", label: hasRecording ? "回放（无需 Key）" : "回放（无录制）" },
                { value: "live", label: liveOk ? `Live × 3（${agent?.info?.llm.model}）` : "Live（Agent 未配置 Key）" },
              ]}
            />
            <button
              onClick={start}
              disabled={stream.status === "running" || (mode === "replay" ? !hasRecording : !liveOk)}
              className="rounded-md px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
              style={{ background: "var(--s1)" }}
            >
              {stream.status === "running" ? "复测中…" : "开始复测"}
            </button>
          </div>
          <p className="mt-1.5 text-[11px] text-muted">
            {mode === "replay"
              ? hasRecording
                ? `回放来源：${sources.data![0].run_id}（${sources.data![0].mode}）`
                : "修复版没有这条用例的录制，请用 Live"
              : "Live 会调用被测 Agent 自己的模型，重复 3 次"}
            ；接入方式：{agent?.online ? `独立进程 ${agent.url}` : "同进程（Agent 进程离线）"}
          </p>
          {error && <p className="mt-2 text-xs text-critical">{error}</p>}
          {runId && (
            <div className="mt-3 rounded-lg p-3 text-xs" style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}>
              <div className="mb-1.5 flex items-center gap-2">
                <span className="mono text-ink">{runId}</span>
                <span className="text-muted">{stream.status === "running" ? `执行中 ${Object.keys(stream.results).length}/${stream.plan?.total ?? "…"}` : stream.status === "done" ? "已完成，缺陷状态已刷新" : stream.status}</span>
              </div>
              <div className="flex gap-1.5">
                {Array.from({ length: stream.plan?.total ?? 0 }, (_, rep) => {
                  const res = stream.results[`${d.case_id}#${rep}`];
                  return (
                    <div key={rep} className={!res && stream.active[`${d.case_id}#${rep}`] ? "animate-pulse" : ""}>
                      <OutcomeCell
                        outcome={res?.outcome ?? null}
                        label={`r${rep}`}
                        onClick={res ? () => (window.location.hash = href("runs", runId, "cases", d.case_id, rep)) : undefined}
                        tooltip={() => <span>r{rep} · {res?.outcome ?? (stream.active[`${d.case_id}#${rep}`] ? `step ${stream.active[`${d.case_id}#${rep}`]}` : "等待")}</span>}
                      />
                    </div>
                  );
                })}
              </div>
              {stream.error && <p className="mt-2 text-critical">{stream.error}</p>}
            </div>
          )}
        </div>
        )}
      </div>
    </Card>
  );
}

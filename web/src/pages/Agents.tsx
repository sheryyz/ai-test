import { useState } from "react";
import { Card, ErrorNote, Loading, Pill } from "../components/ui";
import { api, type AgentDescription, type ProbeReport, type TargetInfo, type WorkspaceAgent } from "../lib/api";
import { href, useAsync, versionColor } from "../lib/util";
import { CAPABILITY_LABELS } from "./Workspace";

const CHECK_COLORS = { PASS: "var(--good)", FAIL: "var(--critical)", SKIP: "var(--muted)" } as const;

export function Agents() {
  const ws = useAsync(() => api.workspace(), []);
  const targets = useAsync(() => api.targets(), []);
  if (ws.error) return <ErrorNote error={ws.error} />;
  if (!ws.data || !targets.data) return <Loading what="被测 Agent" />;
  return (
    <div className="space-y-5">
      <section className="card p-5">
        <h1 className="text-xl font-semibold text-ink">被测 Agent</h1>
        <p className="mt-1.5 max-w-3xl text-sm text-ink-2">
          被测 Agent 是测试对象，运行在自己的进程里，用自己的模型 Key。ConsentTrace 只知道它的地址，通过 Agent 协议拿取对话、工具轨迹和业务状态。Agent 声明了哪些能力，平台就开启对应的断言；缺少某项能力时，相关断言显示 UNSUPPORTED，不会给出 PASS。
        </p>
      </section>
      {ws.data.agents.map((a) => (
        <AgentPanel key={a.name} a={a} t={targets.data!.find((t) => t.name === a.name)} onChange={ws.reload} />
      ))}
      <ConnectNew />
    </div>
  );
}

function AgentPanel({ a, t, onChange }: { a: WorkspaceAgent; t?: TargetInfo; onChange: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<ProbeReport | null>(null);
  const [desc, setDesc] = useState<AgentDescription | null>(null);
  const caps = a.info?.capabilities;

  async function act(name: string, fn: () => Promise<void>) {
    setBusy(name);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card
      title={
        <span className="flex flex-wrap items-center gap-2">
          {a.name}
          <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium" style={{ background: a.online ? "var(--good-wash)" : "var(--surface-3)" }}>
            <span aria-hidden className="size-1.5 rounded-full" style={{ background: a.online ? "var(--good)" : "var(--muted)" }} />
            {a.online ? "在线" : "离线"}
          </span>
        </span>
      }
      subtitle={a.description}
      right={
        <div className="flex flex-wrap gap-2">
          {!a.online && a.launchable && (
            <Button onClick={() => act("start", async () => void (await api.startAgent(a.name), onChange()))} busy={busy === "start"}>
              启动进程
            </Button>
          )}
          <Button onClick={() => act("probe", async () => setReport(await api.probe({ target: a.name })))} busy={busy === "probe"} disabled={!a.url}>
            接入检查
          </Button>
          <Button onClick={() => act("describe", async () => setDesc(await api.describe(a.name)))} busy={busy === "describe"}>
            工具定义
          </Button>
          <a href={href("console", a.name, a.versions[0], a.suites.acceptance ? "acceptance" : Object.keys(a.suites)[0])} className="rounded-md px-3 py-1.5 text-xs font-semibold text-white" style={{ background: "var(--s1)" }}>
            测试此 Agent
          </a>
        </div>
      }
    >
      {a.origin && <p className="-mt-2 mb-3 text-xs text-muted">{a.origin}</p>}
      <div className="grid gap-4 lg:grid-cols-3">
        <Section title="连接">
          <KV k="协议地址" v={<span className="mono">{a.url ?? "—"}</span>} />
          <KV k="进程" v={a.managed ? "由本平台启动的子进程" : a.online ? "外部启动" : a.launchable ? "未启动（可一键启动）" : "未启动"} />
          <KV k="同进程加载" v={a.in_process ? "可用（开发与离线测试）" : "不可用"} />
          <KV k="模型" v={a.info ? (a.info.llm.live_available ? `${a.info.llm.model}（Agent 自己的 Key）` : "未配置 Key，只能回放") : "—"} />
          {!a.online && a.error && <p className="mt-1 text-[11px] text-critical">{a.error}</p>}
        </Section>
        <Section title="能力声明 → 平台能做的审计">
          {caps ? (
            <ul className="space-y-1 text-xs">
              {(Object.keys(CAPABILITY_LABELS) as (keyof typeof CAPABILITY_LABELS)[]).map((k) => (
                <li key={k} className="flex items-start gap-2">
                  <span aria-hidden className="mt-0.5 inline-grid size-4 shrink-0 place-items-center rounded-full text-[10px] text-white" style={{ background: caps[k] ? "var(--good)" : "var(--muted)" }}>
                    {caps[k] ? "✓" : "–"}
                  </span>
                  <span>
                    <b className="text-ink">{CAPABILITY_LABELS[k].label}</b> <span className="text-ink-2">{caps[k] ? CAPABILITY_LABELS[k].unlocks : "未声明：相关断言为 UNSUPPORTED"}</span>
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted">离线时读不到能力声明。</p>
          )}
        </Section>
        <Section title="测试资产">
          <KV k="版本" v={<span className="flex flex-wrap gap-1">{a.versions.map((v) => <Pill key={v} color={versionColor(v)}>{v}{a.fixed_versions[v] ? ` → ${a.fixed_versions[v]}` : ""}</Pill>)}</span>} />
          <KV k="契约" v={t ? <a className="mono text-s1 hover:underline" href={href("suite")}>{t.contract_id}（{t.rules} 条规则）</a> : "—"} />
          <KV k="用例集" v={<span className="flex flex-wrap gap-1">{Object.entries(a.suites).map(([s, n]) => <Pill key={s}>{s} {n}</Pill>)}</span>} />
          {a.last_run && <KV k="最近运行" v={<a className="mono text-s1 hover:underline" href={href("runs", a.last_run.run_id)}>{a.last_run.run_id}</a>} />}
        </Section>
      </div>
      {error && <p className="mt-3 text-xs text-critical">{error}</p>}
      {report && <ProbeTable report={report} />}
      {desc && <ToolList desc={desc} />}
    </Card>
  );
}

function ConnectNew() {
  const [url, setUrl] = useState("http://127.0.0.1:9200");
  const [report, setReport] = useState<ProbeReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <Card title="接入新的 Agent" subtitle="任何语言写的 Agent，实现 Agent 协议的 6 个接口即可接入（docs/agent_protocol.md）；Python Agent 可直接用 SDK 的 serve_agent 包一层">
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex min-w-64 flex-1 flex-col gap-1 text-[11px] text-muted">
          Agent 协议地址
          <input value={url} onChange={(e) => setUrl(e.target.value)} className="mono rounded-md px-2 py-1.5 text-xs" style={{ background: "var(--surface-2)", border: "1px solid var(--border)", color: "var(--ink)" }} />
        </label>
        <Button
          busy={busy}
          onClick={async () => {
            setBusy(true);
            setError(null);
            try {
              setReport(await api.probe({ url }));
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          接入检查
        </Button>
      </div>
      <ol className="mt-3 list-decimal space-y-1 pl-5 text-xs text-ink-2">
        <li>启动 Agent 进程，例如：<span className="mono">uv run python -m targets.approval_agent.service --port 9102</span></li>
        <li>在这里做接入检查：协议握手、自我描述、输出 / 轨迹 / 状态能力是否如实、会话之间是否隔离（不调用模型）</li>
        <li>
          在 <span className="mono">configs/targets.yaml</span> 登记 <span className="mono">service.url</span>、契约与用例集；契约可以在「契约工作台」由 AI 根据工具定义起草
        </li>
      </ol>
      {error && <p className="mt-3 text-xs text-critical">{error}</p>}
      {report && <ProbeResult report={report} />}
    </Card>
  );
}

/** What a probe found, laid out like a registered agent: connection, verified capabilities, registration, tools. */
function ProbeResult({ report }: { report: ProbeReport }) {
  const info = report.info;
  const caps = info?.capabilities;
  const status = Object.fromEntries(report.checks.map((c) => [c.key, c.status]));
  const reg = report.registered;
  const sensitive = new Map((reg?.actions ?? []).map((a) => [a.tool, a.action]));
  const verified: Record<string, string | undefined> = { output: status.output, trace: status.trace, state: status.state, inject_tool_response: status.inject };
  const known = useAsync(() => api.targets(), []);
  const base = (info?.name ?? "my-agent").replace(/[^A-Za-z0-9_-]/g, "-");
  const taken = new Set((known.data ?? []).map((t) => t.name));
  const slug = taken.has(base) ? `${base}-${new URL(report.url).port || "new"}` : base; // a name the registry does not use yet
  const snippet = `targets:
  ${slug}:
    description: ${info?.description || "（Agent 的一句话说明）"}
    service: {url: ${report.url}}
    contract: configs/${slug.replace(/-/g, "_")}_contract.yaml
    versions: [${(info?.versions ?? ["v1"]).join(", ")}]
    suites: {core: benchmarks/${slug.replace(/-/g, "_")}_core.yaml}`;
  return (
    <div className="mt-4 space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="rounded-full px-2.5 py-0.5 text-xs font-semibold text-white" style={{ background: report.ok ? "var(--good)" : "var(--critical)" }}>
          接入检查{report.ok ? "通过" : "未通过"}
        </span>
        {info ? (
          <span className="text-ink">
            <b>{info.name}</b> <span className="text-ink-2">{info.description}</span>
          </span>
        ) : (
          <span className="text-ink-2">没有拿到 Agent 的身份信息（协议握手失败）</span>
        )}
      </div>
      {info && caps && (
        <div className="grid gap-4 lg:grid-cols-3">
          <Section title="连接">
            <KV k="协议地址" v={<span className="mono">{report.url}</span>} />
            <KV k="协议版本" v={`v${info.protocol}`} />
            <KV k="版本" v={<span className="flex flex-wrap gap-1">{info.versions.map((v) => <Pill key={v} color={versionColor(v)}>{v}</Pill>)}</span>} />
            <KV k="模型" v={info.llm.live_available ? `${info.llm.model}（Agent 自己的 Key）` : "未配置 Key，只能回放"} />
            <KV k="回放" v={info.llm.replay ? "支持（平台下发录制，逐次校验请求哈希）" : "不支持"} />
          </Section>
          <Section title="能力声明 → 平台能做的审计（已逐项核对）">
            <ul className="space-y-1 text-xs">
              {(Object.keys(CAPABILITY_LABELS) as (keyof typeof CAPABILITY_LABELS)[]).map((k) => {
                const v = verified[k];
                return (
                  <li key={k} className="flex items-start gap-2">
                    <span aria-hidden className="mt-0.5 inline-grid size-4 shrink-0 place-items-center rounded-full text-[10px] text-white" style={{ background: caps[k] ? (v === "FAIL" ? "var(--critical)" : "var(--good)") : "var(--muted)" }}>
                      {caps[k] ? (v === "FAIL" ? "✕" : "✓") : "–"}
                    </span>
                    <span>
                      <b className="text-ink">{CAPABILITY_LABELS[k].label}</b>{" "}
                      <span className="text-ink-2">{caps[k] ? CAPABILITY_LABELS[k].unlocks : "未声明：相关断言为 UNSUPPORTED"}</span>
                      {caps[k] && v && <span className="ml-1 text-[11px] text-muted">（{v === "PASS" ? "已实测" : v === "SKIP" ? "需在用例中观察" : "实测不符"}）</span>}
                    </span>
                  </li>
                );
              })}
            </ul>
          </Section>
          {reg ? (
            <Section title="已登记为被测 Agent">
              <KV k="名称" v={<b className="text-ink">{reg.name}</b>} />
              {reg.origin && <KV k="来源" v={reg.origin} />}
              <KV k="契约" v={<span className="mono">{reg.contract_id}（{reg.actions.length} 个敏感动作、{reg.rules} 条规则）</span>} />
              <KV k="用例集" v={<span className="flex flex-wrap gap-1">{Object.entries(reg.suites).map(([n, c]) => <Pill key={n}>{n} {c}</Pill>)}</span>} />
              {Object.keys(reg.fixed_versions).length > 0 && (
                <KV k="修复版" v={Object.entries(reg.fixed_versions).map(([a, b]) => `${a} → ${b}`).join("；")} />
              )}
              <div className="flex flex-wrap gap-2 pt-1">
                <a href={href("console", reg.name, reg.versions[0], reg.suites.acceptance ? "acceptance" : Object.keys(reg.suites)[0])} className="rounded-md px-3 py-1.5 text-xs font-semibold text-white" style={{ background: "var(--s1)" }}>
                  测试此 Agent
                </a>
                <a href={href("defects")} className="rounded-md px-3 py-1.5 text-xs font-medium text-ink" style={{ background: "var(--surface)", border: "1px solid var(--border-strong)" }}>
                  查看缺陷
                </a>
              </div>
            </Section>
          ) : (
            <Section title="尚未登记：接下来三步">
              <ol className="list-decimal space-y-1 pl-4 text-xs text-ink-2">
                <li>把下面这段加入 <span className="mono">configs/targets.yaml</span>（已按这个 Agent 的实际信息填好）</li>
                <li>
                  AI 起草测试契约：<span className="mono">uv run consenttrace draft-contract --target {slug}</span>，在「契约工作台」确认后保存
                </li>
                <li>编写或由 AI 扩增用例，然后在「测试任务」里批量执行</li>
              </ol>
              <pre className="mono mt-2 overflow-auto rounded-md p-2 text-[11px] text-ink-2" style={{ background: "var(--surface)", border: "1px solid var(--border)" }}>
                {snippet}
              </pre>
            </Section>
          )}
        </div>
      )}
      <ProbeTable report={report} />
      {report.describe && <ToolList desc={report.describe} sensitive={sensitive} />}
    </div>
  );
}

function ProbeTable({ report }: { report: ProbeReport }) {
  return (
    <div className="mt-4 rounded-lg p-3" style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}>
      <div className="mb-1 text-xs font-semibold text-ink">逐项检查</div>
      <div className="mb-2 flex items-center gap-2 text-xs">
        <b className="text-ink">接入检查 {report.url}</b>
        <span className="rounded-full px-2 py-0.5 text-[11px] font-semibold text-white" style={{ background: report.ok ? "var(--good)" : "var(--critical)" }}>
          {report.ok ? "通过" : "未通过"}
        </span>
        <span className="text-muted">不调用模型；会话使用协议的脚本模式</span>
      </div>
      <table className="w-full text-xs">
        <tbody>
          {report.checks.map((c) => (
            <tr key={c.key} className="hairline-b align-top">
              <td className="w-28 py-1.5 pr-2 text-ink">{c.title}</td>
              <td className="w-16 py-1.5 pr-2">
                <span className="rounded px-1.5 py-0.5 text-[11px] font-semibold text-white" style={{ background: CHECK_COLORS[c.status] }}>
                  {c.status}
                </span>
              </td>
              <td className="py-1.5 text-ink-2">{c.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ToolList({ desc, sensitive }: { desc: AgentDescription; sensitive?: Map<string, string> }) {
  return (
    <div className="mt-4 grid gap-3 lg:grid-cols-2">
      <div className="rounded-lg p-3" style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}>
        <div className="mb-2 text-xs font-semibold text-ink">
          工具（{desc.tools.length}）{sensitive && sensitive.size > 0 && <span className="ml-1 font-normal text-muted">红色标记的是契约里的敏感动作，每次调用都核对授权</span>}
        </div>
        <ul className="space-y-1.5 text-xs">
          {desc.tools.map((t) => (
            <li key={t.function.name}>
              <span className="mono font-semibold text-ink">{t.function.name}</span>
              <span className="mono text-muted">({Object.keys(t.function.parameters.properties ?? {}).join(", ")})</span>
              {sensitive?.get(t.function.name) && <Pill color="var(--critical)">敏感动作 {sensitive.get(t.function.name)}</Pill>}
              <div className="text-ink-2">{t.function.description}</div>
            </li>
          ))}
        </ul>
      </div>
      <div className="rounded-lg p-3" style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}>
        <div className="mb-2 text-xs font-semibold text-ink">业务状态表</div>
        <ul className="space-y-1 text-xs">
          {Object.entries(desc.state_schema).map(([table, s]) => (
            <li key={table}>
              <span className="mono font-semibold text-ink">{table}</span> <span className="mono text-muted">pk({s.pk.join(", ")})</span>
              <div className="mono text-[11px] text-ink-2">{s.columns.join(", ")}</div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg p-3" style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}>
      <div className="mb-2 text-xs font-semibold text-ink">{title}</div>
      <div className="space-y-1.5">{children}</div>
    </div>
  );
}

function KV({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex gap-2 text-xs">
      <span className="w-16 shrink-0 text-muted">{k}</span>
      <span className="min-w-0 text-ink-2">{v}</span>
    </div>
  );
}

export function Button({ children, onClick, busy, disabled }: { children: React.ReactNode; onClick: () => void; busy?: boolean; disabled?: boolean }) {
  return (
    <button
      onClick={onClick}
      disabled={busy || disabled}
      className="rounded-md px-3 py-1.5 text-xs font-medium text-ink disabled:opacity-50"
      style={{ background: "var(--surface-2)", border: "1px solid var(--border-strong)" }}
    >
      {busy ? "…" : children}
    </button>
  );
}

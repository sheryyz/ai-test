import { useState } from "react";
import { Card, ErrorNote, Loading, PageHeader, Pill } from "../components/ui";
import { api, type AgentDescription, type Business, type ProbeReport, type TargetInfo, type WorkspaceAgent } from "../lib/api";
import { href, planName, useAsync, versionColor } from "../lib/util";
import { CAPABILITY_LABELS } from "./Workspace";

const CHECK_COLORS = { PASS: "var(--good)", FAIL: "var(--critical)", SKIP: "var(--muted)" } as const;

export function Agents() {
  const ws = useAsync(() => api.workspace(), []);
  const targets = useAsync(() => api.targets(), []);
  if (ws.error) return <ErrorNote error={ws.error} />;
  if (!ws.data || !targets.data) return <Loading what="被测 Agent" />;
  return (
    <div className="space-y-5">
      <PageHeader
        title="我的 Agent"
        right={
          <a href="#connect" className="btn btn-primary btn-md">
            + 接入新的 Agent
          </a>
        }
      >
        被测 Agent 运行在它自己的进程里、用它自己的模型 Key，平台只通过地址访问它，不改它的代码。Agent 能提供哪些信息（对话、工具调用、数据库状态），平台就开启对应的检查；缺少的检查会标为“不可测”，不会给出通过。
      </PageHeader>
      {ws.data.agents.map((a) => (
        <AgentPanel key={a.name} a={a} t={targets.data!.find((t) => t.name === a.name)} onChange={() => (ws.reload(), targets.reload())} />
      ))}
      <ConnectNew
        onRegistered={() => {
          ws.reload();
          targets.reload();
        }}
      />
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
          {a.like && <Pill color="var(--brand)">我接入的 · 沿用 {a.like} 的契约与场景</Pill>}
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
            检查连接
          </Button>
          <Button onClick={() => act("describe", async () => setDesc(await api.describe(a.name)))} busy={busy === "describe"}>
            工具定义
          </Button>
          {a.like && (
            <Button
              onClick={() =>
                act("remove", async () => {
                  if (!window.confirm(`移除 ${a.name}？只会删除接入登记，不影响 Agent 本身和已有的测试报告。`)) return;
                  await api.unregisterAgent(a.name);
                  onChange();
                })
              }
              busy={busy === "remove"}
            >
              移除
            </Button>
          )}
          <a href={href("console", a.name, a.versions[0], a.suites.acceptance ? "acceptance" : Object.keys(a.suites)[0])} className="btn btn-primary btn-sm">
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
        <Section title="它能提供的信息 → 平台能做的检查">
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
          <KV k="测试方案" v={<span className="flex flex-wrap gap-1">{Object.entries(a.suites).map(([s, n]) => <Pill key={s}>{planName(s)} {n}</Pill>)}</span>} />
          {a.last_run && <KV k="最近测试" v={<a className="text-s1 hover:underline" href={href("runs", a.last_run.run_id)}>{planName(a.last_run.suite)} · {new Date(a.last_run.finished_at).toLocaleString("zh-CN")}</a>} />}
        </Section>
      </div>
      {error && <p className="mt-3 text-xs text-critical">{error}</p>}
      {report && <ProbeTable report={report} />}
      {desc && <ToolList desc={desc} />}
    </Card>
  );
}

function ConnectNew({ onRegistered }: { onRegistered: () => void }) {
  const [url, setUrl] = useState("http://127.0.0.1:9201");
  const [report, setReport] = useState<ProbeReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function check() {
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      setReport(await api.probe({ url }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section id="connect" className="card scroll-mt-6 p-5 sm:p-6">
      <h2 className="text-[15px] font-semibold text-ink">接入新的 Agent</h2>
      <p className="mt-1 max-w-3xl text-xs leading-relaxed text-ink-2">
        三步完成：填地址并检查连接 → 选择它属于哪类业务 → 保存。任何语言写的 Agent，实现 Agent 协议的 6 个 HTTP 接口即可接入（<span className="mono">docs/agent_protocol.md</span>）；Python Agent 用 SDK 的 <span className="mono">serve_agent</span> 包一层即可。
      </p>
      <form
        className="mt-4 flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void check();
        }}
      >
        <label className="flex min-w-64 flex-1 flex-col gap-1 text-[11px] text-muted">
          Agent 地址
          <input value={url} onChange={(e) => setUrl(e.target.value)} className="field mono" />
        </label>
        <button type="submit" disabled={busy || !url} className="btn btn-primary btn-md">
          {busy ? "检查中…" : "检查连接"}
        </button>
      </form>
      <p className="mt-2 text-[11px] text-muted">
        想先试一下？在终端运行 <span className="mono text-ink-2">uv run python -m targets.tau_airline.service --port 9201</span>，再用上面的地址检查。检查不会调用模型，不产生费用。
      </p>
      {error && <p className="mt-3 text-xs text-critical">{error}</p>}
      {report && (
        <ProbeResult
          report={report}
          onRegistered={() => {
            onRegistered();
            void check(); // the same URL now shows as a connected agent
          }}
        />
      )}
    </section>
  );
}

function RegisterForm({ report, onRegistered }: { report: ProbeReport; onRegistered: () => void }) {
  const info = report.info!;
  const businesses = report.businesses ?? [];
  const firstOk = businesses.find((b) => b.compatible) ?? (businesses.some((b) => b.checked) ? undefined : businesses[0]);
  const [like, setLike] = useState(firstOk?.name ?? "");
  const [name, setName] = useState(`my-${info.name}`.toLowerCase().replace(/[^a-z0-9-]/g, "-").slice(0, 32));
  const [description, setDescription] = useState(info.description ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<{ name: string; versions: string[] } | null>(null);
  const picked = businesses.find((b) => b.name === like);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const res = await api.registerAgent({ name, url: report.url, like, description });
      setDone(res);
      onRegistered();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    const plan = picked?.suites.acceptance ? "acceptance" : Object.keys(picked?.suites ?? {})[0];
    return (
      <div className="mt-4 flex flex-wrap items-center gap-3 rounded-xl p-4" style={{ background: "var(--good-wash)", border: "1px solid var(--good)" }}>
        <span className="text-sm text-ink">
          已接入 <b>{done.name}</b>（版本 {done.versions.join("、")}），可以开始测试了。
        </span>
        <a href={href("console", done.name, done.versions[0], plan ?? "")} className="btn btn-primary btn-sm ml-auto">
          开始测试 →
        </a>
      </div>
    );
  }

  return (
    <div className="mt-4 rounded-xl p-4" style={{ border: "1px solid var(--brand)", background: "var(--brand-wash)" }}>
      <div className="text-sm font-semibold text-ink">它属于哪类业务？</div>
      <p className="mt-0.5 text-xs text-ink-2">选定后，这个 Agent 会沿用该业务已有的测试契约（哪些操作需要用户同意）和全部测试场景。平台已按 Agent 自己声明的工具逐一核对。</p>
      <div className="mt-3 grid gap-2 md:grid-cols-3" role="radiogroup" aria-label="业务类型">
        {businesses.map((b) => (
          <BusinessChoice key={b.name} b={b} checked={b.name === like} onPick={() => setLike(b.name)} />
        ))}
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-[1fr_2fr]">
        <label className="flex flex-col gap-1 text-[11px] text-muted">
          名称（小写字母、数字、连字符）
          <input value={name} onChange={(e) => setName(e.target.value)} className="field mono" />
        </label>
        <label className="flex flex-col gap-1 text-[11px] text-muted">
          一句话说明
          <input value={description} onChange={(e) => setDescription(e.target.value)} className="field" placeholder="例如：我们的航空客服 Agent（测试环境）" />
        </label>
      </div>
      {error && <p className="mt-3 text-xs text-critical">{error}</p>}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button onClick={save} disabled={busy || !like || !name || (picked ? picked.checked && !picked.compatible : true)} className="btn btn-primary btn-md">
          {busy ? "保存中…" : "保存并接入"}
        </button>
        <span className="text-[11px] text-muted">保存在本机 runs/_workspace/agents.yaml，随时可以移除。</span>
      </div>
      {!businesses.some((b) => b.compatible) && (
        <p className="mt-3 text-xs text-ink-2">
          这个 Agent 的工具和现有业务都对不上，说明它是一种新业务：需要先在「契约工作台」由 AI 根据它的工具定义起草测试契约，再准备测试场景，然后在 <span className="mono">configs/targets.yaml</span> 中登记（下方“手动登记”有按它的实际信息填好的模板）。
        </p>
      )}
    </div>
  );
}

function BusinessChoice({ b, checked, onPick }: { b: Business; checked: boolean; onPick: () => void }) {
  const disabled = b.checked && !b.compatible;
  return (
    <button role="radio" aria-checked={checked} disabled={disabled} onClick={onPick} className="choice p-3">
      <div className="flex items-center gap-2">
        <span className="text-[13px] font-semibold text-ink">{b.name}</span>
        {b.compatible && <Pill color="var(--good)">工具匹配</Pill>}
      </div>
      <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-ink-2">{b.description}</p>
      <p className="mt-1.5 text-[11px] text-muted">
        {disabled ? `缺少工具：${b.missing.join("、")}` : `${b.rules} 条授权规则 · ${Object.entries(b.suites).map(([s, n]) => `${planName(s)} ${n}`).slice(0, 2).join(" · ")}`}
      </p>
    </button>
  );
}

/** What a probe found, laid out like a registered agent: connection, verified capabilities, registration, tools. */
function ProbeResult({ report, onRegistered }: { report: ProbeReport; onRegistered: () => void }) {
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
          连接检查{report.ok ? "通过" : "未通过"}
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
          <Section title="它能提供的信息 → 平台能做的检查（已逐项实测）">
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
            <Section title="还没有接入">
              <p className="text-xs leading-relaxed text-ink-2">{report.ok ? "检查通过。在下方选择它属于哪类业务，保存后就可以测试。" : "检查没有通过，先按下面的逐项检查修好 Agent 再试。"}</p>
              <details className="pt-1 text-[11px]">
                <summary className="cursor-pointer text-muted hover:text-ink">新业务：手动登记到 configs/targets.yaml</summary>
                <ol className="mt-2 list-decimal space-y-1 pl-4 text-ink-2">
                  <li>把下面这段加入 <span className="mono">configs/targets.yaml</span></li>
                  <li>
                    AI 起草测试契约：<span className="mono">uv run consenttrace draft-contract --target {slug}</span>，在「契约工作台」确认后保存
                  </li>
                  <li>编写或由 AI 扩增测试场景，然后在「发起测试」里运行</li>
                </ol>
                <pre className="mono mt-2 overflow-auto rounded-md p-2 text-[11px] text-ink-2" style={{ background: "var(--surface)", border: "1px solid var(--border)" }}>
                  {snippet}
                </pre>
              </details>
            </Section>
          )}
        </div>
      )}
      {!reg && report.ok && info && <RegisterForm report={report} onRegistered={onRegistered} />}
      <details>
        <summary className="cursor-pointer text-xs font-medium text-ink-2 hover:text-ink">逐项检查结果与工具定义</summary>
        <ProbeTable report={report} />
        {report.describe && <ToolList desc={report.describe} sensitive={sensitive} />}
      </details>
    </div>
  );
}

function ProbeTable({ report }: { report: ProbeReport }) {
  return (
    <div className="mt-4 rounded-lg p-3" style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}>
      <div className="mb-1 text-xs font-semibold text-ink">逐项检查</div>
      <div className="mb-2 flex items-center gap-2 text-xs">
        <b className="text-ink">连接检查 {report.url}</b>
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

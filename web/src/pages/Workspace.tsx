import { OutcomeBar } from "../components/charts";
import { Card, ErrorNote, Loading, PageHeader, Pill } from "../components/ui";
import { api, type Capabilities, type Defect, type DefectStatus, type Workspace as WorkspaceData, type WorkspaceAgent } from "../lib/api";
import { href, useAsync, versionColor } from "../lib/util";

export const CAPABILITY_LABELS: Record<keyof Omit<Capabilities, "notes">, { label: string; unlocks: string }> = {
  output: { label: "输出", unlocks: "回复内容检查" },
  trace: { label: "轨迹", unlocks: "每次敏感调用发生时的授权判定" },
  state: { label: "状态", unlocks: "真实写入核验与任务终态" },
  inject_tool_response: { label: "注入", unlocks: "工具返回注入、RAG 投毒、故障注入" },
  visible_reasoning: { label: "可见推理", unlocks: "模型返回的推理文本（仅供参考）" },
};

export const STATUS_COLORS: Record<DefectStatus, string> = {
  fixed_verified: "var(--good)",
  mitigated: "var(--s3)",
  fix_failed: "var(--critical)",
  awaiting_retest: "var(--warning)",
  open: "var(--serious)",
};

/** For contest reviewers: the acceptance path, how the four path-2 directions map onto the product, and the raw boards. */
export function Review() {
  const ws = useAsync(() => api.workspace(), []);
  if (ws.error) return <ErrorNote error={ws.error} />;
  if (!ws.data) return <Loading what="评审说明" />;
  const w = ws.data;
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="面向比赛评审" title="评审说明">
        这一页给评审老师：按下面 5 步可以亲自验证平台的核心能力，每一步都链接到可以重新执行的页面；下方是赛题路径二四类测试工具在本平台中的位置。普通用户从「首页」开始即可，不需要看这一页。
      </PageHeader>

      <AcceptancePath steps={w.acceptance} />

      <ToolMap w={w} />

      <Card title="被测 Agent" subtitle="每个都是独立进程中的测试对象；同一个测试内核，只换契约与用例" right={<a className="text-xs text-s1 hover:underline" href={href("agents")}>接入检查与管理 →</a>}>
        <div className="grid gap-3 md:grid-cols-2">
          {w.agents.map((a) => (
            <AgentCard key={a.name} a={a} />
          ))}
        </div>
      </Card>

      <div className="grid gap-5 lg:grid-cols-[1.15fr_1fr]">
        <DefectBoard w={w} />
        <RecentRuns w={w} />
      </div>
    </div>
  );
}

function ToolMap({ w }: { w: WorkspaceData }) {
  const attacks = useAsync(() => api.attacks("travel").catch(() => null), []);
  const kb = useAsync(() => api.kb("travel").catch(() => null), []);
  const a = attacks.data;
  const k = kb.data;
  const s = w.defects.summary;
  const tools = [
    {
      title: "智能体自动化测试框架",
      what: "批量执行多轮授权用例，规则引擎逐步判定，缺陷归并与修复复测，版本回归对比",
      stat: `${s.total} 个缺陷 · ${s.by_status.fixed_verified} 个复测通过`,
      links: [
        ["发起测试", href("console")],
        ["问题与复测", href("defects")],
        ["版本对比", href("compare")],
      ],
    },
    {
      title: "RAG 知识库测试工具",
      what: "检测冲突、冗余与结构错误，用 Agent 自己的检索器评估 Recall@k / MRR，识别检索投毒段落",
      stat: k ? `Recall@1 ${k.retrieval?.recall_at_1.num}/${k.retrieval?.queries} · 投毒识别 ${k.poisoning.llm_flagged ?? k.poisoning.flagged}/${k.poisoning.passages}` : "尚未体检",
      links: [["RAG 知识库体检", href("kb")]],
    },
    {
      title: "对抗性用例自动生成器",
      what: "大模型按攻击样式 × 目标生成间接注入，确定性校验后冻结，挂到载体用例上测注入攻击成功率",
      stat: a ? `注入库 ${a.library.entries.length} 条 · 已测 ${a.runs.map((r) => r.version).join("/") || "—"}` : "尚未生成",
      links: [
        ["对抗用例生成", href("attacks")],
        ["契约工作台（AI 起草契约）", href("workbench")],
      ],
    },
    {
      title: "智能体行为可视化与审计平台",
      what: "三泳道时间轴：可信用户通道、Agent 与工具通道（含可见推理）、业务状态通道；首个违规步骤与数据库差分",
      stat: "每次执行都可回放审计",
      links: [
        ["测试报告", href("runs")],
        ["实验分析", href("analysis")],
      ],
    },
  ];
  return (
    <Card title="路径二的四类测试工具" subtitle="同一个测试内核，四个方向的能力都作用在独立进程中的被测 Agent 上；数字来自最近一次真实运行">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {tools.map((t) => (
          <div key={t.title} className="flex flex-col rounded-lg p-3.5" style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}>
            <div className="text-[14px] font-semibold text-ink">{t.title}</div>
            <p className="mt-1 flex-1 text-xs leading-relaxed text-ink-2">{t.what}</p>
            <div className="mono mt-2 text-[11px] text-ink">{t.stat}</div>
            <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs">
              {t.links.map(([label, to]) => (
                <a key={to} href={to} className="text-s1 hover:underline">
                  {label} →
                </a>
              ))}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function AcceptancePath({ steps }: { steps: WorkspaceData["acceptance"] }) {
  const done = steps.filter((s) => s.done).length;
  return (
    <Card title="验收路径" subtitle={`评委可按这 5 步亲自验证：已有证据 ${done}/${steps.length} 步；每一步都可以点进去重新执行`}>
      <ol className="grid gap-2 md:grid-cols-5">
        {steps.map((s, i) => (
          <li key={s.key}>
            <a href={s.href} className="flex h-full flex-col rounded-lg p-3 transition-colors hover:brightness-[0.98]" style={{ background: s.done ? "var(--good-wash)" : "var(--surface-2)", border: "1px solid var(--border)" }}>
              <div className="flex items-center gap-2">
                <span aria-hidden className="inline-grid size-5 place-items-center rounded-full text-[11px] font-semibold text-white" style={{ background: s.done ? "var(--good)" : "var(--muted)" }}>
                  {s.done ? "✓" : i + 1}
                </span>
                <span className="text-[11px] text-muted">第 {i + 1} 步 · {s.done ? "已有证据" : "待完成"}</span>
              </div>
              <div className="mt-2 text-[13px] font-semibold leading-snug text-ink">{s.title}</div>
              <div className="mono mt-1 break-all text-[11px] text-ink-2">{s.detail}</div>
            </a>
          </li>
        ))}
      </ol>
    </Card>
  );
}

function AgentCard({ a }: { a: WorkspaceAgent }) {
  const caps = a.info?.capabilities;
  return (
    <div className="rounded-lg p-4" style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[15px] font-semibold text-ink">{a.name}</span>
        <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium" style={{ background: a.online ? "var(--good-wash)" : "var(--surface-3)", color: "var(--ink)" }}>
          <span aria-hidden className="size-1.5 rounded-full" style={{ background: a.online ? "var(--good)" : "var(--muted)" }} />
          {a.online ? "在线" : "离线"}
        </span>
        <span className="mono text-[11px] text-muted">{a.url ?? "仅同进程"}</span>
      </div>
      <p className="mt-1.5 text-xs text-ink-2">{a.description}</p>
      {a.origin && <p className="mt-1 text-[11px] text-muted">{a.origin}</p>}
      <div className="mt-2.5 flex flex-wrap gap-1">
        {a.versions.map((v) => (
          <Pill key={v} color={versionColor(v)}>
            {v}
            {a.fixed_versions[v] ? ` → 修复版 ${a.fixed_versions[v]}` : ""}
          </Pill>
        ))}
        {caps &&
          (Object.keys(CAPABILITY_LABELS) as (keyof typeof CAPABILITY_LABELS)[])
            .filter((k) => caps[k])
            .map((k) => <Pill key={k}>{CAPABILITY_LABELS[k].label}</Pill>)}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
        {a.last_run ? (
          <a href={href("runs", a.last_run.run_id)} className="min-w-0 flex-1">
            <div className="mb-1 text-[11px] text-muted">
              最近：{a.last_run.version} · {a.last_run.suite} · {a.last_run.mode}
            </div>
            <OutcomeBar counts={a.last_run.counts} total={a.last_run.executions} compact />
          </a>
        ) : (
          <span className="flex-1 text-muted">还没有运行</span>
        )}
        <a href={href("console", a.name, a.versions[0], a.suites.acceptance ? "acceptance" : Object.keys(a.suites)[0])} className="rounded-md px-2.5 py-1 font-semibold text-white" style={{ background: "var(--s1)" }}>
          测试
        </a>
      </div>
    </div>
  );
}

function DefectBoard({ w }: { w: WorkspaceData }) {
  const s = w.defects.summary;
  const order: DefectStatus[] = ["open", "awaiting_retest", "fix_failed", "mitigated", "fixed_verified"];
  return (
    <Card title="缺陷看板" subtitle={`${s.total} 个缺陷（Agent 版本 × 用例），从全部有效运行的判定中归并`} right={<a className="text-xs text-s1 hover:underline" href={href("defects")}>全部问题 →</a>}>
      <div className="mb-3 flex h-2.5 overflow-hidden rounded-full" role="img" aria-label="缺陷状态分布">
        {order.map((k) => (s.by_status[k] ? <div key={k} style={{ width: `${(s.by_status[k] / s.total) * 100}%`, background: STATUS_COLORS[k] }} /> : null))}
      </div>
      <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-5">
        {order.map((k) => (
          <div key={k} className="text-xs">
            <div className="flex items-center gap-1.5 text-ink-2">
              <span aria-hidden className="size-2 rounded-full" style={{ background: STATUS_COLORS[k] }} />
              {s.status_labels[k]}
            </div>
            <div className="mt-0.5 text-lg font-semibold text-ink">{s.by_status[k]}</div>
          </div>
        ))}
      </div>
      <ul className="space-y-1.5">
        {w.defects.recent.map((d) => (
          <DefectLine key={d.id} d={d} />
        ))}
      </ul>
    </Card>
  );
}

export function DefectLine({ d }: { d: Defect }) {
  return (
    <li>
      <a href={href("defects", d.id)} className="flex min-w-0 items-center gap-2 rounded-md px-2 py-1.5 text-xs hover:bg-[var(--surface-2)]">
        <span aria-hidden className="size-2 shrink-0 rounded-full" style={{ background: STATUS_COLORS[d.status] }} />
        <span className="shrink-0 font-medium text-ink">
          {d.target} {d.version}
        </span>
        <span className="min-w-0 flex-1 truncate text-ink-2">{d.title}</span>
        <span className="shrink-0 text-muted">{d.kind_label}</span>
      </a>
    </li>
  );
}

function RecentRuns({ w }: { w: WorkspaceData }) {
  return (
    <Card title="最近的测试任务" subtitle="复测任务会标出它复测的是哪个缺陷" right={<a className="text-xs text-s1 hover:underline" href={href("runs")}>全部测试报告 →</a>}>
      <ul className="space-y-2">
        {w.recent_runs.map((r) => (
          <li key={r.run_id}>
            <a href={href("runs", r.run_id)} className="block rounded-md px-2 py-1.5 hover:bg-[var(--surface-2)]">
              <div className="flex flex-wrap items-center gap-1.5 text-xs">
                <Pill color={versionColor(r.version)}>
                  {r.target} {r.version}
                </Pill>
                <span className="text-ink-2">
                  {r.suite} · {r.mode} · {r.transport === "http" ? "独立进程" : "同进程"}
                </span>
                {r.retest_of && <Pill color="var(--good)">复测 {r.retest_of.defect.split(":").slice(1).join(" ")}</Pill>}
                <span className="ml-auto text-[11px] text-muted">{r.finished_at.slice(5, 16).replace("T", " ")}</span>
              </div>
              <div className="mt-1">
                <OutcomeBar counts={r.counts} total={r.executions} compact />
              </div>
            </a>
          </li>
        ))}
      </ul>
    </Card>
  );
}

import { OutcomeBar } from "../components/charts";
import { Icon, type IconName } from "../components/icons";
import { ErrorNote, Loading, Pill } from "../components/ui";
import { api, type Defect, type Workspace, type WorkspaceAgent } from "../lib/api";
import { pickFeatured } from "../lib/featured";
import { ISSUE_TEXT, href, planName, timeAgo, useAsync } from "../lib/util";
import { STATUS_COLORS } from "./Workspace";

const STEPS: { icon: IconName; title: string; text: string; to: string; cta: string }[] = [
  { icon: "plug", title: "接入 Agent", text: "填入 Agent 的地址，平台自动检查它能提供哪些测试信息", to: href("agents"), cta: "接入 Agent" },
  { icon: "test", title: "选择测试方案", text: "快速体检、完整测试或抗注入测试，一键开始", to: href("console"), cta: "发起测试" },
  { icon: "chat", title: "自动对话与判定", text: "模拟用户多轮对话，逐步核对授权，并检查数据库的实际变化", to: href("demo"), cta: "看一个例子" },
  { icon: "retest", title: "定位问题并复测", text: "直接定位到出错的那一步；修好后用同一个场景一键复测", to: href("defects"), cta: "问题与复测" },
];

const ATTENTION = new Set(["open", "fix_failed", "awaiting_retest"]);

export function Home() {
  const ws = useAsync(() => api.workspace(), []);
  const defects = useAsync(() => api.defects(), []);
  if (ws.error) return <ErrorNote error={ws.error} />;
  if (!ws.data) return <Loading what="首页" />;
  const w = ws.data;
  const all = defects.data?.defects ?? [];
  const featured = pickFeatured(all);
  const attention = all.filter((d) => ATTENTION.has(d.status) && d.kind !== "task").sort((a, b) => rank(a) - rank(b));
  const fixed = all.filter((d) => d.status === "fixed_verified").length;

  return (
    <div className="space-y-8">
      <section className="hero card overflow-hidden">
        <div className="grid gap-8 p-7 lg:grid-cols-[1.25fr_1fr] lg:p-9">
          <div>
            <Pill color="var(--brand)">AI Agent 授权安全测试</Pill>
            <h1 className="mt-4 text-[28px] font-semibold leading-tight tracking-tight text-ink sm:text-[32px]">
              你的 AI Agent，会不会在
              <br className="hidden sm:block" />
              用户没同意时就动手？
            </h1>
            <p className="mt-3 max-w-xl text-[15px] leading-relaxed text-ink-2">
              ConsentTrace 扮演真实用户，和你的 Agent 进行多轮对话：中途改主意、撤回同意、在工具返回里藏指令……然后对照数据库里真实发生的变化，找出 Agent 没等确认就执行的那一步。
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <a href={href("demo")} className="btn btn-primary btn-lg">
                <Icon name="play" size={17} />1 分钟看懂一个真实案例
              </a>
              <a href={href("console")} className="btn btn-secondary btn-lg">
                测试我的 Agent
                <Icon name="arrow" size={16} />
              </a>
            </div>
          </div>
          <FeaturedTeaser d={featured} loading={!defects.data} />
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-[15px] font-semibold text-ink">四步完成一次测试</h2>
        <ol className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {STEPS.map((s, i) => (
            <li key={s.title}>
              <a href={s.to} className="card group flex h-full flex-col p-4 transition-shadow hover:shadow-[var(--shadow-md)]">
                <div className="flex items-center gap-2.5">
                  <span className="grid size-9 place-items-center rounded-lg" style={{ background: "var(--brand-wash)", color: "var(--brand)" }}>
                    <Icon name={s.icon} size={18} />
                  </span>
                  <span className="text-[11px] font-semibold text-muted">第 {i + 1} 步</span>
                </div>
                <div className="mt-3 text-sm font-semibold text-ink">{s.title}</div>
                <p className="mt-1 flex-1 text-xs leading-relaxed text-ink-2">{s.text}</p>
                <span className="mt-3 inline-flex items-center gap-1 text-xs font-medium" style={{ color: "var(--brand)" }}>
                  {s.cta}
                  <Icon name="arrow" size={13} className="transition-transform group-hover:translate-x-0.5" />
                </span>
              </a>
            </li>
          ))}
        </ol>
      </section>

      <div className="grid gap-6 xl:grid-cols-[1.35fr_1fr]">
        <section className="min-w-0">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 className="text-[15px] font-semibold text-ink">我的 Agent</h2>
            <a href={href("agents")} className="text-xs font-medium" style={{ color: "var(--brand)" }}>
              + 接入新的 Agent
            </a>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            {w.agents.map((a) => (
              <AgentTile key={a.name} a={a} />
            ))}
          </div>
        </section>
        <div className="min-w-0 space-y-6">
          <section>
            <div className="mb-3 flex items-baseline justify-between">
              <h2 className="text-[15px] font-semibold text-ink">需要处理的问题</h2>
              <a href={href("defects")} className="text-xs font-medium" style={{ color: "var(--brand)" }}>
                全部问题 →
              </a>
            </div>
            <div className="card p-2">
              {!defects.data ? (
                <Loading what="问题" />
              ) : attention.length === 0 ? (
                <p className="px-3 py-6 text-center text-sm text-muted">暂时没有待处理的问题</p>
              ) : (
                <ul>
                  {attention.slice(0, 5).map((d) => (
                    <IssueRow key={d.id} d={d} />
                  ))}
                </ul>
              )}
              {defects.data && (
                <p className="hairline-t px-3 pb-1.5 pt-2.5 text-[11px] text-muted" style={{ borderTop: "1px solid var(--border)" }}>
                  待处理 {attention.length} 个 · 已修复并复测通过 {fixed} 个
                </p>
              )}
            </div>
          </section>
          <RecentReports w={w} />
        </div>
      </div>
    </div>
  );
}

function rank(d: Defect): number {
  return ({ side_effect: 0, attempt: 1, claim: 2, task: 3 } as const)[d.kind] * 10 + ({ fix_failed: 0, open: 1, awaiting_retest: 2 } as Record<string, number>)[d.status];
}

function FeaturedTeaser({ d, loading }: { d: Defect | null; loading: boolean }) {
  if (loading) return <div className="hidden lg:block" />;
  if (!d) {
    return (
      <div className="card flex flex-col justify-center p-6 text-sm text-ink-2">
        <b className="text-ink">还没有发现问题的测试记录</b>
        <p className="mt-1">先对一个 Agent 运行一次「快速体检」，这里会展示它发现的第一个真实问题。</p>
        <a href={href("console")} className="btn btn-primary btn-md mt-4 self-start">
          开始快速体检
        </a>
      </div>
    );
  }
  const retest = d.retest;
  return (
    <a href={href("demo")} className="card group block self-center p-5 transition-shadow hover:shadow-[var(--shadow-md)]" style={{ background: "var(--surface)" }}>
      <div className="flex items-center gap-2 text-[11px] font-medium text-muted">
        <span className="size-1.5 rounded-full" style={{ background: "var(--critical)" }} />
        平台发现的真实问题
      </div>
      <div className="mt-2 text-[15px] font-semibold leading-snug text-ink">{d.title}</div>
      <div className="mt-1 text-xs text-ink-2">
        被测：{d.target} {d.version}
      </div>
      <ol className="mt-4 space-y-2.5 text-xs">
        <TeaserStep color="var(--s1)" label="用户" text="确认了一件事，又在同一句话里改了参数" />
        <TeaserStep color="var(--critical)" label={`第 ${d.first.first_bad_step ?? "?"} 步`} text="Agent 没等用户重新确认就执行了" />
        <TeaserStep color="var(--critical)" label="数据库" text={d.kind === "side_effect" ? "被真实改写，用户撤回已经来不及" : "没有被写入"} />
        {retest && <TeaserStep color="var(--good)" label="修复后" text={`在 ${retest.version} 上复测：${retest.passed}/${retest.total} 次通过`} />}
      </ol>
      <span className="mt-4 inline-flex items-center gap-1 text-xs font-semibold" style={{ color: "var(--brand)" }}>
        逐步查看证据
        <Icon name="arrow" size={13} className="transition-transform group-hover:translate-x-0.5" />
      </span>
    </a>
  );
}

function TeaserStep({ color, label, text }: { color: string; label: string; text: string }) {
  return (
    <li className="flex items-start gap-2.5">
      <span className="mt-1 size-2 shrink-0 rounded-full" style={{ background: color }} />
      <span className="w-14 shrink-0 font-semibold text-ink">{label}</span>
      <span className="text-ink-2">{text}</span>
    </li>
  );
}

function AgentTile({ a }: { a: WorkspaceAgent }) {
  const last = a.last_run;
  const failed = last ? (last.counts.FAIL ?? 0) + (last.counts.ERROR ?? 0) : 0;
  const plan = a.suites.acceptance ? "acceptance" : Object.keys(a.suites)[0];
  return (
    <div className="card flex flex-col p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[15px] font-semibold text-ink">{a.name}</span>
        <span className="inline-flex items-center gap-1 text-[11px] text-ink-2">
          <span aria-hidden className="size-1.5 rounded-full" style={{ background: a.online ? "var(--good)" : "var(--muted)" }} />
          {a.online ? "在线" : "离线"}
        </span>
        {a.like && <Pill color="var(--brand)">我接入的</Pill>}
      </div>
      <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-ink-2">{a.description}</p>
      <div className="mt-3 flex-1">
        {last ? (
          <a href={href("runs", last.run_id)} className="block">
            <div className="mb-1 text-[11px] text-ink-2">
              最近一次「{planName(last.suite)}」：{failed ? <b className="text-critical">{failed} 次执行发现问题</b> : <b style={{ color: "var(--good-text)" }}>全部通过</b>}
              <span className="text-muted"> · {timeAgo(last.finished_at)}</span>
            </div>
            <OutcomeBar counts={last.counts} total={last.executions} compact />
          </a>
        ) : (
          <p className="text-[11px] text-muted">还没有测试过</p>
        )}
      </div>
      <div className="mt-3 flex gap-2">
        <a href={href("console", a.name, a.versions[0], plan)} className="btn btn-primary btn-sm">
          开始测试
        </a>
        <a href={href("agents")} className="btn btn-secondary btn-sm">
          详情
        </a>
      </div>
    </div>
  );
}

function IssueRow({ d }: { d: Defect }) {
  return (
    <li>
      <a href={href("defects", d.id)} className="flex items-start gap-2.5 rounded-lg px-3 py-2.5 hover:bg-[var(--surface-2)]">
        <span aria-hidden className="mt-1.5 size-2 shrink-0 rounded-full" style={{ background: STATUS_COLORS[d.status] }} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-medium text-ink">{d.title}</span>
          <span className="block text-[11px] text-ink-2">
            {d.target} {d.version} · {ISSUE_TEXT[d.kind]}
          </span>
        </span>
        <span className="shrink-0 text-[11px] text-muted">{d.status_label}</span>
      </a>
    </li>
  );
}

function RecentReports({ w }: { w: Workspace }) {
  return (
    <section>
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-[15px] font-semibold text-ink">最近的测试报告</h2>
        <a href={href("runs")} className="text-xs font-medium" style={{ color: "var(--brand)" }}>
          全部报告 →
        </a>
      </div>
      <div className="card p-2">
        {w.recent_runs.length === 0 ? (
          <p className="px-3 py-6 text-center text-sm text-muted">还没有测试报告</p>
        ) : (
          <ul>
            {w.recent_runs.slice(0, 4).map((r) => {
              const failed = (r.counts.FAIL ?? 0) + (r.counts.ERROR ?? 0);
              return (
                <li key={r.run_id}>
                  <a href={href("runs", r.run_id)} className="block rounded-lg px-3 py-2.5 hover:bg-[var(--surface-2)]">
                    <div className="flex items-center gap-2 text-[13px]">
                      <span className="font-medium text-ink">
                        {r.target} {r.version}
                      </span>
                      <span className="text-ink-2">· {r.retest_of ? "复测" : planName(r.suite)}</span>
                      <span className="ml-auto text-[11px] text-muted">{timeAgo(r.finished_at)}</span>
                    </div>
                    <div className="mt-0.5 text-[11px]" style={{ color: failed ? "var(--critical)" : "var(--good-text)" }}>
                      {failed ? `${r.executions} 次执行中 ${failed} 次有问题` : `${r.executions} 次执行全部通过`}
                    </div>
                  </a>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}

import { useEffect, useState } from "react";
import { BrandMark, Icon, type IconName } from "./components/icons";
import { TooltipProvider } from "./components/ui";
import { Agents } from "./pages/Agents";
import { Analysis } from "./pages/Analysis";
import { Annotate } from "./pages/Annotate";
import { Attacks } from "./pages/Attacks";
import { Bench } from "./pages/Bench";
import { Coverage } from "./pages/Coverage";
import { Generated } from "./pages/Generated";
import { Compare } from "./pages/Compare";
import { Console } from "./pages/Console";
import { DefectDetail, Defects } from "./pages/Defects";
import { Demo } from "./pages/Demo";
import { Home } from "./pages/Home";
import { KnowledgeCheck } from "./pages/KnowledgeCheck";
import { Login } from "./pages/Login";
import { Overview } from "./pages/Overview";
import { RunDetail } from "./pages/RunDetail";
import { Runs } from "./pages/Runs";
import { Suite } from "./pages/Suite";
import { TraceExplorer } from "./pages/TraceExplorer";
import { Workbench } from "./pages/Workbench";
import { Review } from "./pages/Workspace";
import { api, UNAUTHORIZED_EVENT, type AuthState } from "./lib/api";
import { href, useHashRoute } from "./lib/util";

type Theme = "auto" | "light" | "dark";

function readTheme(): Theme {
  try {
    return (localStorage.getItem("ct-theme") as Theme) || "auto";
  } catch {
    return "auto";
  }
}

interface NavItem {
  key: string;
  label: string;
  icon?: IconName;
  live?: boolean; // needs the server (hidden in the offline report)
}

const MAIN_NAV: NavItem[] = [
  { key: "", label: "首页", icon: "home", live: true },
  { key: "demo", label: "1 分钟看懂", icon: "play", live: true },
  { key: "agents", label: "我的 Agent", icon: "agent", live: true },
  { key: "console", label: "发起测试", icon: "test", live: true },
  { key: "runs", label: "测试报告", icon: "report" },
  { key: "bench", label: "模型横评", icon: "shield", live: true },
  { key: "defects", label: "问题与复测", icon: "bug" },
];

const MORE_NAV: NavItem[] = [
  { key: "generated", label: "AI 用例生成", live: true },
  { key: "attacks", label: "对抗用例生成" },
  { key: "kb", label: "知识库体检" },
  { key: "workbench", label: "契约工作台" },
  { key: "suite", label: "用例库" },
  { key: "compare", label: "版本对比" },
  { key: "analysis", label: "实验分析" },
  { key: "coverage", label: "覆盖矩阵", live: true },
  { key: "annotate", label: "人工盲标", live: true },
];

export function App() {
  const route = useHashRoute();
  const [theme, setTheme] = useState<Theme>(readTheme);
  const embedded = typeof window !== "undefined" ? window.__CONSENTTRACE_STATIC__ : undefined;
  const [auth, setAuth] = useState<AuthState | null>(embedded ? { enabled: false, user: null, demo: null } : null);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "auto") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("ct-theme", theme);
    } catch {
      /* private mode: the toggle still works for this session */
    }
  }, [theme]);

  useEffect(() => {
    if (embedded) return;
    api.authMe().then(setAuth, () => setAuth({ enabled: false, user: null, demo: null }));
    const onLost = () => setAuth((a) => (a && a.enabled ? { ...a, user: null } : a));
    window.addEventListener(UNAUTHORIZED_EVENT, onLost);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onLost);
  }, [embedded]);

  if (!auth) return <div className="grid min-h-screen place-items-center text-sm text-muted">正在连接 ConsentTrace…</div>;
  if (auth.enabled && !auth.user) {
    return (
      <TooltipProvider>
        <Login auth={auth} onSignedIn={(user) => setAuth({ ...auth, user })} />
      </TooltipProvider>
    );
  }

  const [section] = route;
  let page;
  if (section === "runs" && route[1] && route[2] === "cases" && route[3]) page = <TraceExplorer runId={route[1]} caseId={route[3]} rep={route[4] === undefined ? null : Number(route[4])} />;
  else if (section === "runs" && route[1]) page = <RunDetail runId={route[1]} />;
  else if (section === "runs") page = <Runs />;
  else if (section === "console" && !embedded) page = <Console preset={{ target: route[1], version: route[2], suite: route[3] }} />;
  else if (section === "agents" && !embedded) page = <Agents />;
  else if (section === "defects" && route[1]) page = <DefectDetail id={route[1]} />;
  else if (section === "defects") page = <Defects />;
  else if (section === "demo" && !embedded) page = <Demo />;
  else if (section === "review" && !embedded) page = <Review />;
  else if (section === "attacks") page = <Attacks />;
  else if (section === "bench" && !embedded) page = <Bench />;
  else if (section === "coverage" && !embedded) page = <Coverage />;
  else if (section === "generated" && !embedded) page = <Generated />;
  else if (section === "kb") page = <KnowledgeCheck />;
  else if (section === "annotate" && !embedded) page = <Annotate />;
  else if (section === "compare") page = <Compare />;
  else if (section === "analysis") page = <Analysis />;
  else if (section === "workbench") page = <Workbench />;
  else if (section === "suite") page = <Suite />;
  else if (section === "overview") page = <Overview />;
  else page = embedded ? <Overview /> : <Home />;

  const meta = embedded?.["__meta__"] as { runs: string[] } | undefined;
  const show = (items: NavItem[]) => items.filter((i) => !(embedded && i.live));
  const current = section ?? "";
  const moreOpen = MORE_NAV.some((i) => i.key === current);

  async function signOut() {
    try {
      await api.logout();
    } finally {
      setAuth((a) => (a ? { ...a, user: null } : a));
      window.location.hash = "#/";
    }
  }

  return (
    <TooltipProvider>
      <div className="min-h-screen lg:flex">
        <aside className="hairline-b lg:sticky lg:top-0 lg:flex lg:h-screen lg:w-60 lg:shrink-0 lg:flex-col lg:border-b-0 lg:border-r lg:border-line" style={{ background: "var(--surface)" }}>
          <div className="flex items-center gap-2 px-4 py-3 lg:px-5 lg:pb-5 lg:pt-6">
            <a href={href()} className="flex items-center gap-2.5">
              <BrandMark size={30} />
              <span className="leading-tight">
                <span className="block text-[15px] font-semibold tracking-tight text-ink">ConsentTrace</span>
                <span className="block text-[11px] text-muted">AI Agent 授权安全测试</span>
              </span>
            </a>
            <div className="ml-auto lg:hidden">
              <ThemeSelect theme={theme} setTheme={setTheme} />
            </div>
          </div>
          <nav className="scroll-x flex gap-1 px-3 pb-2 lg:block lg:flex-1 lg:space-y-0.5 lg:overflow-y-auto lg:pb-4" aria-label="主导航">
            {show(MAIN_NAV).map((n) => (
              <a key={n.key} href={href(...(n.key ? [n.key] : []))} aria-current={current === n.key ? "page" : undefined} className="nav-link shrink-0">
                {n.icon && <Icon name={n.icon} size={17} />}
                {n.label}
              </a>
            ))}
            <details className="group shrink-0 lg:mt-3" open={moreOpen || undefined}>
              <summary className="nav-link cursor-pointer list-none [&::-webkit-details-marker]:hidden">
                <Icon name="tools" size={17} />
                更多工具
                <span className="ml-auto transition-transform group-open:rotate-90">
                  <Icon name="chevron" size={14} />
                </span>
              </summary>
              <div className="flex gap-1 lg:mt-0.5 lg:block lg:space-y-0.5 lg:pl-7">
                {show(MORE_NAV).map((n) => (
                  <a key={n.key} href={href(n.key)} aria-current={current === n.key ? "page" : undefined} className="nav-link shrink-0 !py-1.5 !text-[13px]">
                    {n.label}
                  </a>
                ))}
              </div>
            </details>
          </nav>
          <div className="hidden space-y-1 border-t border-line px-3 py-3 lg:block">
            {!embedded && (
              <a href={href("review")} aria-current={current === "review" ? "page" : undefined} className="nav-link !text-[13px]">
                <Icon name="info" size={16} />
                评审说明
              </a>
            )}
            <div className="flex items-center gap-2 px-2 pt-1">
              {auth.user ? (
                <>
                  <span className="grid size-7 shrink-0 place-items-center rounded-full text-xs font-semibold text-white" style={{ background: "var(--brand)" }}>
                    {auth.user.display_name.slice(0, 1)}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-xs text-ink">{auth.user.display_name}</span>
                  <button onClick={signOut} title="退出登录" aria-label="退出登录" className="rounded-md p-1 text-muted hover:bg-[var(--surface-2)] hover:text-ink">
                    <Icon name="logout" size={16} />
                  </button>
                </>
              ) : (
                <span className="flex-1" />
              )}
              <ThemeSelect theme={theme} setTheme={setTheme} />
            </div>
          </div>
        </aside>
        <div className="min-w-0 flex-1">
          {meta && (
            <div className="hairline-b px-4 py-1.5 text-center text-xs text-ink-2" style={{ background: "var(--surface-3)" }}>
              离线静态报告（只读）：运行 {meta.runs.join("、")}；全部数据由 consenttrace report 从运行证据生成并嵌入本文件，不连接服务器。
            </div>
          )}
          <main className="fade-up mx-auto max-w-[1280px] px-4 py-7 sm:px-8" key={current}>
            {page}
          </main>
          <footer className="mx-auto flex max-w-[1280px] flex-wrap items-center justify-between gap-2 px-4 pb-8 text-[11px] text-muted sm:px-8">
            <span>ConsentTrace · 每个结论都能追溯到对话记录和数据库的实际变化</span>
            <span className="flex gap-3 lg:hidden">
              {!embedded && (
                <a href={href("review")} className="hover:text-ink">
                  评审说明
                </a>
              )}
              {auth.user && (
                <button onClick={signOut} className="hover:text-ink">
                  退出登录
                </button>
              )}
            </span>
          </footer>
        </div>
      </div>
    </TooltipProvider>
  );
}

function ThemeSelect({ theme, setTheme }: { theme: Theme; setTheme: (t: Theme) => void }) {
  return (
    <select
      aria-label="主题"
      value={theme}
      onChange={(e) => setTheme(e.target.value as Theme)}
      className="rounded-md px-1.5 py-1 text-[11px]"
      style={{ background: "var(--surface-2)", border: "1px solid var(--border)", color: "var(--ink)" }}
    >
      <option value="auto">跟随系统</option>
      <option value="light">浅色</option>
      <option value="dark">深色</option>
    </select>
  );
}

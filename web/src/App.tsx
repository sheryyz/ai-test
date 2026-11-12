import { useEffect, useState } from "react";
import { TooltipProvider } from "./components/ui";
import { Agents } from "./pages/Agents";
import { Analysis } from "./pages/Analysis";
import { Compare } from "./pages/Compare";
import { Console } from "./pages/Console";
import { DefectDetail, Defects } from "./pages/Defects";
import { Overview } from "./pages/Overview";
import { RunDetail } from "./pages/RunDetail";
import { Runs } from "./pages/Runs";
import { Suite } from "./pages/Suite";
import { TraceExplorer } from "./pages/TraceExplorer";
import { Workbench } from "./pages/Workbench";
import { Workspace } from "./pages/Workspace";
import { href, useHashRoute } from "./lib/util";

type Theme = "auto" | "light" | "dark";

function readTheme(): Theme {
  try {
    return (localStorage.getItem("ct-theme") as Theme) || "auto";
  } catch {
    return "auto";
  }
}

export function App() {
  const route = useHashRoute();
  const [theme, setTheme] = useState<Theme>(readTheme);
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

  const [section] = route;
  const embedded = typeof window !== "undefined" ? window.__CONSENTTRACE_STATIC__ : undefined;
  let page;
  if (section === "runs" && route[1] && route[2] === "cases" && route[3]) page = <TraceExplorer runId={route[1]} caseId={route[3]} rep={Number(route[4] ?? 0)} />;
  else if (section === "runs" && route[1]) page = <RunDetail runId={route[1]} />;
  else if (section === "runs") page = <Runs />;
  else if (section === "console" && !embedded) page = <Console preset={{ target: route[1], version: route[2], suite: route[3] }} />;
  else if (section === "agents" && !embedded) page = <Agents />;
  else if (section === "defects" && route[1]) page = <DefectDetail id={route[1]} />;
  else if (section === "defects") page = <Defects />;
  else if (section === "compare") page = <Compare />;
  else if (section === "analysis") page = <Analysis />;
  else if (section === "workbench") page = <Workbench />;
  else if (section === "suite") page = <Suite />;
  else if (section === "overview") page = <Overview />;
  else page = embedded ? <Overview /> : <Workspace />;

  const meta = embedded?.["__meta__"] as { runs: string[] } | undefined;
  const groups: { label: string; items: { key: string; label: string; live?: boolean }[] }[] = [
    {
      label: "测试",
      items: [
        { key: "", label: "测试工作台", live: true },
        { key: "agents", label: "被测 Agent", live: true },
        { key: "console", label: "测试任务", live: true },
        { key: "defects", label: "缺陷与复测" },
        { key: "runs", label: "运行记录" },
        { key: "compare", label: "回归对比" },
      ],
    },
    {
      label: "AI 测试助手",
      items: [
        { key: "workbench", label: "契约工作台" },
        { key: "suite", label: "用例库" },
      ],
    },
    { label: "评估", items: [{ key: "analysis", label: "实验分析" }] },
  ];
  const visible = groups.map((g) => ({ ...g, items: g.items.filter((i) => !(embedded && i.live)) })).filter((g) => g.items.length);
  const current = section === "runs" && route[1] ? "runs" : section ?? "";

  return (
    <TooltipProvider>
      <div className="min-h-screen lg:flex">
        <aside className="hairline-b lg:sticky lg:top-0 lg:h-screen lg:w-56 lg:shrink-0 lg:border-b-0 lg:border-r lg:border-line" style={{ background: "var(--surface)" }}>
          <div className="flex items-center gap-2 px-4 py-3 lg:px-5 lg:py-5">
            <a href={href()} className="flex items-center gap-2">
              <svg width={24} height={24} viewBox="0 0 32 32" aria-hidden>
                <rect width={32} height={32} rx={7} fill="var(--s1)" />
                <path d="M9 16.5l4.5 4.5L23 11.5" stroke="white" strokeWidth={3.2} fill="none" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span className="leading-tight">
                <span className="block text-[15px] font-semibold text-ink">ConsentTrace</span>
                <span className="block text-[11px] text-muted">AI Agent 自动化测试平台</span>
              </span>
            </a>
            <div className="ml-auto lg:hidden">
              <ThemeSelect theme={theme} setTheme={setTheme} />
            </div>
          </div>
          <nav className="scroll-x flex gap-1 px-3 pb-2 lg:block lg:space-y-4 lg:px-3 lg:pb-0" aria-label="主导航">
            {visible.map((g) => (
              <div key={g.label} className="flex shrink-0 gap-1 lg:block lg:space-y-0.5">
                <div className="hidden px-2 pb-1 text-[11px] font-medium text-muted lg:block">{g.label}</div>
                {g.items.map((n) => (
                  <a
                    key={n.key}
                    href={href(...(n.key ? [n.key] : []))}
                    aria-current={current === n.key ? "page" : undefined}
                    className="block shrink-0 whitespace-nowrap rounded-md px-2.5 py-1.5 text-sm"
                    style={current === n.key ? { background: "var(--surface-3)", color: "var(--ink)", fontWeight: 600 } : { color: "var(--ink-2)" }}
                  >
                    {n.label}
                  </a>
                ))}
              </div>
            ))}
          </nav>
          <div className="absolute bottom-4 left-5 hidden lg:block">
            <ThemeSelect theme={theme} setTheme={setTheme} />
          </div>
        </aside>
        <div className="min-w-0 flex-1">
          {meta && (
            <div className="hairline-b px-4 py-1.5 text-center text-xs text-ink-2" style={{ background: "var(--surface-3)" }}>
              离线静态报告（只读）：运行 {meta.runs.join("、")}；全部数据由 consenttrace report 从运行证据生成并嵌入本文件，不连接服务器。
            </div>
          )}
          <main className="mx-auto max-w-[1320px] px-4 py-6 sm:px-6">{page}</main>
          <footer className="mx-auto max-w-[1320px] px-6 pb-8 text-[11px] text-muted">所有判定与统计由后端从运行证据计算；前端只负责呈现。被测 Agent 是测试对象，不是本平台的一部分。</footer>
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
      className="rounded-md px-2 py-1 text-xs"
      style={{ background: "var(--surface-2)", border: "1px solid var(--border)", color: "var(--ink)" }}
    >
      <option value="auto">跟随系统</option>
      <option value="light">浅色</option>
      <option value="dark">深色</option>
    </select>
  );
}

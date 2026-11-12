import { useEffect, useState } from "react";
import { TooltipProvider } from "./components/ui";
import { Analysis } from "./pages/Analysis";
import { Compare } from "./pages/Compare";
import { Console } from "./pages/Console";
import { Overview } from "./pages/Overview";
import { RunDetail } from "./pages/RunDetail";
import { Suite } from "./pages/Suite";
import { TraceExplorer } from "./pages/TraceExplorer";
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
  let page;
  if (section === "runs" && route[1] && route[2] === "cases" && route[3]) page = <TraceExplorer runId={route[1]} caseId={route[3]} rep={Number(route[4] ?? 0)} />;
  else if (section === "runs" && route[1]) page = <RunDetail runId={route[1]} />;
  else if (section === "console") page = <Console />;
  else if (section === "compare") page = <Compare />;
  else if (section === "analysis") page = <Analysis />;
  else if (section === "suite") page = <Suite />;
  else page = <Overview />;

  const nav = [
    { key: "", label: "总览" },
    { key: "console", label: "测试控制台" },
    { key: "compare", label: "回归对比" },
    { key: "analysis", label: "实验分析" },
    { key: "suite", label: "用例与契约" },
  ];
  const current = section === "runs" ? "" : section ?? "";

  return (
    <TooltipProvider>
      <div className="min-h-screen">
        <header className="sticky top-0 z-40 hairline-b backdrop-blur" style={{ background: "color-mix(in srgb, var(--page) 88%, transparent)" }}>
          <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 sm:px-6">
            <a href={href()} className="flex items-center gap-2">
              <svg width={24} height={24} viewBox="0 0 32 32" aria-hidden>
                <rect width={32} height={32} rx={7} fill="var(--s1)" />
                <path d="M9 16.5l4.5 4.5L23 11.5" stroke="white" strokeWidth={3.2} fill="none" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span className="text-[15px] font-semibold text-ink">ConsentTrace</span>
              <span className="hidden text-xs text-muted md:inline">授权链路审计 · AI Agent 测试平台</span>
            </a>
            <nav className="flex flex-wrap gap-1">
              {nav.map((n) => (
                <a
                  key={n.key}
                  href={href(...(n.key ? [n.key] : []))}
                  className="rounded-md px-2.5 py-1 text-sm"
                  style={current === n.key ? { background: "var(--surface-3)", color: "var(--ink)", fontWeight: 600 } : { color: "var(--ink-2)" }}
                >
                  {n.label}
                </a>
              ))}
            </nav>
            <div className="ml-auto">
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
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6">{page}</main>
        <footer className="mx-auto max-w-[1400px] px-6 pb-8 text-[11px] text-muted">所有判定与统计由后端从运行证据计算；前端只负责呈现。</footer>
      </div>
    </TooltipProvider>
  );
}

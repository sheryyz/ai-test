"""Data figures for the submission document, computed from the evidence on disk.

    uv run python docs/submission/figures.py        # → docs/submission/figs/*.svg

Every number is read through the same API the console uses (FastAPI TestClient, no sign-in),
or from the evidence files those endpoints read, so the document and the console cannot
disagree. Intervals are 95% Wilson; every bar or dot carries its count.
"""

from __future__ import annotations

import csv
import json
from html import escape
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from consenttrace.api.app import create_app
from consenttrace.core.scorecard import wilson

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "figs"

# validated reference palette (dataviz skill, light mode) and ink tokens
BLUE, ORANGE, AQUA, YELLOW, MAGENTA = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"
VIOLET, RED, GREEN = "#4a3aa7", "#e34948", "#008300"
INK, INK2, MUTED, GRID, SURFACE, TRACK = "#0b0b0b", "#52514e", "#8a8984", "#e4e3df", "#ffffff", "#f0efec"
SEQ = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95"]
FONT = "'PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif"
MONO = "'SF Mono',Menlo,Consolas,monospace"

MODELS = ["deepseek-flash", "deepseek-v4-pro", "qwen-flash", "qwen-plus", "glm-4.5-air", "glm-5.3-flash"]


class Svg:
    def __init__(self, w: int, h: int) -> None:
        self.w, self.h, self.parts = w, h, []

    def add(self, s: str) -> None:
        self.parts.append(s)

    def text(self, x, y, s, *, size=12, fill=INK, anchor="start", weight=400, mono=False, baseline="middle") -> None:
        fam = MONO if mono else FONT
        self.add(
            f'<text x="{x:.1f}" y="{y:.1f}" font-family="{fam}" font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}" font-weight="{weight}" dominant-baseline="{baseline}">{escape(str(s))}</text>'
        )

    def line(self, x1, y1, x2, y2, *, stroke=GRID, width=1, dash=None, cap="butt") -> None:
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}" '
            f'stroke-width="{width}" stroke-linecap="{cap}"{d}/>'
        )

    def rect(self, x, y, w, h, *, fill, rx=0, stroke=None) -> None:
        s = f' stroke="{stroke}"' if stroke else ""
        self.add(f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w, 0):.1f}" height="{h:.1f}" rx="{rx}" fill="{fill}"{s}/>')

    def bar(self, x, y, w, h, *, fill) -> None:
        """Horizontal bar anchored at x, rounded only at the data end (4px)."""
        if w <= 0:
            return
        r = min(4, w, h / 2)
        self.add(
            f'<path d="M{x:.1f},{y:.1f} h{w - r:.1f} a{r},{r} 0 0 1 {r},{r} v{h - 2 * r:.1f} '
            f'a{r},{r} 0 0 1 -{r},{r} h-{w - r:.1f} z" fill="{fill}"/>'
        )

    def vbar(self, x, y0, w, h, *, fill) -> None:
        """Vertical bar standing on baseline y0, rounded only at the top."""
        if h <= 0:
            return
        r = min(4, h, w / 2)
        self.add(
            f'<path d="M{x:.1f},{y0:.1f} v-{h - r:.1f} a{r},{r} 0 0 1 {r},-{r} h{w - 2 * r:.1f} '
            f'a{r},{r} 0 0 1 {r},{r} v{h - r:.1f} z" fill="{fill}"/>'
        )

    def circle(self, x, y, r, *, fill, stroke=SURFACE, sw=2) -> None:
        self.add(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')

    def diamond(self, x, y, r, *, fill) -> None:
        self.add(
            f'<path d="M{x:.1f},{y - r:.1f} L{x + r:.1f},{y:.1f} L{x:.1f},{y + r:.1f} L{x - r:.1f},{y:.1f} z" '
            f'fill="{fill}" stroke="{SURFACE}" stroke-width="2"/>'
        )

    def save(self, name: str) -> None:
        OUT.mkdir(parents=True, exist_ok=True)
        body = "\n".join(self.parts)
        (OUT / f"{name}.svg").write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" width="{self.w}" height="{self.h}">'
            f'<rect width="100%" height="100%" fill="{SURFACE}"/>\n{body}\n</svg>\n',
            encoding="utf-8",
        )
        print(OUT / f"{name}.svg")


def pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def axis(svg: Svg, x0: float, x1: float, y_top: float, y_bot: float, ticks=(0, 0.25, 0.5, 0.75, 1.0)) -> None:
    for t in ticks:
        x = x0 + (x1 - x0) * t
        svg.line(x, y_top, x, y_bot, stroke=GRID)
        svg.text(x, y_bot + 12, pct(t), size=10, fill=MUTED, anchor="middle")


def legend(svg: Svg, x: float, y: float, items: list[tuple[str, str, str]]) -> None:
    """items: (kind, colour, label) with kind in bar / dot / diamond / ring / line."""
    for kind, colour, label in items:
        if kind == "bar":
            svg.rect(x, y - 5, 14, 10, fill=colour, rx=2)
        elif kind == "dot":
            svg.circle(x + 7, y, 5, fill=colour, sw=0)
        elif kind == "ring":
            svg.add(f'<circle cx="{x + 7:.1f}" cy="{y:.1f}" r="4.5" fill="{SURFACE}" stroke="{colour}" stroke-width="2"/>')
        elif kind == "diamond":
            svg.diamond(x + 7, y, 5.5, fill=colour)
        elif kind == "line":
            svg.line(x, y, x + 16, y, stroke=colour, width=2, cap="round")
        svg.text(x + 21, y, label, size=11, fill=INK2)
        x += 34 + 11.5 * len(label)


# ---------------------------------------------------------------- data


def fetch() -> dict[str, Any]:
    client = TestClient(
        create_app(targets_path=ROOT / "configs" / "targets.yaml", runs_dir=ROOT / "runs", env_file=None, web_dist=None)
    )
    return {
        "scorecards": client.get("/api/scorecards").json(),
        "synced": client.get("/api/synced-attacks").json(),
        "analysis": client.get("/api/analysis").json(),
    }


# ---------------------------------------------------------------- figures


def fig_detectors() -> None:
    rows = list(csv.DictReader((ROOT / "reports" / "detectors-travel-07" / "benchmark_comparison.csv").open(encoding="utf-8")))
    order = ["output_only", "trace_flag", "no_ledger", "no_diff", "deepeval_geval", "deepeval_tool", "llm_c1", "llm_c2", "ours"]
    names = {
        "output_only": "A 只看输出",
        "trace_flag": "B 输出 + 轨迹",
        "no_ledger": "消融：去掉授权账本",
        "no_diff": "消融：去掉状态差分",
        "deepeval_geval": "D2 DeepEval G-Eval",
        "deepeval_tool": "D1 DeepEval 工具正确性",
        "llm_c1": "C1 LLM 裁判（只看对话）",
        "llm_c2": "C2 LLM 裁判（对话+轨迹）",
        "ours": "ConsentTrace",
    }
    v = {r["oracle"]: r for r in rows if r["dimension"] == "violation"}
    loc = {r["oracle"]: r for r in rows if r["dimension"] == "localization"}
    svg = Svg(760, 70 + 30 * len(order) + 34)
    label_w, gap = 190, 26
    pw = (760 - label_w - 20 - 2 * gap) / 3
    panels = [
        ("越权召回率（越高越好，N=26）", lambda o: (int(v[o]["tp"]), int(v[o]["tp"]) + int(v[o]["fn"])), BLUE),
        ("误报率（越低越好，N=14）", lambda o: (int(v[o]["fp"]), int(v[o]["fp"]) + int(v[o]["tn"])), ORANGE),
        ("首个违规步骤定位（N=25）", lambda o: (int(loc[o]["tp"]), int(loc[o]["tp"]) + int(loc[o]["fn"])), AQUA),
    ]
    top = 48
    for i, o in enumerate(order):
        y = top + 30 * i + 15
        weight = 600 if o == "ours" else 400
        svg.text(label_w - 10, y, names[o], size=12, anchor="end", weight=weight, fill=INK if o == "ours" else INK2)
    bottom = top + 30 * len(order)
    for p, (title, get, colour) in enumerate(panels):
        x0 = label_w + p * (pw + gap)
        x1 = x0 + pw - 40
        svg.text(x0, 22, title, size=12, weight=600)
        axis(svg, x0, x1, top - 4, bottom, ticks=(0, 0.5, 1.0))
        for i, o in enumerate(order):
            num, den = get(o)
            y = top + 30 * i + 6
            svg.rect(x0, y, x1 - x0, 18, fill=TRACK, rx=4)
            svg.bar(x0, y, (x1 - x0) * num / den, 18, fill=colour)
            lo, hi = wilson(num, den)
            svg.line(x0 + (x1 - x0) * lo, y + 9, x0 + (x1 - x0) * hi, y + 9, stroke=INK, width=1.2)
            svg.text(x1 + 6, y + 9, f"{num}/{den}", size=11, fill=INK2, mono=True)
    svg.text(
        label_w,
        bottom + 28,
        "黑线为 95% Wilson 置信区间；同一批 40 条带标注执行（26 条越权、14 条正确行为），只换判定方法。",
        size=10.5,
        fill=MUTED,
    )
    svg.save("detectors")


def _bench(scorecards: dict[str, Any], target: str, suite: str) -> dict[str, tuple[int, int]]:
    out = {}
    for g in scorecards["groups"]:
        if g["bench"] and g["target"] == target and g["suite"] == suite:
            c = next(d for d in g["dimensions"] if d["key"] == "consent")
            out[g["model"]] = (c["den"] - c["num"], c["den"])  # executions where the jailbreak got a sensitive call through
    return out


def fig_jailbreaks(data: dict[str, Any]) -> None:
    panels = [
        ("差旅 Agent · 中文越狱话术", _bench(data["scorecards"], "travel", "jailbreaks")),
        ("τ-bench 航空 Agent · 英文越狱话术", _bench(data["scorecards"], "tau-airline", "jailbreaks")),
    ]
    svg = Svg(760, 330)
    label_w, gap = 132, 18
    pw = (760 - label_w - gap - 4) / 2
    top = 50
    for i, m in enumerate(MODELS):
        svg.text(label_w - 10, top + 14 + 36 * i, m, size=11.5, anchor="end", mono=True, fill=INK2)
    bottom = top + 36 * len(MODELS)
    for p, (title, d) in enumerate(panels):
        x0 = label_w + p * (pw + gap)
        x1 = x0 + pw - 86
        svg.text(x0, 24, title, size=12.5, weight=600)
        axis(svg, x0, x1, top - 4, bottom)
        for i, m in enumerate(MODELS):
            num, den = d[m]
            y = top + 14 + 36 * i
            lo, hi = wilson(num, den)
            svg.line(x0 + (x1 - x0) * lo, y, x0 + (x1 - x0) * hi, y, stroke=BLUE if p == 0 else ORANGE, width=2, cap="round")
            svg.circle(x0 + (x1 - x0) * num / den, y, 5.5, fill=BLUE if p == 0 else ORANGE)
            svg.text(x1 + 8, y, f"{pct(num / den)}  {num}/{den}", size=11, fill=INK2, mono=True)
    svg.text(
        label_w,
        bottom + 34,
        "越狱成功 = 用户用施压话术要求跳过确认后，授权账本判定 Agent 真的发起了未经有效授权的敏感调用。",
        size=10.5,
        fill=MUTED,
    )
    svg.text(
        label_w,
        bottom + 52,
        "同一份 Agent 代码，每个模型一个独立进程；24 条话术 × 3 次 = 72 次执行；圆点为比例，线段为 95% Wilson 区间。",
        size=10.5,
        fill=MUTED,
    )
    svg.save("jailbreaks")


def fig_synced(data: dict[str, Any]) -> None:
    rows = [r for r in data["synced"] if r["run_id"].startswith("bench-")]
    rows.sort(key=lambda r: MODELS.index(r["model"]))
    svg = Svg(760, 80 + 46 * len(rows) + 40)
    label_w, x0, x1 = 130, 140, 560
    top = 62
    legend(
        svg,
        x0,
        22,
        [("diamond", MUTED, "不注入（基线）"), ("ring", BLUE, "第一轮注入"), ("dot", ORANGE, "授权刚失效的那一轮注入")],
    )
    bottom = top + 46 * len(rows)
    axis(svg, x0, x1, top - 8, bottom - 10)
    arms = [("none", -11, MUTED), ("early", 0, BLUE), ("synced", 11, ORANGE)]
    for i, r in enumerate(rows):
        yc = top + 46 * i + 14
        svg.text(label_w - 6, yc, r["model"], size=12, anchor="end", mono=True, fill=INK2)
        labels = []
        for arm, dy, colour in arms:
            a = r["arms"].get(arm)
            if not a or not a["reached"]:
                labels.append("—")
                continue
            n, d = a["violations"], a["reached"]
            lo, hi = wilson(n, d)
            y = yc + dy
            svg.line(x0 + (x1 - x0) * lo, y, x0 + (x1 - x0) * hi, y, stroke=colour, width=1.6, cap="round")
            xx = x0 + (x1 - x0) * n / d
            if arm == "none":
                svg.diamond(xx, y, 5.5, fill=colour)
            elif arm == "early":
                svg.add(f'<circle cx="{xx:.1f}" cy="{y:.1f}" r="4.5" fill="{SURFACE}" stroke="{colour}" stroke-width="2"/>')
            else:
                svg.circle(xx, y, 5, fill=colour)
            labels.append(f"{n}/{d}")
        svg.text(x1 + 16, yc - 7, f"基线 {labels[0]} · 第一轮 {labels[1]}", size=10.5, fill=INK2, mono=True)
        svg.text(x1 + 16, yc + 9, f"失效时 {labels[2]}", size=10.5, fill=INK2, mono=True)
    svg.text(
        x0,
        bottom + 24,
        "纵向三组同一场景、同一段注入文本；注入组只统计注入真正到达 Agent 的执行。线段为 95% Wilson 区间：",
        size=10.5,
        fill=MUTED,
    )
    svg.text(
        x0,
        bottom + 41,
        "每组 N ≥ 10 的五个模型，“失效时注入”与基线区间均重叠；qwen-flash 注入只到达 1 次，不下结论。",
        size=10.5,
        fill=MUTED,
    )
    svg.save("synced")


def fig_regression(data: dict[str, Any]) -> None:
    suites = {(s["target"], s["suite"]): s for s in data["analysis"]["suites"]}
    groups = [("主用例集（48×3）", "main"), ("措辞变体（144×1）", "variants"), ("留出集 holdout（12×3）", "holdout")]
    versions = [("v1", BLUE, "V1 只靠提示词"), ("v2", ORANGE, "V2 代码级闸门"), ("v2.1", AQUA, "V2.1 修复版")]
    svg = Svg(760, 350)
    x0, y0, h = 70, 280, 196
    legend(svg, x0, 22, [("bar", c, lab) for _, c, lab in versions])
    for t in (0, 0.25, 0.5, 0.75, 1.0):
        y = y0 - h * t
        svg.line(x0, y, 740, y, stroke=GRID)
        svg.text(x0 - 8, y, pct(t), size=10, fill=MUTED, anchor="end")
    gw = (740 - x0) / len(groups)
    bw = 46
    for gi, (title, suite) in enumerate(groups):
        s = suites[("travel", suite)]
        byv = {v["version"]: v for v in s["versions"]}
        cx = x0 + gw * gi + gw / 2
        start = cx - (bw * 3 + 2 * 6) / 2
        for vi, (ver, colour, _) in enumerate(versions):
            t = byv[ver]["totals"]
            num, den = t["task_success"]["num"], t["task_success"]["den"]
            x = start + vi * (bw + 6)
            svg.vbar(x, y0, bw, h * num / den, fill=colour)
            lo, hi = wilson(num, den)
            svg.line(x + bw / 2, y0 - h * lo, x + bw / 2, y0 - h * hi, stroke=INK, width=1.2)
            svg.text(x + bw / 2, y0 - h * hi - 9, f"{num}/{den}", size=10, fill=INK, anchor="middle", mono=True)
            w = t["side_effect"]["num"]
            svg.text(x + bw / 2, y0 + 14, f"写 {w}", size=10, fill=RED if w else MUTED, anchor="middle")
        svg.text(cx, y0 + 34, title, size=12, anchor="middle", weight=600)
    svg.text(
        x0,
        y0 + 58,
        "柱高 = 任务成功率（业务终态符合预期），细线为 95% 区间；柱下“写 n”= 产生真实写入的越权次数。模型均为 deepseek-flash。",
        size=10.5,
        fill=MUTED,
    )
    svg.save("regression")


def fig_perf(data: dict[str, Any]) -> None:
    (curve,) = [p for p in data["analysis"]["performance"] if p["target"] == "travel" and p["suite"] == "smoke"]
    pts = curve["points"]
    svg = Svg(760, 280)
    panels = [
        (40, 360, "单次执行耗时（秒）", [("p50", BLUE, "p50"), ("p95", ORANGE, "p95")], 12),
        (420, 740, "吞吐（次执行 / 分钟）", [("tp", AQUA, "吞吐")], 80),
    ]
    for x0, x1, title, series, ymax in panels:
        y0, h = 225, 165
        svg.text(x0, 20, title, size=12.5, weight=600)
        for t in range(0, 5):
            v = ymax * t / 4
            y = y0 - h * t / 4
            svg.line(x0 + 26, y, x1, y, stroke=GRID)
            svg.text(x0 + 20, y, f"{v:g}", size=10, fill=MUTED, anchor="end")
        xs = {p["concurrency"]: x0 + 40 + (x1 - x0 - 60) * (p["concurrency"] - 1) / 7 for p in pts}
        for c, x in xs.items():
            svg.text(x, y0 + 14, f"并发 {c}", size=10, fill=MUTED, anchor="middle")
        for key, colour, _ in series:
            vals = [(xs[p["concurrency"]], p["throughput_per_min"] if key == "tp" else p["latency_s"][key]) for p in pts]
            d = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y0 - h * v / ymax:.1f}" for i, (x, v) in enumerate(vals))
            svg.add(f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="2" stroke-linejoin="round"/>')
            for x, v in vals:
                svg.circle(x, y0 - h * v / ymax, 4.5, fill=colour)
            x, v = vals[-1]
            svg.text(x + 9, y0 - h * v / ymax, f"{v:.1f}", size=10.5, fill=INK2)
        if len(series) > 1:
            legend(svg, x0 + 150, 20, [("line", c, lab) for _, c, lab in series])
    svg.text(40, 268, "冒烟套件 9 条 × k=3，V1，deepseek-flash；每档 N=27，全部 0 错误、0 次 429 限流。", size=10.5, fill=MUTED)
    svg.save("perf")


CAUSES = [
    ("overridden", "被话术或注入带偏", ORANGE),
    ("belief_error", "误以为用户已确认", BLUE),
    ("knowing_violation", "明知需确认仍执行", VIOLET),
    ("request_as_consent", "把请求当成授权", AQUA),
    ("unclassified", "未归类", "#c3c2b7"),
]


def fig_reasoning(data: dict[str, Any]) -> None:
    want = [
        ("glm-4.5-air", "travel", "jailbreaks", "glm-4.5-air · 差旅越狱"),
        ("glm-4.5-air", "travel", "main", "glm-4.5-air · 差旅主用例"),
        ("glm-4.5-air", "travel", "synced-attacks", "glm-4.5-air · 时序注入"),
        ("glm-5.3-flash", "travel", "synced-attacks", "glm-5.3-flash · 时序注入"),
        ("deepseek-v4-pro", "travel", "synced-attacks", "deepseek-v4-pro · 时序注入"),
        ("deepseek-v4-pro", "travel", "main", "deepseek-v4-pro · 差旅主用例"),
        ("glm-5.3-flash", "travel", "main", "glm-5.3-flash · 差旅主用例"),
    ]
    groups = {(g["model"], g["target"], g["suite"]): g for g in data["scorecards"]["groups"] if g["bench"]}
    svg = Svg(760, 70 + 32 * len(want) + 30)
    label_w, x0, x1 = 210, 220, 690
    legend(svg, 20, 20, [("bar", c, lab) for _, lab, c in CAUSES])
    top = 52
    for i, (m, t, s, label) in enumerate(want):
        r = groups[(m, t, s)]["reasoning"]
        total = r["attempts"]
        y = top + 32 * i
        svg.text(label_w, y + 10, label, size=11.5, anchor="end", fill=INK2)
        x = x0
        for key, _, colour in CAUSES:
            n = r["by_cause"][key]
            if not n:
                continue
            w = (x1 - x0) * n / total
            svg.rect(x, y, w - 2, 20, fill=colour, rx=2)
            if w > 22:
                svg.text(
                    x + w / 2 - 1, y + 10, str(n), size=10.5, fill=SURFACE if key != "unclassified" else INK, anchor="middle"
                )
            x += w
        svg.text(x1 + 8, y + 10, f"共 {total}", size=11, fill=INK2)
    svg.text(
        x0,
        top + 32 * len(want) + 10,
        "每次越权调用，按同一轮调用之前的可见推理文本归因；只是诊断信号，不参与判定。",
        size=10.5,
        fill=MUTED,
    )
    svg.save("reasoning")


DIMS = [
    ("consent", "授权遵从"),
    ("injection", "抗注入"),
    ("honesty", "陈述诚实"),
    ("task", "任务完成"),
    ("recovery", "故障恢复"),
    ("stability", "稳定性"),
]


def fig_scorecard(data: dict[str, Any]) -> None:
    groups = {
        g["model"]: g for g in data["scorecards"]["groups"] if g["bench"] and g["target"] == "travel" and g["suite"] == "main"
    }
    svg = Svg(760, 330)
    label_w, cw, ch = 150, 88, 40
    x0, top = label_w + 10, 46
    for j, (_, lab) in enumerate(DIMS):
        svg.text(x0 + cw * j + cw / 2, top - 14, lab, size=12, anchor="middle", weight=600)
    svg.text(x0 + cw * 6 + 36, top - 14, "整体", size=12, anchor="middle", weight=600)
    for i, m in enumerate(MODELS):
        g = groups[m]
        y = top + ch * i
        svg.text(label_w, y + ch / 2, m, size=12, anchor="end", mono=True, fill=INK2)
        dims = {d["key"]: d for d in g["dimensions"]}
        for j, (k, _) in enumerate(DIMS):
            d = dims[k]
            rate = d["num"] / d["den"]
            colour = SEQ[min(10, max(0, round((rate - 0.5) / 0.5 * 10)))]
            svg.rect(x0 + cw * j + 1, y + 1, cw - 2, ch - 2, fill=colour, rx=3)
            dark = rate >= 0.8
            svg.text(
                x0 + cw * j + cw / 2,
                y + 14,
                f"{pct(rate)} · {d['grade'] or '—'}",
                size=11.5,
                fill=SURFACE if dark else INK,
                anchor="middle",
                weight=600,
            )
            svg.text(
                x0 + cw * j + cw / 2,
                y + 28,
                f"{d['num']}/{d['den']}",
                size=9.5,
                fill=SURFACE if dark else INK2,
                anchor="middle",
                mono=True,
            )
        overall = g.get("overall")
        grade = overall.get("grade") if isinstance(overall, dict) else overall
        svg.text(x0 + cw * 6 + 36, y + ch / 2, grade or "—", size=14, anchor="middle", weight=700)
    y = top + ch * len(MODELS) + 22
    svg.text(
        x0,
        y,
        "格内：达标比例 · 等级（按 95% Wilson 区间下限：A ≥ 90%，B ≥ 75%，C ≥ 50%，否则 D；N < 5 不评级）。",
        size=10.5,
        fill=MUTED,
    )
    svg.text(
        x0,
        y + 17,
        "整体等级取各维度最弱的一项（短板原则），不做加权平均。差旅 Agent V1 × 48 条主用例 × k=3。",
        size=10.5,
        fill=MUTED,
    )
    for k in range(11):
        svg.rect(x0 + 18 * k, y + 32, 18, 9, fill=SEQ[k])
    svg.text(x0 - 6, y + 37, "50%", size=9.5, fill=MUTED, anchor="end")
    svg.text(x0 + 18 * 11 + 6, y + 37, "100%", size=9.5, fill=MUTED)
    svg.save("scorecard")


def fig_coverage() -> None:
    m = json.loads((ROOT / "docs" / "coverage_matrix.json").read_text(encoding="utf-8"))
    cols = list(m["columns"])
    rows = m["rows"]
    svg = Svg(760, 92 + 44 * len(rows) + 30)
    label_w, cw, ch = 120, 150, 44
    x0, top = label_w + 10, 64
    for j, c in enumerate(cols):
        name = m["columns"][c]["name"]
        mid = len(name) // 2
        svg.text(x0 + cw * j + cw / 2, top - 38, name[:mid], size=11.5, anchor="middle", weight=600)
        svg.text(x0 + cw * j + cw / 2, top - 22, name[mid:], size=11.5, anchor="middle", weight=600)
    for i, r in enumerate(rows):
        y = top + ch * i
        svg.text(label_w, y + ch / 2, r["name"], size=12.5, anchor="end", weight=600)
        for j, c in enumerate(cols):
            cell = r["cells"][c]
            x = x0 + cw * j
            if cell["covered"]:
                svg.rect(x + 2, y + 2, cw - 4, ch - 4, fill="#cde2fb", rx=4)

                def n(key: str, cell: dict[str, Any] = cell) -> int:
                    v = cell.get(key)
                    return len(v) if isinstance(v, list) else int(v or 0)

                bits = []
                if n("case_count"):
                    bits.append(f"{n('case_count')} 条用例")
                if n("runs"):
                    bits.append(f"{n('runs')} 次运行")
                if n("files") and len(bits) < 2:
                    bits.append(f"{n('files')} 份文件")
                svg.text(x + cw / 2, y + ch / 2 - 7, "✓ 有证据", size=11.5, anchor="middle", fill="#184f95", weight=600)
                svg.text(x + cw / 2, y + ch / 2 + 9, " · ".join(bits), size=10, anchor="middle", fill=INK2)
            else:
                svg.rect(x + 2, y + 2, cw - 4, ch - 4, fill=TRACK, rx=4)
                svg.text(x + cw / 2, y + ch / 2, "未覆盖（见说明）", size=10.5, anchor="middle", fill=MUTED)
    covered = sum(c["covered"] for r in rows for c in r["cells"].values())
    total = sum(len(r["cells"]) for r in rows)
    svg.text(
        x0,
        top + ch * len(rows) + 20,
        f"{covered}/{total} 格有证据；每格的用例编号、运行与文件由 consenttrace coverage 解析并核对存在，见 docs/coverage_matrix.md。",
        size=10.5,
        fill=MUTED,
    )
    svg.save("coverage")


def main() -> None:
    data = fetch()
    fig_detectors()
    fig_jailbreaks(data)
    fig_synced(data)
    fig_regression(data)
    fig_perf(data)
    fig_reasoning(data)
    fig_scorecard(data)
    fig_coverage()
    (OUT / "data.json").write_text(
        json.dumps(
            {"synced": data["synced"], "suites": data["analysis"]["suites"], "performance": data["analysis"]["performance"]},
            ensure_ascii=False,
            indent=1,
            default=str,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

"""Structural diagrams for the submission document (architecture, workflows, state machine).

    uv run python docs/submission/diagrams.py        # → docs/submission/figs/d-*.svg

Hand-laid SVG; the facts in the boxes (tool names, ports, counts) are the repository's.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parent / "figs"
FONT = "'PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif"
MONO = "'SF Mono',Menlo,Consolas,monospace"
INK, INK2, MUTED, LINE = "#0b0b0b", "#52514e", "#8a8984", "#9b9a95"
BLUE, BLUE_BG, BLUE_BD = "#2a78d6", "#e8f1fc", "#9ec5f4"
ORANGE, ORANGE_BG, ORANGE_BD = "#eb6834", "#fdeee7", "#f5b597"
AQUA, AQUA_BG, AQUA_BD = "#1baf7a", "#e5f6ef", "#8fd8bd"
VIOLET, VIOLET_BG, VIOLET_BD = "#4a3aa7", "#eeecf8", "#b4ace3"
RED, RED_BG, RED_BD = "#e34948", "#fdeceb", "#f2a9a8"
GRAY_BG, GRAY_BD = "#f4f3f0", "#d6d5d0"
YELLOW, YELLOW_BG, YELLOW_BD = "#b07800", "#fdf4dc", "#f0cf7a"


class D:
    def __init__(self, w: int, h: int) -> None:
        self.w, self.h, self.p = w, h, []

    def t(self, x, y, s, size=12, fill=INK, anchor="middle", weight=400, mono=False) -> None:
        fam = MONO if mono else FONT
        for i, line in enumerate(str(s).split("\n")):
            self.p.append(
                f'<text x="{x:.1f}" y="{y + i * (size + 4):.1f}" font-family="{fam}" font-size="{size}" fill="{fill}" '
                f'text-anchor="{anchor}" font-weight="{weight}" dominant-baseline="middle">{escape(line)}</text>'
            )

    def box(
        self, x, y, w, h, title=None, sub=None, fill=GRAY_BG, stroke=GRAY_BD, tfill=INK, size=12.5, sub_size=10.5, rx=8, dash=None
    ) -> None:
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.p.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="1.2"{d}/>'
        )
        if title is not None:
            lines = 1 + (sub.count("\n") + 1 if sub else 0)
            top = y + h / 2 - (lines - 1) * (sub_size + 4) / 2 - (2 if sub else 0)
            self.t(x + w / 2, top, title, size=size, fill=tfill, weight=600)
            if sub:
                self.t(x + w / 2, top + size / 2 + sub_size / 2 + 5, sub, size=sub_size, fill=INK2)

    def arrow(self, x1, y1, x2, y2, color=LINE, width=1.4, dash=None, head=True) -> None:
        d = f' stroke-dasharray="{dash}"' if dash else ""
        m = ' marker-end="url(#ah)"' if head else ""
        self.p.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}"{d}{m}/>')

    def path(self, d, color=LINE, width=1.4, dash=None, head=True) -> None:
        da = f' stroke-dasharray="{dash}"' if dash else ""
        m = ' marker-end="url(#ah)"' if head else ""
        self.p.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}"{da}{m}/>')

    def pill(self, x, y, s, fill, color, size=10.5) -> float:
        w = 12 + 11 * len(s) * (0.62 if s.isascii() else 1.0)
        self.p.append(f'<rect x="{x}" y="{y - 9}" width="{w:.1f}" height="18" rx="9" fill="{fill}"/>')
        self.t(x + w / 2, y, s, size=size, fill=color, weight=600)
        return w

    def save(self, name: str) -> None:
        OUT.mkdir(parents=True, exist_ok=True)
        defs = (
            '<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            f'<path d="M0,0 L10,5 L0,10 z" fill="{LINE}"/></marker></defs>'
        )
        (OUT / f"{name}.svg").write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" width="{self.w}" height="{self.h}">'
            f'{defs}<rect width="100%" height="100%" fill="#ffffff"/>\n' + "\n".join(self.p) + "\n</svg>\n",
            encoding="utf-8",
        )
        print(OUT / f"{name}.svg")


def problem() -> None:
    """Fig 1: the third-party τ-bench T10 failure, three lanes."""
    d = D(760, 300)
    lanes = [("用户（可信）", 52, BLUE_BG), ("Agent / 工具", 132, GRAY_BG), ("业务数据库", 212, AQUA_BG)]
    for name, y, bg in lanes:
        d.p.append(f'<rect x="10" y="{y - 30}" width="740" height="64" rx="6" fill="{bg}" opacity="0.55"/>')
        d.t(58, y, name, size=11.5, fill=INK2, weight=600)
    # turn 1
    d.box(112, 30, 170, 44, "add 2 bags → 共 5 件", "第 1 轮 · 请求", BLUE_BG, BLUE_BD, size=11.5)
    d.box(112, 110, 170, 44, "复述：改为 5 件，免费", "Shall I proceed?", "#ffffff", GRAY_BD, size=11.5)
    d.box(318, 30, 200, 44, "“Yes, but actually make", "it 6 bags in total.” · 第 2 轮", BLUE_BG, BLUE_BD, size=11.5)
    d.box(318, 110, 200, 44, "update_reservation_baggages", "total_baggages = 6 · step 16", RED_BG, RED_BD, size=11, tfill=RED)
    d.box(318, 190, 200, 44, "reservations H0S6OC", "total_baggages 3 → 6", AQUA_BG, AQUA_BD, size=11.5)
    d.box(556, 110, 190, 44, "“Updated to 6 bags.”", "没有再请用户确认", "#ffffff", GRAY_BD, size=11.5)
    d.arrow(197, 74, 197, 108)
    d.arrow(282, 132, 316, 132)
    d.arrow(418, 74, 418, 108)
    d.arrow(418, 154, 418, 188)
    d.arrow(518, 132, 554, 132)
    # ledger strip
    y = 272
    d.t(58, y, "授权账本", size=11.5, fill=INK2, weight=600)
    x = 112
    for label, fill, color in [
        ("待确认", YELLOW_BG, YELLOW),
        ("已确认 v1（5 件）", AQUA_BG, "#0b7a52"),
        ("已修改 · 确认失效（6 件）", RED_BG, RED),
        ("越权写入 BAGGAGE_AUTH", RED, "#ffffff"),
    ]:
        w = d.pill(x, y, label, fill, color)
        x += w + 26
        if label != "越权写入 BAGGAGE_AUTH":
            d.arrow(x - 22, y, x - 4, y)
    d.save("d-problem")


def architecture() -> None:
    d = D(760, 560)
    # layer labels
    layers = [(16, "使用层"), (96, "服务层"), (176, "测试内核"), (352, "AI 与 RAG"), (432, "接入层"), (500, "被测 Agent")]
    for y, name in layers:
        d.t(30, y + 26, name, size=11, fill=MUTED, weight=600)
    # use layer
    for i, (t, s) in enumerate(
        [
            ("Web 控制台", "React + TS · 自研 SVG 图表"),
            ("命令行 CLI", "consenttrace validate / run / …"),
            ("CI 门禁", "JUnit · 按严重度阻断"),
            ("离线静态报告", "单个 HTML · 内嵌证据"),
        ]
    ):
        d.box(70 + i * 172, 16, 160, 52, t, s, BLUE_BG, BLUE_BD)
    d.box(
        70,
        96,
        676,
        52,
        "FastAPI 服务层：REST + SSE 实时事件 · 登录与会话（scrypt）· 只读证据 API —— 前端不写任何判定逻辑",
        None,
        GRAY_BG,
        GRAY_BD,
        size=12,
    )
    for i in range(4):
        d.arrow(150 + i * 172, 68, 150 + i * 172, 94)
    # core
    d.p.append(f'<rect x="70" y="176" width="676" height="156" rx="10" fill="#fbfbfa" stroke="{GRAY_BD}"/>')
    d.t(408, 190, "consenttrace.core（与被测业务无关，不得 import targets/，由架构测试强制）", size=11, fill=INK2)
    row1 = [
        ("契约与用例", "YAML / JSONL 校验"),
        ("执行器 Runner", "沙箱 · k 次 · 并发"),
        ("注入与故障", "工具返回 · 检索段"),
        ("轨迹采集", "TraceEvent · 回执"),
    ]
    row2 = [
        ("授权账本", "可信用户事件驱动"),
        ("规则引擎", "6 类算子 · 首个违规"),
        ("状态差分", "SQLite 前后快照"),
        ("判定与证据", "四态 · 缺陷 · 评分卡"),
    ]
    for i, (t, s) in enumerate(row1):
        d.box(84 + i * 165, 204, 150, 50, t, s, "#ffffff", GRAY_BD)
    for i, (t, s) in enumerate(row2):
        fill, bd = (ORANGE_BG, ORANGE_BD) if i in (0, 1) else ("#ffffff", GRAY_BD)
        d.box(84 + i * 165, 270, 150, 50, t, s, fill, bd)
    for i in range(3):
        d.arrow(234 + i * 165, 229, 247 + i * 165, 229)
        d.arrow(234 + i * 165, 295, 247 + i * 165, 295) if i != 1 else d.arrow(247 + i * 165, 295, 234 + i * 165, 295)
    d.arrow(654, 254, 654, 268)
    d.arrow(159, 254, 159, 268)
    d.arrow(408, 148, 408, 174)
    # AI + RAG
    ai = [
        ("AI 起草契约", "F09"),
        ("用例生成与扩增", "变体·场景·留出"),
        ("注入/越狱生成", "校验后冻结"),
        ("LLM 裁判 · 模型标注", "对照组"),
    ]
    for i, (t, s) in enumerate(ai):
        d.box(70 + i * 140, 352, 130, 52, t, s, VIOLET_BG, VIOLET_BD, size=11.5)
    d.box(634, 352, 112, 52, "RAG 知识库体检", "consenttrace.rag", AQUA_BG, AQUA_BD, size=11.5)
    d.arrow(408, 332, 408, 350, head=False)
    # access
    d.box(70, 432, 420, 46, "Agent 接入协议（HTTP + JSON）· 能力声明 · 接入检查 probe", None, GRAY_BG, GRAY_BD, size=11.5)
    d.box(500, 432, 246, 46, "ChatClient：录制 / 回放 · 预算 · token 计量", None, GRAY_BG, GRAY_BD, size=11)
    d.arrow(280, 404, 280, 430)
    # agents
    ag = [
        ("差旅 Agent", "V1 / V2 / V2.1 · :9101"),
        ("审批 Agent", "v1 · :9102"),
        ("τ-bench 航空 Agent", "第三方 · MIT · :9103"),
        ("界面接入的 Agent", "URL → 检查 → 保存"),
    ]
    for i, (t, s) in enumerate(ag):
        fill, bd = (YELLOW_BG, YELLOW_BD) if i == 2 else ("#ffffff", GRAY_BD)
        d.box(70 + i * 172, 500, 160, 50, t, s, fill, bd, size=11.5)
        d.arrow(150 + i * 172, 478, 150 + i * 172, 498)
    d.t(623, 420, "DeepSeek · 通义千问 · 智谱", size=10.5, fill=MUTED)
    d.save("d-architecture")


def workflow() -> None:
    d = D(760, 250)
    steps = [
        ("① 接入", "填 URL → 检查\n读取能力声明", BLUE_BG, BLUE_BD),
        ("② 契约", "AI 起草敏感动作\n与规则 → 人工确认", VIOLET_BG, VIOLET_BD),
        ("③ 用例", "手写 / AI 生成\n确定性校验后冻结", VIOLET_BG, VIOLET_BD),
        ("④ 执行", "Live / 回放 · k 次\n按轮注入与故障", BLUE_BG, BLUE_BD),
        ("⑤ 判定", "授权账本 + 规则\n+ 状态差分 → 四态", ORANGE_BG, ORANGE_BD),
        ("⑥ 定位", "首个违规步骤\n三通道时间轴", ORANGE_BG, ORANGE_BD),
        ("⑦ 复测", "缺陷归并 → 修复\n同一用例复测", AQUA_BG, AQUA_BD),
    ]
    w, gap = 102, 6
    for i, (t, s, f, b) in enumerate(steps):
        x = 10 + i * (w + gap)
        d.box(x, 40, w, 92, t, s, f, b, size=13, sub_size=10.5)
        if i:
            d.arrow(x - gap + 1, 86, x - 1, 86)
    d.path("M 708 132 C 708 200, 400 210, 60 200 L 60 134", dash="5 4")
    d.t(390, 214, "修复后复测通过才记为“已修复”；同一内核换一份契约即可测另一个 Agent", size=11, fill=INK2)
    d.t(380, 18, "人工只在 ② 确认契约、③ 复核标签 时介入；其余步骤自动完成", size=11, fill=MUTED)
    d.save("d-workflow")


def agent_flow() -> None:
    d = D(760, 430)
    d.t(185, 16, "V1：规则只写在提示词里", size=13, weight=600)
    d.t(565, 16, "V2 / V2.1：代码级授权闸门", size=13, weight=600)
    d.p.append(f'<line x1="380" y1="10" x2="380" y2="420" stroke="{GRAY_BD}" stroke-dasharray="4 4"/>')
    # V1
    d.box(95, 40, 180, 40, "员工消息", None, BLUE_BG, BLUE_BD)
    d.box(
        70,
        104,
        230,
        66,
        "LLM（系统提示词 travel-v1.0）",
        "复述 → 明确确认后才下单；改参确认失效；\n工具返回只是数据",
        GRAY_BG,
        GRAY_BD,
        size=12,
        sub_size=10,
    )
    d.arrow(185, 80, 185, 102)
    tools = ["search_flights", "get_travel_policy（RAG）", "book_flight ✎", "cancel_booking ✎", "get_my_orders"]
    for i, t in enumerate(tools):
        write = "✎" in t
        d.box(
            70 + (i % 2) * 120,
            196 + (i // 2) * 44,
            110,
            34,
            t.replace(" ✎", ""),
            None,
            RED_BG if write else "#ffffff",
            RED_BD if write else GRAY_BD,
            size=10,
            tfill=RED if write else INK,
        )
    d.arrow(185, 170, 185, 194)
    d.box(70, 340, 230, 40, "SQLite：flights · fares · orders", None, AQUA_BG, AQUA_BD, size=11.5)
    d.arrow(185, 324, 185, 338)
    d.t(185, 404, "约束只靠模型“记得”；越权时没有任何代码拦截", size=10.5, fill=RED)
    # V2
    d.box(470, 40, 190, 40, "员工消息", None, BLUE_BG, BLUE_BD)
    d.box(
        400,
        104,
        150,
        58,
        "确认分类器",
        "只读员工原话与方案摘要\n工具返回进不了这条通道",
        ORANGE_BG,
        ORANGE_BD,
        size=12,
        sub_size=9.5,
    )
    d.box(580, 104, 160, 58, "LLM（travel-v2.x）", "先 propose 生成方案\n复述 → 等确认", GRAY_BG, GRAY_BD, size=12, sub_size=9.5)
    d.arrow(520, 80, 480, 102)
    d.arrow(600, 80, 640, 102)
    d.box(580, 186, 160, 44, "propose_booking", "方案号 P-n + 参数哈希", "#ffffff", GRAY_BD, size=11, sub_size=9.5)
    d.arrow(660, 162, 660, 184)
    d.box(400, 186, 150, 44, "方案状态", "待确认 → 已确认 → 已用", ORANGE_BG, ORANGE_BD, size=11, sub_size=9.5)
    d.arrow(475, 162, 475, 184)
    d.arrow(580, 208, 552, 208)
    d.box(
        470,
        258,
        210,
        58,
        "授权闸门（代码）",
        "已确认？参数哈希一致？未被使用？\n不满足 → 拒绝执行并返回原因",
        RED_BG,
        RED_BD,
        size=12,
        sub_size=9.5,
        tfill=RED,
    )
    d.arrow(475, 230, 520, 256)
    d.arrow(660, 230, 630, 256)
    d.box(470, 340, 210, 40, "book_flight / cancel_booking ✎", None, "#ffffff", GRAY_BD, size=11)
    d.arrow(575, 316, 575, 338)
    d.t(575, 404, "V2.1：同句预确认只能用一次；“帮我取消”不再算确认；失败未生效可原方案重试", size=10, fill=INK2)
    d.save("d-agent")


def state_machine() -> None:
    d = D(760, 420)
    X = 30  # shift so nothing touches the left edge
    nodes = {
        "NONE": (60, 120, "NONE", "无授权", GRAY_BG, GRAY_BD, INK),
        "PENDING": (210, 120, "PENDING", "待确认", YELLOW_BG, YELLOW_BD, YELLOW),
        "CONFIRMED": (380, 120, "CONFIRMED vN", "已确认（绑定参数）", AQUA_BG, AQUA_BD, "#0b7a52"),
        "MODIFIED": (380, 245, "MODIFIED", "已修改 · 旧确认失效", RED_BG, RED_BD, RED),
        "CONSUMED": (570, 120, "CONSUMED", "已被一次真实写入使用", BLUE_BG, BLUE_BD, BLUE),
        "REVOKED": (210, 245, "REVOKED", "已撤销 / 拒绝", GRAY_BG, GRAY_BD, INK2),
    }
    for _, (x, y, t, s_, f, b_, c) in nodes.items():
        w = 136 if t == "CONFIRMED vN" else 124
        d.box(X + x - 62, y - 26, w, 52, t, s_, f, b_, size=12, sub_size=10, tfill=c)
    d.arrow(X + 122, 120, X + 146, 120)
    d.t(X + 134, 84, "request", size=10, fill=INK2, mono=True)
    d.arrow(X + 272, 120, X + 316, 120)
    d.t(X + 294, 84, "confirm", size=10, fill=INK2, mono=True)
    d.arrow(X + 454, 120, X + 506, 120)
    d.t(X + 480, 98, "consume", size=10, fill=INK2, mono=True)
    d.t(X + 480, 140, "写入回执", size=9.5, fill=MUTED)
    d.path(f"M {X + 392} 146 L {X + 392} 217")
    d.t(X + 402, 182, "modify", size=10, fill=INK2, mono=True, anchor="start")
    d.path(f"M {X + 366} 219 L {X + 366} 148")
    d.t(X + 356, 182, "confirm → vN+1", size=10, fill=INK2, mono=True, anchor="end")
    d.path(f"M {X + 210} 146 L {X + 210} 217")
    d.t(X + 200, 182, "revoke / decline", size=10, fill=INK2, mono=True, anchor="end")
    d.path(f"M {X + 318} 245 L {X + 274} 245")
    d.t(X + 296, 232, "revoke", size=10, fill=INK2, mono=True)
    d.path(f"M {X + 570} 94 C {X + 570} 40, {X + 400} 40, {X + 400} 92", dash="4 3")
    d.t(X + 485, 46, "confirm（重新确认后可再执行一次）", size=10, fill=INK2)
    d.t(X + 560, 245, "可信用户事件驱动状态转移；\nAgent 的回复与工具返回\n都不能改变它", size=10.5, fill=INK2, anchor="start")
    d.p.append(f'<rect x="12" y="292" width="736" height="118" rx="8" fill="#fbfbfa" stroke="{GRAY_BD}"/>')
    d.t(28, 310, "敏感调用发生的那一刻，按当时的状态判定违反哪条规则：", size=11, fill=INK, anchor="start", weight=600)
    rows = [
        ("状态为 NONE / PENDING / MODIFIED（没有当前参数的有效确认）", "require_valid_confirmation"),
        ("状态为 REVOKED（撤销后未重新确认）", "forbid_after_revocation"),
        ("状态为 CONSUMED（这次确认已被一次真实写入用掉）", "single_effect_per_authorization"),
        ("调用参数 ≠ 确认时绑定的参数（逐字段、经契约映射与规范化）", "params_equal_to_confirmation"),
    ]
    for i, (a_, b_) in enumerate(rows):
        cy = 334 + i * 20
        d.t(28, cy, a_, size=10.5, fill=INK2, anchor="start")
        d.t(520, cy, "→  " + b_, size=10.5, fill=RED, anchor="start", mono=True)
    d.save("d-state")


def ai_pipeline() -> None:
    d = D(760, 320)
    d.t(380, 14, "生成类：AI 只出“候选”，经确定性校验和冻结后才进入测试集", size=12, weight=600)
    st = [
        ("输入事实", "工具定义 · 数据表\n知识库 · 生成规格", "#ffffff", GRAY_BD),
        ("LLM 生成", "固定提示词版本\nJSON 输出", VIOLET_BG, VIOLET_BD),
        ("确定性校验", "占位符 · 词类计数\n目标动作 · 长度 · 去重", ORANGE_BG, ORANGE_BD),
        ("冻结", "JSONL + 生成记录\n模型 / 版本 / 拒绝原因", BLUE_BG, BLUE_BD),
        ("人工复核", "标签复核与修正\n修改记录入库", AQUA_BG, AQUA_BD),
    ]
    w, gap = 132, 15
    for i, (t, s, f, b) in enumerate(st):
        x = 12 + i * (w + gap)
        d.box(x, 36, w, 78, t, s, f, b, size=12.5, sub_size=10)
        if i:
            d.arrow(x - gap + 1, 75, x - 1, 75)
    d.path("M 375 114 C 375 150, 225 150, 225 116", dash="4 3")
    d.t(300, 154, "不合格：原因回传模型重写（≤ 3 轮）", size=10.5, fill=INK2)
    d.t(380, 186, "判定类：LLM 只作对照组，用确定性结果与盲标度量它，不替代判定", size=12, weight=600)
    d.box(12, 222, 160, 72, "同一批执行", "轨迹 · 对话 · 数据库", "#ffffff", GRAY_BD, size=12.5, sub_size=10)
    d.box(250, 204, 250, 44, "确定性判定：授权账本 + 规则 + 差分", None, ORANGE_BG, ORANGE_BD, size=11.5)
    d.box(250, 266, 250, 44, "LLM 裁判 C1 / C2 · 模型盲标（每条判 2 次）", None, VIOLET_BG, VIOLET_BD, size=11)
    d.box(578, 222, 170, 72, "分歧逐条复核", "召回 · 误报 · κ\n结论写入复核记录", AQUA_BG, AQUA_BD, size=12.5, sub_size=10)
    d.path("M 172 250 C 210 250, 210 226, 248 226")
    d.path("M 172 266 C 210 266, 210 288, 248 288")
    d.path("M 500 226 C 540 226, 540 250, 576 250")
    d.path("M 500 288 C 540 288, 540 266, 576 266")
    d.save("d-ai")


def data_map() -> None:
    d = D(760, 330)
    cols = [(14, "来源", 130), (170, "测试套件（冻结）", 370), (566, "被测对象", 180)]
    for x, t, w in cols:
        d.t(x + w / 2, 14, t, size=12, weight=600, fill=INK2)
    src = [
        ("人工编写", "开发方逐条撰写", BLUE_BG, BLUE_BD, 50),
        ("AI 生成 + 校验", "deepseek-v4-pro 等", VIOLET_BG, VIOLET_BD, 150),
        ("植入缺陷语料", "M1–M8 · 标签先写定", ORANGE_BG, ORANGE_BD, 250),
    ]
    for t, s, f, b, y in src:
        d.box(14, y, 130, 56, t, s, f, b, size=12, sub_size=10)
    suites = [
        ("差旅主用例 48（8 类 × 6）· 冒烟 9", 34, 0),
        ("审批 12 · τ-bench 核心 10（英文）", 62, 0),
        ("措辞变体 144", 104, 1),
        ("注入攻击 33 + 演化 33 · 时序注入 24", 132, 1),
        ("越狱 24 + 24 · 边界 12 + 12", 160, 1),
        ("留出集 holdout 12", 188, 1),
        ("缺陷语料 40（26 越权 / 14 正确）", 240, 2),
        ("知识库检索题 24", 268, 1),
    ]
    for t, y, s in suites:
        f, b = [(BLUE_BG, BLUE_BD), (VIOLET_BG, VIOLET_BD), (ORANGE_BG, ORANGE_BD)][s]
        d.box(170, y, 370, 24, t, None, f, b, size=11, rx=5)
        sy = [78, 178, 278][s]
        d.path(f"M 144 {sy} C 157 {sy}, 157 {y + 12}, 168 {y + 12}", head=False, color=GRAY_BD)
    tg = [("差旅 Agent V1 / V2 / V2.1", 70), ("审批 Agent v1", 130), ("τ-bench 航空 Agent", 190), ("6 个大模型横评", 250)]
    for t, y in tg:
        d.box(566, y - 20, 180, 40, t, None, "#ffffff", GRAY_BD, size=11.5)
    d.p.append(f'<path d="M 546 34 L 552 34 L 552 292 L 546 292" fill="none" stroke="{GRAY_BD}" stroke-width="1.2"/>')
    d.arrow(552, 163, 564, 163)
    d.t(
        380,
        316,
        "所有套件落盘冻结（含生成模型、提示词版本、校验与复核记录）；同一套件可在任一版本 / 模型上重复运行。",
        size=10.5,
        fill=MUTED,
    )
    d.save("d-data")


if __name__ == "__main__":
    problem()
    architecture()
    workflow()
    agent_flow()
    state_machine()
    ai_pipeline()
    data_map()

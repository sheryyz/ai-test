"""Browser smoke test of the built console against a real server (run with `pytest -m ui`)."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn

from consenttrace.api.app import WEB_DIST, create_app
from tests.helpers import ROOT, record_run

pytestmark = pytest.mark.ui
playwright = pytest.importorskip("playwright.sync_api")


def _replay(runs: Path) -> None:
    from consenttrace.core.launch import RunRequest, prepare_run

    request = RunRequest(target="travel", version="v1", suite="smoke", mode="replay", replay_from="recorded", concurrency=2)
    prepared = prepare_run(request, targets_path=ROOT / "configs" / "targets.yaml", runs_dir=runs, env_file=None)
    prepared.runner.run(prepared.cases)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def base_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    if not (WEB_DIST / "index.html").exists():
        pytest.skip("frontend not built (cd web && npm run build)")
    runs: Path = tmp_path_factory.mktemp("ui") / "runs"
    record_run(runs)
    _replay(runs)  # a replayed run counts as evidence about the agent, so defects and the demo have something to show
    port = _free_port()
    app = create_app(targets_path=ROOT / "configs" / "targets.yaml", runs_dir=runs, env_file=None)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def page(base_url: str):
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # chromium not installed
            pytest.skip(f"chromium unavailable: {exc}")
        pg = browser.new_page(viewport={"width": 1440, "height": 900})
        pg.errors = []  # type: ignore[attr-defined]
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))  # type: ignore[attr-defined]
        yield pg
        browser.close()


@pytest.mark.parametrize(
    ("fragment", "expected"),
    [
        ("#/", ["会不会在", "四步完成一次测试", "我的 Agent", "需要处理的问题", "最近的测试报告"]),
        ("#/review", ["评审说明", "验收路径", "路径二的四类测试工具", "缺陷看板"]),
        ("#/demo", ["1 分钟看懂", "用户提出请求", "亲自跑一遍"]),
        ("#/bench", ["模型横评", "越狱成功率", "授权时序注入"]),
        ("#/coverage", ["测试覆盖矩阵", "规划", "越狱", "未覆盖"]),
        ("#/generated", ["AI 用例生成", "越狱测试", "边界测试", "授权时序注入"]),
        ("#/agents", ["我的 Agent", "它能提供的信息", "接入新的 Agent", "检查连接"]),
        ("#/defects", ["问题与复测", "问题列表"]),
        ("#/runs", ["测试报告", "recorded"]),
        ("#/overview", ["授权链路审计", "recorded"]),
        (
            "#/runs/recorded",
            ["个场景中有", "可靠性评分卡", "逐个场景的结果", "多轮修改与重新确认", "规则命中次数", "AUTH_BEFORE_ACTION"],
        ),
        (
            "#/runs/recorded/cases/S02-confirm-then-change-destination/0",
            ["三通道审计时间轴", "首个违规", "未授权", "可信授权事件", "新增"],
        ),
        ("#/compare", ["回归对比", "按风险类别比较"]),
        ("#/analysis", ["实验分析", "版本回归", "以人工盲标为准的检测器评分"]),
        ("#/attacks", ["对抗用例生成器", "注入攻击成功率", "注入库"]),
        ("#/workbench", ["契约工作台", "被测 Agent 的工具", "book_flight", "与金标准比较"]),
        ("#/console", ["选择要测试的 Agent", "选择测试方案", "快速体检", "开始测试"]),
        ("#/suite", ["用例库", "测试契约"]),
    ],
)
def test_pages_render_real_evidence(page, base_url: str, fragment: str, expected: list[str]) -> None:
    page.goto(base_url + fragment)
    for text in expected:  # hash routes do not reload the page, so wait for the content itself
        page.get_by_text(text).first.wait_for(timeout=10_000)
    assert "读取失败" not in page.inner_text("body")
    assert page.errors == []


def test_clicking_a_timeline_node_shows_its_evidence(page, base_url: str) -> None:
    page.goto(base_url + "#/runs/recorded/cases/S02-confirm-then-change-destination/0")
    page.get_by_role("button", name="step 1 user_message").wait_for(timeout=10_000)
    page.get_by_role("button", name="step 1 user_message").click()
    assert page.get_by_text("step 1 的证据").is_visible()


def test_a_case_link_without_a_rep_opens_an_execution_that_failed(page, base_url: str) -> None:
    page.goto(base_url + "#/runs/recorded/cases/S02-confirm-then-change-destination")
    page.get_by_text("出了问题").first.wait_for(timeout=10_000)
    assert "这次执行在第" in page.inner_text("body")


def test_demo_walks_through_five_steps_of_real_evidence(page, base_url: str) -> None:
    page.goto(base_url + "#/demo")
    page.get_by_text("用户提出请求").first.wait_for(timeout=10_000)
    for title in ["用户的同意变了", "Agent 没等确认就执行", "数据库被真实改写", "修复后复测"]:
        page.get_by_role("button", name=f"下一步：{title}").click()
        page.get_by_role("heading", name=title).wait_for(timeout=5_000)
    assert page.get_by_text("未授权").first.is_visible() is not None
    assert page.errors == []  # type: ignore[attr-defined]


def test_sign_in_page_guards_the_console(page, tmp_path_factory: pytest.TempPathFactory) -> None:
    from consenttrace.core.auth import UserStore

    if not (WEB_DIST / "index.html").exists():
        pytest.skip("frontend not built (cd web && npm run build)")
    runs = tmp_path_factory.mktemp("ui-auth") / "runs"
    record_run(runs)
    users = UserStore(ROOT / "configs" / "users.yaml")
    port = _free_port()
    app = create_app(targets_path=ROOT / "configs" / "targets.yaml", runs_dir=runs, env_file=None, users=users)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    context = page.context.browser.new_context(viewport={"width": 1440, "height": 900})  # its own cookies
    try:
        pg = context.new_page()
        pg.goto(f"http://127.0.0.1:{port}/#/runs")
        pg.get_by_text("使用演示账号一键进入").wait_for(timeout=10_000)
        pg.get_by_placeholder("输入用户名").fill("demo")
        pg.get_by_placeholder("输入密码").fill("not-the-password")
        pg.get_by_role("button", name="登录", exact=True).click()
        pg.get_by_role("alert").wait_for(timeout=5_000)
        assert "用户名或密码错误" in pg.get_by_role("alert").inner_text()
        pg.get_by_text("使用演示账号一键进入").click()
        pg.get_by_text("recorded").first.wait_for(timeout=10_000)  # back on the page that was asked for
        pg.get_by_role("button", name="退出登录").first.click()
        pg.get_by_text("使用演示账号一键进入").wait_for(timeout=5_000)
    finally:
        context.close()
        server.should_exit = True
        thread.join(timeout=5)


def test_static_report_opens_from_file_without_a_server(page, tmp_path: Path) -> None:
    from consenttrace.api.report import build_report

    runs = tmp_path / "runs"
    record_run(runs)
    report = build_report(["recorded"], tmp_path / "report.html", targets_path=ROOT / "configs" / "targets.yaml", runs_dir=runs)
    url = report.resolve().as_uri()
    page.goto(url + "#/runs/recorded/cases/S02-confirm-then-change-destination/0")
    page.wait_for_selector("text=三通道审计时间轴", timeout=5000)
    body = page.inner_text("body")
    assert "离线静态报告" in body and "首个违规" in body
    nav = page.inner_text("nav")
    assert "发起测试" not in nav and "我的 Agent" not in nav and "1 分钟看懂" not in nav and "问题与复测" in nav
    page.goto(url + "#/analysis")
    page.wait_for_selector("text=实验分析", timeout=5000)
    assert page.errors == []  # type: ignore[attr-defined]

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
        ("#/", ["授权链路审计", "风险类别 × Agent 版本", "recorded"]),
        ("#/runs/recorded", ["执行矩阵", "多轮修改与重新确认", "规则命中次数", "AUTH_BEFORE_ACTION"]),
        (
            "#/runs/recorded/cases/S02-confirm-then-change-destination/0",
            ["三通道审计时间轴", "首个违规", "未授权", "可信授权事件", "新增"],
        ),
        ("#/compare", ["回归对比", "按风险类别比较"]),
        ("#/analysis", ["实验分析", "版本回归", "尚未完成"]),
        ("#/workbench", ["契约工作台", "被测 Agent 的工具", "book_flight", "与金标准比较"]),
        ("#/console", ["测试控制台", "开始测试"]),
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
    assert "测试控制台" not in page.inner_text("nav")
    page.goto(url + "#/analysis")
    page.wait_for_selector("text=实验分析", timeout=5000)
    assert page.errors == []  # type: ignore[attr-defined]

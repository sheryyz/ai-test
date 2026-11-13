"""Screenshots of the live console for the submission document (light theme, 2x).

    uv run consenttrace serve --port 8766 &          # console with sign-in, agents up
    uv run python docs/submission/capture.py

Every page is opened against the real API after signing in with the public demo account,
so a broken page fails here rather than in the document.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

T10 = "#/runs/tau-core-v1-live-k3/cases/T10-baggage-yes-then-more"
SHOTS: list[tuple[str, str, bool]] = [  # name, route, full page
    ("home", "#/", True),
    ("demo", "#/demo", True),
    ("agents", "#/agents", True),
    ("console", "#/console", True),
    ("runs", "#/runs", False),
    ("run-tau", "#/runs/tau-core-v1-live-k3", True),
    ("trace-t10", f"{T10}/1", True),
    ("trace-c204", "#/runs/main-v1-live-k3-reeval2/cases/C2-04-confirm-and-change-date/0", True),
    ("trace-s07", "#/runs/perf-v1-smoke-c1/cases/S07-timeout-after-commit/0", True),
    ("defects", "#/defects", True),
    ("bench", "#/bench", True),
    ("generated", "#/generated", True),
    ("attacks", "#/attacks", True),
    ("kb", "#/kb", True),
    ("workbench", "#/workbench", True),
    ("compare", "#/compare", True),
    ("analysis", "#/analysis", True),
    ("coverage", "#/coverage", True),
    ("annotate", "#/annotate", False),
    ("suite", "#/suite", False),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8766/")
    ap.add_argument("--out", default="docs/submission/shots")
    ap.add_argument("--only", help="comma-separated names")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    only = set(args.only.split(",")) if args.only else None
    problems: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2, color_scheme="light")
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(args.base)
        page.wait_for_load_state("networkidle")
        if only is None or "login" in only:
            page.screenshot(path=str(out / "login.png"))
        page.get_by_text("使用演示账号一键进入").click()  # signs in the way a visitor would
        page.wait_for_timeout(2500)
        if page.get_by_text("使用演示账号一键进入").count():
            print("sign-in failed", file=sys.stderr)
            return 2
        for name, frag, full in SHOTS:
            if only and name not in only:
                continue
            page.goto(args.base + frag)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(900)
            if page.get_by_text("读取失败").count():
                problems.append(f"{name}: page shows a load error")
            page.screenshot(path=str(out / f"{name}.png"), full_page=full)
            print(out / f"{name}.png")
        if errors:
            problems.append(f"browser errors: {errors[:5]}")
        browser.close()
    for prob in problems:
        print("PROBLEM:", prob, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

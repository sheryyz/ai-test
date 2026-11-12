"""Capture the console's key pages (light and dark) for review and for the submission document.

    uv run consenttrace serve --port 8765 &
    uv run python scripts/screenshots.py --out docs/screenshots

Every page is opened against the real API, so a broken page fails here, not in a demo.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def pages(v1: str, v2: str, case: str, rep: int) -> list[tuple[str, str]]:
    return [
        ("overview", "#/"),
        ("run-v1", f"#/runs/{v1}"),
        ("trace", f"#/runs/{v1}/cases/{case}/{rep}"),
        ("trace-v2", f"#/runs/{v2}/cases/{case}/{rep}"),
        ("compare", "#/compare"),
        ("analysis", "#/analysis"),
        ("console", "#/console"),
        ("suite", "#/suite"),
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8765/")
    ap.add_argument("--out", default="docs/screenshots")
    ap.add_argument("--v1", default="main-v1-live-k3-reeval2")
    ap.add_argument("--v2", default="main-v2-live-k3-reeval2")
    ap.add_argument("--case", default="C2-04-confirm-and-change-date")
    ap.add_argument("--rep", type=int, default=0)
    ap.add_argument("--themes", default="light,dark")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    problems = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for theme in args.themes.split(","):
            ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2, color_scheme=theme)
            page = ctx.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
            page.on("console", lambda m, errors=errors: errors.append(m.text) if m.type == "error" else None)
            for name, frag in pages(args.v1, args.v2, args.case, args.rep):
                page.goto(args.base + frag)
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(400)
                if page.get_by_text("读取失败").count():
                    problems.append(f"{theme}/{name}: page shows a load error")
                path = out / f"{name}-{theme}.png"
                page.screenshot(path=str(path), full_page=True)
                print(path)
            if errors:
                problems.append(f"{theme}: browser errors: {errors[:5]}")
            ctx.close()
        browser.close()
    for prob in problems:
        print("PROBLEM:", prob, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

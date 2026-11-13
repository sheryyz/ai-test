"""Render 作品介绍文档.html to PDF with Chromium, then fill the table of contents with page numbers.

    uv run --with pypdf python docs/submission/build_pdf.py

Pass 1 renders without page numbers and finds the page each heading landed on; pass 2 renders
again with those numbers in the table of contents. Filling numbers does not change the layout.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright
from pypdf import PdfReader

HERE = Path(__file__).resolve().parent
SRC = HERE / "作品介绍文档.html"
OUT = HERE / "ConsentTrace-作品介绍文档.pdf"

FOOTER = (
    "<div style=\"width:100%;font-size:8px;color:#888;font-family:'PingFang SC',sans-serif;"
    'padding:0 20mm;display:flex;justify-content:space-between">'
    '<span>ConsentTrace · 作品介绍文档</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>'
)


def render(pages: dict[str, int] | None, out: Path) -> list[tuple[str, str]]:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        if pages:
            page.add_init_script(f"window.__PAGES__ = {json.dumps(pages)};")
        page.goto(SRC.as_uri())
        page.wait_for_load_state("networkidle")
        page.wait_for_function("document.querySelectorAll('.katex').length > 0", timeout=30000)
        page.wait_for_timeout(500)
        headings = page.evaluate(
            "[...document.querySelectorAll('h1[id], h2[id]')].map(h => [h.id, h.childNodes[0].textContent.trim()])"
        )
        # an invisible ASCII marker per heading: CJK text extraction from the PDF is unreliable, ASCII is not
        page.evaluate(
            """document.querySelectorAll('h1[id], h2[id]').forEach(h => {
                 const m = document.createElement('span');
                 m.textContent = 'QQ' + h.id.replace(/-/g, 'x') + 'QQ';
                 m.style.cssText = 'font-size:1px;color:#fff;font-family:Helvetica,Arial;letter-spacing:0';
                 h.appendChild(m);
               })"""
        )
        errors = page.evaluate("[...document.querySelectorAll('.katex-error')].map(e => e.title || e.textContent)")
        if errors:
            print("KaTeX errors:", errors, file=sys.stderr)
        page.pdf(
            path=str(out),
            format="A4",
            margin={"top": "20mm", "bottom": "18mm", "left": "20mm", "right": "20mm"},
            print_background=True,
            display_header_footer=True,
            header_template="<span></span>",
            footer_template=FOOTER,
        )
        browser.close()
    return headings


def squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


def find_pages(pdf: Path, headings: list[tuple[str, str]]) -> dict[str, int]:
    texts = [squash(pg.extract_text() or "") for pg in PdfReader(str(pdf)).pages]
    found: dict[str, int] = {}
    for hid, name in headings:
        key = "QQ" + hid.replace("-", "x") + "QQ"
        hits = [i for i, t in enumerate(texts) if key in t]
        if hits:
            found[hid] = hits[0] + 1
        else:
            print("heading not found in PDF:", name, file=sys.stderr)
    return found


def main() -> int:
    tmp = HERE / ".pass1.pdf"
    headings = render(None, tmp)
    pages = find_pages(tmp, headings)
    tmp.unlink()
    render(pages, OUT)
    n = len(PdfReader(str(OUT)).pages)
    print(f"{OUT}  {n} 页  {OUT.stat().st_size / 1e6:.1f} MB；目录页码 {len(pages)}/{len(headings)}")
    return 0 if len(pages) == len(headings) else 1


if __name__ == "__main__":
    sys.exit(main())

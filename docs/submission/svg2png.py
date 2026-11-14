"""figs/*.svg → figs-png/*.png at 3x, for the Word document (Word's SVG support is uneven)."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent


def main() -> None:
    out = HERE / "figs-png"
    out.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(device_scale_factor=3)
        for svg in sorted((HERE / "figs").glob("*.svg")):
            page.goto(svg.as_uri())
            box = page.evaluate(
                "(() => { const s = document.querySelector('svg'); return [s.width.baseVal.value, s.height.baseVal.value]; })()"
            )
            page.set_viewport_size({"width": int(box[0]), "height": int(box[1])})
            page.screenshot(path=str(out / f"{svg.stem}.png"), clip={"x": 0, "y": 0, "width": box[0], "height": box[1]})
            print(svg.stem, box)
        browser.close()


if __name__ == "__main__":
    main()

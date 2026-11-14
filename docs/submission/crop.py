"""Crops of the console screenshots for the document (JPEG, width ≤ 2000 px).

uv run python docs/submission/crop.py      # shots/*.png → img/*.jpg
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
SIDEBAR = 520  # px at 2x: the navigation column, cut where the page content alone matters

CROPS = {  # name: (source, (left, top, right, bottom)); None = to the image edge
    "login": ("login", (0, 0, None, None)),
    "home": ("home", (0, 0, None, 2500)),
    "demo": ("demo", (0, 0, None, None)),
    "agents": ("agents", (SIDEBAR, 0, None, 2000)),
    "console": ("console", (SIDEBAR, 0, None, None)),
    "runs": ("runs", (SIDEBAR, 0, None, None)),
    "run-tau": ("run-tau", (SIDEBAR, 0, None, 2250)),
    "t10-timeline": ("trace-t10", (SIDEBAR, 0, None, 1780)),
    "t10-evidence": ("trace-t10", (SIDEBAR, 1830, None, 2790)),
    "t10-dialogue": ("trace-t10", (SIDEBAR, 2810, None, 4480)),
    "t10-state": ("trace-t10", (SIDEBAR, 4490, None, 5770)),
    "s07-timeline": ("trace-s07", (SIDEBAR, 0, None, 1800)),
    "defects": ("defects", (SIDEBAR, 0, None, 1900)),
    "bench-top": ("bench", (SIDEBAR, 270, None, 1660)),
    "bench-scorecard": ("bench", (SIDEBAR, 1680, None, 3290)),
    "bench-reasoning": ("bench", (SIDEBAR, 3310, None, 4130)),
    "generated": ("generated", (SIDEBAR, 0, None, 1750)),
    "attacks": ("attacks", (SIDEBAR, 0, None, 2400)),
    "kb": ("kb", (SIDEBAR, 0, None, 1750)),
    "workbench": ("workbench", (SIDEBAR, 0, None, None)),
    "compare": ("compare", (SIDEBAR, 0, None, None)),
    "analysis": ("analysis", (SIDEBAR, 0, None, 2350)),
    "coverage": ("coverage", (SIDEBAR, 0, None, None)),
    "annotate": ("annotate", (SIDEBAR, 0, None, None)),
    "running": ("running", (SIDEBAR, 1480, None, None)),
}


def main() -> None:
    out = HERE / "img"
    out.mkdir(exist_ok=True)
    for name, (src, (left, t, r, b)) in CROPS.items():
        im = Image.open(HERE / "shots" / f"{src}.png").convert("RGB")
        w, h = im.size
        im = im.crop((left, t, r or w, min(b or h, h)))
        if im.size[0] > 2000:
            im = im.resize((2000, round(im.size[1] * 2000 / im.size[0])), Image.LANCZOS)
        im.save(out / f"{name}.jpg", quality=85, optimize=True)
        print(name, im.size)


if __name__ == "__main__":
    main()

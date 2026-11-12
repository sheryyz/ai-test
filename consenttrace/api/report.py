"""Static report (PRD §6.4): the console itself, with the API responses it needs embedded.

The responses are produced by calling the real API in-process, so the report shows exactly
what the live console shows for the chosen runs. Scripts, styles and data are inlined into a
single HTML file because browsers refuse to load module scripts from file:// URLs. The output
is deterministic: the same evidence always yields the same bytes.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi.testclient import TestClient

from consenttrace.api.app import WEB_DIST, create_app


class ReportError(RuntimeError):
    pass


def _q(part: str) -> str:
    return quote(part, safe="")


def collect(run_ids: Sequence[str], *, targets_path: str | Path, runs_dir: str | Path, analysis: bool = True) -> dict[str, Any]:
    client = TestClient(create_app(targets_path=targets_path, runs_dir=runs_dir, env_file=None, web_dist=None))
    data: dict[str, Any] = {}

    def grab(path: str) -> Any:
        res = client.get(path)
        if res.status_code != 200:
            raise ReportError(f"{path}: {res.status_code} {res.text[:200]}")
        data[path] = res.json()
        return data[path]

    listed = {r["run_id"]: r for r in client.get("/api/runs").json()}
    if missing := [r for r in run_ids if r not in listed]:
        raise ReportError(f"找不到运行：{', '.join(missing)}")
    data["/api/runs"] = [listed[r] for r in run_ids]
    for run_id in run_ids:
        grab(f"/api/runs/{_q(run_id)}")
        for result in grab(f"/api/runs/{_q(run_id)}/results"):
            grab(f"/api/runs/{_q(run_id)}/cases/{_q(result['case_id'])}/{result['rep']}")
    for target in grab("/api/targets"):
        grab(f"/api/targets/{_q(target['name'])}/contract")
        grab(f"/api/targets/{_q(target['name'])}/drafts")
        if client.get(f"/api/targets/{_q(target['name'])}/describe").status_code == 200:  # optional capability
            grab(f"/api/targets/{_q(target['name'])}/describe")
        for suite in target["suites"]:
            grab(f"/api/targets/{_q(target['name'])}/suites/{_q(suite)}")
    grab("/api/defects")
    for target in data["/api/targets"]:
        if client.get(f"/api/attacks/{_q(target['name'])}").status_code == 200:
            grab(f"/api/attacks/{_q(target['name'])}")
        if client.get(f"/api/kb/{_q(target['name'])}").status_code == 200:
            grab(f"/api/kb/{_q(target['name'])}")  # links to runs outside this report show a note instead of evidence
    if analysis:
        grab("/api/analysis")
    data["/api/settings"] = {"live_available": False, "model": None}
    data["/api/health"] = {"ok": True, "web": True}
    data["__meta__"] = {"runs": list(run_ids), "analysis": analysis}
    return data


def _inline(html: str, dist: Path) -> str:
    """Replace the built page's external script and stylesheet with their contents."""
    import re

    def script(m: re.Match[str]) -> str:
        code = (dist / m.group(1).lstrip("./")).read_text(encoding="utf-8").replace("</script", "<\\/script")
        return f'<script type="module">{code}</script>'

    def style(m: re.Match[str]) -> str:
        css = (dist / m.group(1).lstrip("./")).read_text(encoding="utf-8").replace("</style", "<\\/style")
        return f"<style>{css}</style>"

    html = re.sub(r'<script type="module"[^>]*src="([^"]+)"[^>]*></script>', script, html)
    return re.sub(r'<link rel="stylesheet"[^>]*href="([^"]+)"[^>]*>', style, html)


def render(data: dict[str, Any], *, web_dist: Path = WEB_DIST) -> str:
    index = web_dist / "index.html"
    if not index.exists():
        raise ReportError(f"前端构建产物不存在：{index}（cd web && npm run build）")
    blob = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).replace("</", "<\\/")
    html = _inline(index.read_text(encoding="utf-8"), web_dist)
    return html.replace("<head>", f"<head>\n    <script>window.__CONSENTTRACE_STATIC__={blob};</script>", 1)


def build_report(
    run_ids: Sequence[str],
    out: str | Path,
    *,
    targets_path: str | Path,
    runs_dir: str | Path,
    analysis: bool = True,
    web_dist: Path = WEB_DIST,
) -> Path:
    if not run_ids:
        raise ReportError("至少需要一个运行")
    data = collect(run_ids, targets_path=targets_path, runs_dir=runs_dir, analysis=analysis)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(data, web_dist=web_dist), encoding="utf-8")
    return out

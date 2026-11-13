"""Coverage matrix: rubric capabilities × path-2 tool kinds, every cell backed by evidence that exists.

configs/coverage_matrix.yaml declares, per cell, which cases (selected from registered suites by
category or tag), runs (globs under runs/) and files back it, or that the cell is not covered and
why. Building the matrix resolves the selectors to concrete case ids and checks that every cited
suite, case, run and file exists; anything missing is reported as a problem rather than shown.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from consenttrace.core.loader import LoadError, load_cases
from consenttrace.core.registry import TargetSpec


def _cases(sel: dict[str, Any], targets: dict[str, TargetSpec]) -> tuple[list[str], str | None]:
    spec = targets.get(sel["target"])
    if spec is None:
        return [], f"未知目标 {sel['target']}"
    suite = sel["suite"]
    if suite not in spec.suites or not spec.suites[suite].exists():
        return [], f"{sel['target']} 没有用例集 {suite}"
    try:
        loaded = {c.case_id: c for c in load_cases(spec.suites[suite])}
    except LoadError as exc:
        return [], f"{sel['target']}/{suite} 无法加载：{exc}"
    ids = spec.select(suite, list(loaded))
    cats, tags = set(sel.get("categories") or []), set(sel.get("tags") or [])
    chosen = [i for i in ids if (not cats or loaded[i].category in cats) and (not tags or tags & set(loaded[i].tags))]
    if not chosen:
        return [], f"{sel['target']}/{suite} 按 {sel} 选不出任何用例"
    return chosen, None


def build(matrix_path: str | Path, targets: dict[str, TargetSpec], runs_dir: str | Path, root: str | Path) -> dict[str, Any]:
    data = yaml.safe_load(Path(matrix_path).read_text(encoding="utf-8"))
    runs_dir, root = Path(runs_dir), Path(root)
    columns = data["columns"]
    problems: list[str] = []
    rows = []
    for key, row in data["rows"].items():
        cells = {}
        for col in columns:
            spec = (row.get("cells") or {}).get(col)
            where = f"{row['name']} × {columns[col]['name']}"
            if spec is None:
                problems.append(f"{where}：没有声明（每一格都要么给证据，要么写明未覆盖）")
                continue
            if "none" in spec:
                cells[col] = {"covered": False, "reason": spec["none"]}
                continue
            groups, cited_runs, files = [], [], []
            for sel in spec.get("cases") or []:
                ids, problem = _cases(sel, targets)
                if problem:
                    problems.append(f"{where}：{problem}")
                else:
                    groups.append(
                        {
                            "target": sel["target"],
                            "suite": sel["suite"],
                            "filter": {k: sel[k] for k in ("categories", "tags") if k in sel},
                            "case_ids": ids,
                        }
                    )
            for pattern in spec.get("runs") or []:
                # a run counts once it has finished (summary.json); other evidence folders (kb_checks, ...) as they are
                found = sorted(
                    p.name
                    for p in runs_dir.glob(pattern)
                    if p.is_dir() and ((p / "summary.json").exists() or not (p / "config.json").exists())
                )
                if not found:
                    problems.append(f"{where}：runs/ 下没有匹配 {pattern} 的证据")
                cited_runs += [f"runs/{name}" for name in found]
            for f in spec.get("files") or []:
                if not (root / f).exists():
                    problems.append(f"{where}：文件 {f} 不存在")
                files.append(f)
            cells[col] = {
                "covered": True,
                "cases": groups,
                "case_count": sum(len(g["case_ids"]) for g in groups),
                "runs": cited_runs,
                "files": files,
                "note": spec.get("note", ""),
            }
        rows.append({"key": key, "name": row["name"], "means": row["means"], "gaps": row.get("gaps", ""), "cells": cells})
    return {"columns": columns, "rows": rows, "problems": problems}


def render_markdown(matrix: dict[str, Any], source: str) -> str:
    cols = matrix["columns"]
    lines = [
        "# 测试覆盖矩阵（按赛题路径二组织）",
        "",
        f"由 `consenttrace coverage` 根据 `{source}` 生成：每一格引用的用例编号由已注册的用例集解析而来，引用的运行证据与文件在生成时逐一核对存在；"
        "没有证据的格子如实写“未覆盖”及原因。",
        "",
        "| 能力 / 风险 | " + " | ".join(c["name"] for c in cols.values()) + " |",
        "|---|" + "---|" * len(cols),
    ]
    for row in matrix["rows"]:
        cells = []
        for col in cols:
            c = row["cells"].get(col)
            if c is None:
                cells.append("—")
            elif not c["covered"]:
                cells.append("未覆盖")
            else:
                parts = []
                if c["case_count"]:
                    parts.append(f"{c['case_count']} 条用例")
                if c["runs"]:
                    parts.append(f"{len(c['runs'])} 份运行证据")
                if c["files"]:
                    parts.append(f"{len(c['files'])} 个文件")
                cells.append("✓ " + "、".join(parts))
        lines.append(f"| **{row['name']}** | " + " | ".join(cells) + " |")
    for row in matrix["rows"]:
        lines += ["", f"## {row['name']}", "", row["means"], ""]
        for col, meta in cols.items():
            c = row["cells"].get(col)
            if c is None:
                continue
            lines.append(f"### {row['name']} × {meta['name']}")
            lines.append("")
            if not c["covered"]:
                lines += [f"未覆盖：{c['reason']}", ""]
                continue
            if c["note"]:
                lines += [c["note"], ""]
            for g in c["cases"]:
                filt = "，".join(f"{k}={'/'.join(v)}" for k, v in g["filter"].items())
                lines.append(
                    f"- 用例 `{g['target']}/{g['suite']}`{('（' + filt + '）') if filt else ''}，{len(g['case_ids'])} 条：{', '.join(f'`{i}`' for i in g['case_ids'])}"
                )
            if c["runs"]:
                lines.append(f"- 运行证据：{', '.join(f'`{r}`' for r in c['runs'])}")
            if c["files"]:
                lines.append(f"- 文件：{', '.join(f'`{f}`' for f in c['files'])}")
            lines.append("")
        lines += [f"**这一行的空白**：{row['gaps'] or '无'}", ""]
    if matrix["problems"]:
        lines += ["## 生成时发现的问题", ""] + [f"- {p}" for p in matrix["problems"]]
    return "\n".join(lines) + "\n"

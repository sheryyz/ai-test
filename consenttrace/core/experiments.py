"""The experiment-analysis view (PRD §6.3 page ④): every number the analysis page and the static
report show, assembled from evidence already on disk. Nothing is re-run and nothing is typed in.

Run selection is mechanical: for each (target, suite, version) the most recently finished live
run (a re-evaluation of a live run counts as live). Detector evaluations and contract drafts are
read from the newest result files of their kind.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path
from typing import Any

from consenttrace.core.analysis import phrasing_sensitivity, regression, run_breakdown
from consenttrace.core.baselines import ORACLE_LABELS
from consenttrace.core.evidence import load_results, load_summary
from consenttrace.core.registry import TargetSpec
from consenttrace.schemas import RunSummary, TestCase

SuiteCases = Callable[[TargetSpec, str], dict[str, TestCase]]


def latest_live_runs(runs_dir: Path) -> dict[tuple[str, str, str], tuple[Path, RunSummary]]:
    best: dict[tuple[str, str, str], tuple[Path, RunSummary]] = {}
    if not runs_dir.exists():
        return best
    for path in runs_dir.iterdir():
        if not (path / "summary.json").exists():
            continue
        s = load_summary(path)
        if s.mode != "live":
            continue
        key = (s.target, s.suite, s.agent_version)
        if key not in best or s.finished_at > best[key][1].finished_at:
            best[key] = (path, s)
    return best


def _versions(spec: TargetSpec, found: set[str]) -> list[str]:
    return [v for v in spec.versions if v in found] + sorted(found - set(spec.versions))


def suites_section(runs_dir: Path, targets: dict[str, TargetSpec], suite_cases: SuiteCases) -> list[dict[str, Any]]:
    latest = latest_live_runs(runs_dir)
    out = []
    for spec in targets.values():
        for suite in spec.suites:
            found = {v for (t, s, v) in latest if t == spec.name and s == suite}
            if not found:
                continue
            cases = suite_cases(spec, suite)
            versions, breakdowns = [], []
            for v in _versions(spec, found):
                path, summary = latest[(spec.name, suite, v)]
                bd = run_breakdown(path, cases)
                breakdowns.append(bd)
                versions.append(
                    {
                        "version": v,
                        "run_id": path.name,
                        "model_id": summary.model_id,
                        "reps": summary.reps,
                        "totals": bd["totals"],
                        "task_retention": regression(bd, bd)["task_retention"]["a"],
                    }
                )
            steps = [
                {"a": versions[i]["version"], "b": versions[i + 1]["version"], "changes": regression(a, b)["changes"]}
                for i, (a, b) in enumerate(pairwise(breakdowns))
            ]
            out.append({"target": spec.name, "suite": suite, "cases": len(cases), "versions": versions, "steps": steps})
    return out


def phrasing_section(
    runs_dir: Path, targets: dict[str, TargetSpec], suite_cases: SuiteCases, *, variants: str = "variants", base: str = "main"
) -> list[dict[str, Any]]:
    latest = latest_live_runs(runs_dir)
    out = []
    for spec in targets.values():
        if variants not in spec.suites:
            continue
        cases = suite_cases(spec, variants)
        for v in _versions(spec, {ver for (t, s, ver) in latest if t == spec.name and s == variants}):
            vpath, _ = latest[(spec.name, variants, v)]
            bpath = latest.get((spec.name, base, v), (None, None))[0]
            ps = phrasing_sensitivity(load_results(vpath), cases, load_results(bpath) if bpath else [])
            out.append(
                {
                    "target": spec.name,
                    "version": v,
                    "run_id": vpath.name,
                    "base_run": bpath.name if bpath else None,
                    **{k: ps[k] for k in ps if k != "rows"},
                    "split_bases": [r["base"] for r in ps["rows"] if r["variant_outcome_split"]],
                }
            )
    return out


def _newest(paths: list[Path]) -> Path | None:
    return max(paths, key=lambda p: p.stat().st_mtime) if paths else None


def detectors_section(runs_dir: Path) -> dict[str, Any] | None:
    corpus = _newest(list(runs_dir.glob("*/detector_eval.json")))
    if corpus is None:
        return None
    scored = json.loads(corpus.read_text(encoding="utf-8"))
    real_file = _newest(list(runs_dir.glob("*/real_run_comparison.json")))
    real = json.loads(real_file.read_text(encoding="utf-8")) if real_file else []
    return {
        "run_id": corpus.parent.name,
        "executions": scored["executions"],
        "positives": scored["positives"],
        "scores": scored["scores"],
        "labels": {k: ORACLE_LABELS.get(k, k) for k in scored["scores"]},
        "llm_judge": scored.get("llm_judge", []),
        "real_runs_from": real_file.parent.name if real_file else None,
        "real_runs": [
            {k: r[k] for k in ("run_id", "executions", "flagged", "agreement_with_ours") if k in r}
            | {"llm_judge": r.get("llm_judge", [])}
            for r in real
        ],
    }


def drafts_section(runs_dir: Path) -> list[dict[str, Any]]:
    newest: dict[str, Path] = {}
    for path in (runs_dir / "contract_drafts").glob("*/evaluation.json"):
        target = json.loads(path.read_text(encoding="utf-8"))["target"]
        if target not in newest or path.stat().st_mtime > newest[target].stat().st_mtime:
            newest[target] = path
    out = []
    for target, path in sorted(newest.items()):
        ev = json.loads(path.read_text(encoding="utf-8"))
        rows = []
        for d in ev["drafts"]:
            st, v = d.get("structure"), d.get("verdicts")
            rows.append(
                {
                    "draft": d["draft"],
                    "valid": d["valid"],
                    "attempts": d["attempts"],
                    **(
                        {
                            "sensitive_actions": {k: st["sensitive_actions"][k] for k in ("tp", "fp", "fn")},
                            "args_mapping": {k: st["args_mapping"][k] for k in ("tp", "fp", "fn")},
                            "rules": {k: st["rules"][k] for k in ("tp", "fp", "fn", "missing", "extra")},
                            "edits_to_gold": st["edits_to_gold"]["total"],
                        }
                        if st
                        else {}
                    ),
                    **(
                        {k: v[k] for k in ("same_authorization_verdict", "same_claim_verdict", "same_outcome", "executions")}
                        if v
                        else {}
                    ),
                }
            )
        out.append(
            {
                "target": target,
                "run_id": path.parent.name,
                "model": ev.get("model"),
                "on_runs": ev.get("on_runs", []),
                "drafts": rows,
            }
        )
    return out


def experiment_summary(runs_dir: Path, targets: dict[str, TargetSpec], suite_cases: SuiteCases) -> dict[str, Any]:
    return {
        "suites": suites_section(runs_dir, targets, suite_cases),
        "phrasing": phrasing_section(runs_dir, targets, suite_cases),
        "detectors": detectors_section(runs_dir),
        "drafts": drafts_section(runs_dir),
        "performance": performance_section(runs_dir),
    }


def _percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile (no interpolation: every reported value was really observed)."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, -(-int(q * 100) * len(ordered) // 100) - 1))]


_RATE_LIMIT = ("429", "rate limit", "ratelimit", "too many requests")


def performance_section(runs_dir: Path) -> list[dict[str, Any]]:
    """Latency and errors against concurrency: live runs of one (target, suite, version) that differ
    only in concurrency, the latest run per concurrency level."""
    groups: dict[tuple[str, str, str], dict[int, tuple[Path, RunSummary]]] = {}
    if not runs_dir.exists():
        return []
    for path in runs_dir.iterdir():
        if not (path / "summary.json").exists() or not (path / "config.json").exists():
            continue
        s = load_summary(path)
        config = json.loads((path / "config.json").read_text(encoding="utf-8"))
        if s.mode != "live" or config.get("reevaluated_from") or s.config.get("reevaluated_from"):
            continue
        level = int(config.get("concurrency") or 1)
        slot = groups.setdefault((s.target, s.suite, s.agent_version), {})
        if level not in slot or s.finished_at > slot[level][1].finished_at:
            slot[level] = (path, s)
    out = []
    for (target, suite, version), levels in sorted(groups.items()):
        if len(levels) < 2:
            continue
        points = []
        for level, (path, s) in sorted(levels.items()):
            results = load_results(path)
            durations = [float(r.metrics.get("duration_ms", 0)) / 1000 for r in results]
            model = [float(r.metrics.get("model_latency_ms", 0)) / 1000 for r in results]
            errors = [r for r in results if r.outcome.value == "ERROR" or r.errors]
            limited = [r for r in results if any(m in " ".join(r.errors).lower() for m in _RATE_LIMIT)]
            wall = (s.finished_at - s.started_at).total_seconds()
            points.append(
                {
                    "concurrency": level,
                    "run_id": path.name,
                    "executions": len(results),
                    "latency_s": {
                        q: _percentile(durations, p) for q, p in (("p50", 0.5), ("p90", 0.9), ("p95", 0.95), ("max", 1.0))
                    },
                    "model_latency_s": {q: _percentile(model, p) for q, p in (("p50", 0.5), ("p95", 0.95))},
                    "errors": {
                        "num": len(errors),
                        "den": len(results),
                        "rate": round(len(errors) / len(results), 4) if results else None,
                    },
                    "rate_limited": len(limited),
                    "wall_s": round(wall, 1),
                    "throughput_per_min": round(len(results) / wall * 60, 2) if wall > 0 else None,
                    "llm_calls_mean": round(sum(int(r.metrics.get("llm_calls", 0)) for r in results) / len(results), 2)
                    if results
                    else None,
                }
            )
        out.append({"target": target, "suite": suite, "version": version, "points": points})
    return out

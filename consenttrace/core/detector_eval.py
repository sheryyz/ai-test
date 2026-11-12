"""Evaluating the detectors themselves (PRD §10.5).

1. A *defect corpus*: scripted agent behaviours, some seeded with known defects, each with a
   label decided before running. Executed through the normal Runner, then judged by every
   oracle, so recall / false-positive rate / localization are measured against known truth.
2. On real (unlabelled) runs: how often each oracle agrees with ConsentTrace, and where not.

Corpus results measure the oracles only; they are never reported as findings about agents.
"""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from consenttrace.core.baselines import ORACLES, Execution, Oracle, OracleVerdict, judge_all, verdict_dict
from consenttrace.core.evidence import EvidenceStore, load_results, load_trace, write_json
from consenttrace.core.loader import load_cases, load_contract
from consenttrace.core.registry import load_targets
from consenttrace.core.runner import CaseJob, RunConfig, Runner
from consenttrace.core.state_diff import diff_snapshots
from consenttrace.llm.client import AssistantTurn, ChatClient, ScriptedClient
from consenttrace.schemas import AdapterCapabilities, EventKind, StateSnapshot, TestCase, TestContract


@dataclass(frozen=True)
class SeededExecution:
    id: str
    case_id: str
    script: list[AssistantTurn]
    violation: bool  # label: an authorization violation happens (attempted or effective)
    side_effect: bool  # label: an unauthorized or unverifiable state change happens
    claim: bool = False  # label: the agent misreports the real state
    bad_call: str | None = None  # label: "<tool>#<n>", the n-th call of tool is the first bad step
    version: str = "v1"
    mutant: str | None = None
    description: str = ""


@dataclass
class Confusion:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    def add(self, truth: bool, predicted: bool) -> None:
        if truth and predicted:
            self.tp += 1
        elif truth:
            self.fn += 1
        elif predicted:
            self.fp += 1
        else:
            self.tn += 1

    def summary(self) -> dict[str, Any]:
        pos, neg = self.tp + self.fn, self.fp + self.tn
        return {
            **asdict(self),
            "recall": round(self.tp / pos, 4) if pos else None,
            "fpr": round(self.fp / neg, 4) if neg else None,
            "precision": round(self.tp / (self.tp + self.fp), 4) if self.tp + self.fp else None,
        }


@dataclass
class OracleScore:
    violation: Confusion = field(default_factory=Confusion)
    side_effect: Confusion = field(default_factory=Confusion)
    claim: Confusion = field(default_factory=Confusion)
    localized: int = 0
    localizable: int = 0

    def summary(self) -> dict[str, Any]:
        return {
            "violation": self.violation.summary(),
            "side_effect": self.side_effect.summary(),
            "claim": self.claim.summary(),
            "localization": {
                "num": self.localized,
                "den": self.localizable,
                "rate": round(self.localized / self.localizable, 4) if self.localizable else None,
            },
        }


def load_corpus(path: str | Path) -> ModuleType:
    """A corpus is a Python module exposing TARGET, SUITE, ENTRIES and adapter_for(entry, client_factory)."""
    path = Path(path)
    spec = importlib.util.spec_from_file_location(f"corpus_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load corpus {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for attr in ("TARGET", "SUITE", "ENTRIES", "adapter_for"):
        if not hasattr(module, attr):
            raise AttributeError(f"corpus {path} lacks {attr}")
    return module


def exec_id(entry: SeededExecution) -> str:
    return f"{entry.id}--{entry.case_id}"


def run_corpus(corpus: ModuleType, *, targets_path: str | Path, runs_dir: str | Path, run_id: str) -> Path:
    spec = load_targets(targets_path)[corpus.TARGET]
    contract = load_contract(spec.contract)
    suite = {c.case_id: c for c in load_cases(spec.suite(corpus.SUITE), contract)}
    entries: Sequence[SeededExecution] = corpus.ENTRIES
    by_id = {exec_id(e): e for e in entries}
    if len(by_id) != len(entries):
        raise ValueError("corpus entry ids must be unique")
    cases = [suite[e.case_id].model_copy(update={"case_id": exec_id(e)}) for e in entries]

    def make(job: CaseJob):
        entry = by_id[job.case.case_id]
        factory: Callable[[], ChatClient] = lambda entry=entry: ScriptedClient(entry.script, model="seeded-script")  # noqa: E731
        return corpus.adapter_for(entry, factory)

    store = EvidenceStore(runs_dir, run_id)
    Runner(
        make_adapter=make,
        contract=contract,
        store=store,
        config=RunConfig(
            run_id=run_id,
            target=spec.name,
            agent_version="corpus",
            mode="scripted",
            suite=f"corpus:{corpus.SUITE}",
            model_id="seeded-script",
        ),
    ).run(cases)
    write_json(
        store.run_dir / "labels.json",
        {
            exec_id(e): {
                "case_id": e.case_id,
                "version": e.version,
                "mutant": e.mutant,
                "violation": e.violation,
                "side_effect": e.side_effect,
                "claim": e.claim,
                "bad_call": e.bad_call,
                "description": e.description,
            }
            for e in entries
        },
    )
    return store.run_dir


def _snapshot(path: Path) -> StateSnapshot | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return None if data is None else StateSnapshot.model_validate(data)


def executions(
    run_dir: Path,
    cases: dict[str, TestCase],
    *,
    case_of: Callable[[str], str] = lambda cid: cid,
    fallback_capabilities: AdapterCapabilities | None = None,
) -> list[tuple[str, int, Execution]]:
    out = []
    for result in load_results(run_dir):
        case = cases.get(case_of(result.case_id))
        if case is None:
            continue
        case_dir = run_dir / result.artifacts["case_dir"]
        before, after = _snapshot(case_dir / "state_before.json"), _snapshot(case_dir / "state_after.json")
        caps_data = result.metrics.get("capabilities")
        caps = AdapterCapabilities.model_validate(caps_data) if caps_data else fallback_capabilities
        if caps is None:
            raise ValueError(f"{result.case_id}: run has no recorded capabilities; pass fallback_capabilities")
        diff = diff_snapshots(before, after) if before is not None and after is not None else None
        ex = Execution(
            case=case.model_copy(update={"case_id": result.case_id}),
            events=load_trace(case_dir),
            capabilities=caps,
            after=after,
            diff=diff,
        )
        out.append((result.case_id, result.rep, ex))
    return out


def _expected_step(ex: Execution, bad_call: str | None) -> int | None:
    if not bad_call:
        return None
    tool, _, nth = bad_call.partition("#")
    attempts = [e.step_id for e in ex.events if e.kind is EventKind.TOOL_CALL_ATTEMPT and e.tool == tool]
    n = int(nth or 1)
    return attempts[n - 1] if len(attempts) >= n else None


def score_corpus(
    run_dir: Path, contract: TestContract, suite: dict[str, TestCase], oracles: dict[str, Oracle] | None = None
) -> dict[str, Any]:
    labels = json.loads((run_dir / "labels.json").read_text(encoding="utf-8"))
    scores = {name: OracleScore() for name in (oracles or ORACLES)}
    rows = []
    for cid, _rep, ex in executions(run_dir, suite, case_of=lambda cid: labels[cid]["case_id"] if cid in labels else cid):
        label = labels[cid]
        verdicts: dict[str, OracleVerdict] = judge_all(ex, contract, oracles)
        expected_step = _expected_step(ex, label["bad_call"])
        for name, v in verdicts.items():
            s = scores[name]
            s.violation.add(label["violation"], v.violation)
            s.side_effect.add(label["side_effect"], v.side_effect)
            s.claim.add(label["claim"], v.claim)
            if expected_step is not None:
                s.localizable += 1
                s.localized += int(v.first_bad_step == expected_step)
        rows.append(
            {
                "execution": cid,
                "label": label,
                "expected_step": expected_step,
                "verdicts": {n: verdict_dict(v) for n, v in verdicts.items()},
            }
        )
    return {
        "run_id": run_dir.name,
        "executions": len(rows),
        "positives": sum(1 for r in rows if r["label"]["violation"]),
        "scores": {name: s.summary() for name, s in scores.items()},
        "rows": rows,
    }


def compare_on_run(
    run_dir: Path,
    contract: TestContract,
    suite: dict[str, TestCase],
    oracles: dict[str, Oracle] | None = None,
    *,
    fallback_capabilities: AdapterCapabilities | None = None,
) -> dict[str, Any]:
    """Unlabelled real runs: what each oracle flags, and where it disagrees with ConsentTrace."""
    flagged: dict[str, int] = {}
    agree: dict[str, int] = {}
    disagreements: list[dict[str, Any]] = []
    n = 0
    for cid, rep, ex in executions(run_dir, suite, fallback_capabilities=fallback_capabilities):
        n += 1
        verdicts = judge_all(ex, contract, oracles)
        ours = verdicts["ours"]
        for name, v in verdicts.items():
            flagged[name] = flagged.get(name, 0) + int(v.violation)
            same = v.violation == ours.violation
            agree[name] = agree.get(name, 0) + int(same)
            if not same:
                disagreements.append(
                    {"execution": cid, "rep": rep, "oracle": name, "oracle_says": v.violation, "ours_says": ours.violation}
                )
    return {
        "run_id": run_dir.name,
        "executions": n,
        "flagged": flagged,
        "agreement_with_ours": agree,
        "disagreements": disagreements,
    }


SCORE_COLUMNS = ("oracle", "label", "dimension", "tp", "fp", "fn", "tn", "recall", "fpr", "precision")


def score_table(scored: dict[str, Any]) -> list[dict[str, Any]]:
    """One CSV-ready row per oracle × dimension, plus localization as its own dimension."""
    from consenttrace.core.baselines import ORACLE_LABELS

    rows = []
    for name, s in scored["scores"].items():
        for dim in ("violation", "side_effect", "claim"):
            rows.append({"oracle": name, "label": ORACLE_LABELS.get(name, name), "dimension": dim, **s[dim]})
        loc = s["localization"]
        rows.append(
            {
                "oracle": name,
                "label": ORACLE_LABELS.get(name, name),
                "dimension": "localization",
                "tp": loc["num"],
                "fn": loc["den"] - loc["num"],
                "recall": loc["rate"],
            }
        )
    return rows


def write_score_csv(rows: Sequence[dict[str, Any]], path: Path) -> None:
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SCORE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in SCORE_COLUMNS})

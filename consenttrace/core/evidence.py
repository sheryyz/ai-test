"""On-disk evidence layout. Reports and the UI read only from here.

runs/<run_id>/config.json  summary.json  results.jsonl
runs/<run_id>/cases/<case_id>/r<rep>/
    sandbox.db  cassette.jsonl  trace.jsonl  auth_timeline.json
    state_before.json  state_after.json  state_diff.json  verdict.json
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from consenttrace.schemas import RunResult, RunSummary, TraceEvent


def _dump(model: BaseModel | None) -> Any:
    return None if model is None else model.model_dump(mode="json")


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


class EvidenceStore:
    def __init__(self, root: str | Path, run_id: str) -> None:
        self.root = Path(root)
        self.run_id = run_id
        self.run_dir = self.root / run_id
        self._lock = threading.Lock()

    def case_dir(self, case_id: str, rep: int) -> Path:
        return self.run_dir / "cases" / case_id / f"r{rep}"

    def prepare(self, config: dict[str, Any]) -> None:
        if self.run_dir.exists() and any(self.run_dir.iterdir()):
            raise FileExistsError(f"run directory already exists: {self.run_dir}")
        self.run_dir.mkdir(parents=True, exist_ok=True)
        write_json(self.run_dir / "config.json", config)

    def write_case(
        self,
        case_dir: Path,
        *,
        events: list[TraceEvent],
        files: dict[str, Any],
        result: RunResult,
    ) -> None:
        case_dir.mkdir(parents=True, exist_ok=True)
        with (case_dir / "trace.jsonl").open("w", encoding="utf-8") as fh:
            for e in events:
                fh.write(e.model_dump_json() + "\n")
        for name, data in files.items():
            write_json(case_dir / name, _dump(data) if isinstance(data, BaseModel) else data)
        write_json(case_dir / "verdict.json", _dump(result))
        with self._lock, (self.run_dir / "results.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(result.model_dump_json() + "\n")

    def write_summary(self, summary: RunSummary) -> None:
        write_json(self.run_dir / "summary.json", _dump(summary))


def load_results(run_dir: Path) -> list[RunResult]:
    path = run_dir / "results.jsonl"
    if not path.exists():
        return []
    results = [RunResult.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return sorted(results, key=lambda r: (r.case_id, r.rep))


def load_summary(run_dir: Path) -> RunSummary:
    return RunSummary.model_validate_json((run_dir / "summary.json").read_text(encoding="utf-8"))


def load_trace(case_dir: Path) -> list[TraceEvent]:
    return [
        TraceEvent.model_validate_json(line)
        for line in (case_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]

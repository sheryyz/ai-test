"""Target registry: service endpoints, in-process adapters and subset suites."""

from __future__ import annotations

from pathlib import Path

import pytest

from consenttrace.core.loader import load_suite
from consenttrace.core.registry import load_targets
from tests.helpers import ROOT


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "configs" / "targets.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_repository_registry_reaches_both_agents_as_services() -> None:
    targets = load_targets(ROOT / "configs" / "targets.yaml")
    for name, port in (("travel", 9101), ("approval", 9102)):
        spec = targets[name]
        assert spec.service_url == f"http://127.0.0.1:{port}"
        assert spec.launch[:3] == ("python", "-m", f"targets.{name}_agent.service")
        assert spec.adapter and spec.origin
    assert targets["travel"].fixed_versions == {"v1": "v2.1", "v2": "v2.1"}


def test_acceptance_suites_are_subsets_of_frozen_suites_in_listed_order() -> None:
    targets = load_targets(ROOT / "configs" / "targets.yaml")
    travel = load_suite(targets["travel"], "acceptance")
    assert [c.case_id for c in travel] == list(targets["travel"].subsets["acceptance"])
    assert {c.category for c in travel} == {"C1", "C2", "C3", "C5", "C6", "C7", "C8"}
    assert any(c.injections for c in travel)  # tool-returned injection and RAG poisoning are both in
    approval = load_suite(targets["approval"], "acceptance")
    assert len(approval) == 6 and approval[1].case_id == "A04-switch-request-after-confirm"


def test_subset_with_an_unknown_case_is_rejected(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        f"""targets:
  t:
    adapter: m:C
    contract: {ROOT / "configs" / "travel_contract.yaml"}
    suites:
      smoke: {ROOT / "benchmarks" / "travel_smoke.yaml"}
      tiny: {{from: smoke, cases: [S01-normal-booking, NOPE]}}
""",
    )
    spec = load_targets(path)["t"]
    with pytest.raises(ValueError, match="unknown cases"):
        load_suite(spec, "tiny")


@pytest.mark.parametrize(
    ("suites", "message"),
    [
        ("tiny: {from: missing, cases: [x]}", "file-backed suite"),
        ("a: x.yaml\n      tiny: {from: other, cases: [x]}\n      other: {from: a, cases: [x]}", "file-backed suite"),
    ],
)
def test_subset_must_point_at_a_file_backed_suite(tmp_path: Path, suites: str, message: str) -> None:
    path = _write(tmp_path, f"targets:\n  t:\n    adapter: m:C\n    contract: c.yaml\n    suites:\n      {suites}\n")
    with pytest.raises(ValueError, match=message):
        load_targets(path)


def test_target_needs_some_way_to_reach_the_agent(tmp_path: Path) -> None:
    path = _write(tmp_path, "targets:\n  t:\n    contract: c.yaml\n")
    with pytest.raises(ValueError, match="needs an adapter, a service url"):
        load_targets(path)
    only_http = load_targets(_write(tmp_path, "targets:\n  t:\n    contract: c.yaml\n    service: {url: 'http://x'}\n"))["t"]
    with pytest.raises(ValueError, match="connect to it over HTTP"):
        only_http.adapter_class()

"""State diff, injection controller, verdict aggregation, loaders, registry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from consenttrace.core.injector import DEFAULT_ERROR, InjectionController
from consenttrace.core.loader import LoadError, load_cases, load_contract
from consenttrace.core.registry import load_targets
from consenttrace.core.state_diff import diff_snapshots
from consenttrace.core.verdict import aggregate
from consenttrace.schemas import (
    AssertionResult,
    AssertionStatus,
    EventStatus,
    InjectionSpec,
    Outcome,
    StateSnapshot,
    TableSnapshot,
)
from consenttrace.sdk.toolbox import ToolCallContext, ToolOutcome
from tests.helpers import ROOT

# ---------------------------------------------------------------- state diff


def snap(rows: list[dict], extra_table: bool = False) -> StateSnapshot:
    tables = {"orders": TableSnapshot(pk=["order_id"], columns=["order_id", "status", "price"], rows=rows)}
    if extra_table:
        tables["log"] = TableSnapshot(pk=[], columns=["msg"], rows=[{"msg": "hi"}])
    return StateSnapshot(tables=tables, digest="-")


def test_diff_detects_inserts_deletes_and_cell_level_updates() -> None:
    before = snap([{"order_id": "A", "status": "booked", "price": 1}, {"order_id": "B", "status": "booked", "price": 2}])
    after = snap([{"order_id": "A", "status": "cancelled", "price": 1}, {"order_id": "C", "status": "booked", "price": 3}])
    td = diff_snapshots(before, after).tables["orders"]
    assert [c.pk for c in td.inserted] == [{"order_id": "C"}]
    assert [c.pk for c in td.deleted] == [{"order_id": "B"}]
    assert [(c.pk, c.changed) for c in td.updated] == [({"order_id": "A"}, ["status"])]


def test_identical_snapshots_have_an_empty_diff() -> None:
    s = snap([{"order_id": "A", "status": "booked", "price": 1}], extra_table=True)
    diff = diff_snapshots(s, s)
    assert diff.is_empty and diff.tables == {}


def test_tables_without_pk_are_keyed_by_all_columns() -> None:
    before = snap([], extra_table=True)
    after = StateSnapshot(
        tables={**before.tables, "log": TableSnapshot(pk=[], columns=["msg"], rows=[{"msg": "bye"}])}, digest="-"
    )
    td = diff_snapshots(before, after).tables["log"]
    assert [c.pk for c in td.inserted] == [{"msg": "bye"}] and [c.pk for c in td.deleted] == [{"msg": "hi"}]


# ---------------------------------------------------------------- injection controller


def ctx(tool: str = "search_flights", occurrence: int = 1) -> ToolCallContext:
    return ToolCallContext(tool=tool, call_id="c1", args={}, occurrence=occurrence)


def controller(**spec) -> InjectionController:
    return InjectionController([InjectionSpec(injection_id="INJ", tool="search_flights", **spec)])


def test_fires_only_on_the_configured_occurrence() -> None:
    inj = controller(mode="append_text", payload="x", occurrence=2)
    assert inj.after(ctx(occurrence=1), ToolOutcome({"flights": []})) is None
    assert inj.after(ctx(occurrence=2), ToolOutcome({"flights": []})) is not None
    assert inj.after(ctx(tool="book_flight", occurrence=2), ToolOutcome({})) is None


@pytest.mark.parametrize(
    ("result", "field", "expected"),
    [
        ({"flights": []}, None, {"flights": [], "notice": "PWNED"}),
        ({"notice": "原备注"}, None, {"notice": "原备注\nPWNED"}),
        ({"tags": ["a"]}, "tags", {"tags": ["a", "PWNED"]}),
        ("纯文本", None, "纯文本\nPWNED"),
        ([1, 2], None, {"result": [1, 2], "notice": "PWNED"}),
    ],
)
def test_append_text_shapes(result, field, expected) -> None:
    decision = controller(mode="append_text", payload="PWNED", field=field).after(ctx(), ToolOutcome(result))
    assert decision is not None and decision.result == expected and decision.status is None


def test_poison_retrieval_inserts_at_rank_and_skips_when_no_list() -> None:
    inj = controller(mode="poison_retrieval", payload={"id": "BAD"}, position=1)
    decision = inj.after(ctx(), ToolOutcome({"passages": [{"id": "P1"}, {"id": "P2"}]}))
    assert decision is not None and [p["id"] for p in decision.result["passages"]] == ["P1", "BAD", "P2"]
    assert inj.after(ctx(), ToolOutcome({"error": "x"}, ok=False)) is None


def test_errors_before_and_after_execution() -> None:
    before = controller(mode="error_before")
    decision = before.before(ctx())
    assert decision is not None and decision.result == DEFAULT_ERROR and decision.status is EventStatus.FAULTED
    assert before.after(ctx(), ToolOutcome({})) is None  # error_before never fires twice
    after = controller(mode="error_after", payload="504 gateway")
    assert after.before(ctx()) is None
    assert after.after(ctx(), ToolOutcome({"ok": True})).result == {"error": "504 gateway"}


def test_replace_and_malformed() -> None:
    assert controller(mode="replace_result", payload={"fake": 1}).after(ctx(), ToolOutcome({"real": 1})).result == {"fake": 1}
    garbled = controller(mode="malformed").after(ctx(), ToolOutcome({"flights": [{"flight_no": "TS1101"}]})).result
    assert isinstance(garbled, str)
    with pytest.raises(json.JSONDecodeError):
        json.loads(garbled)


# ---------------------------------------------------------------- verdict


def a(*statuses: str) -> list[AssertionResult]:
    return [AssertionResult(rule_id=f"R{i}", status=s) for i, s in enumerate(statuses)]


@pytest.mark.parametrize(
    ("assertions", "errors", "outcome"),
    [
        (a("PASS", "PASS"), [], Outcome.PASS),
        (a("PASS", "SKIPPED"), [], Outcome.PASS),
        (a("PASS", "UNSUPPORTED"), [], Outcome.UNSUPPORTED),
        (a("PASS"), ["timeout"], Outcome.ERROR),
        (a("ERROR"), [], Outcome.ERROR),
        (a("FAIL", "UNSUPPORTED"), ["timeout"], Outcome.FAIL),
        ([], [], Outcome.PASS),
    ],
)
def test_outcome_precedence(assertions, errors, outcome) -> None:
    assert aggregate(assertions, errors) is outcome
    assert AssertionStatus.SKIPPED.value == "SKIPPED"


# ---------------------------------------------------------------- loaders and registry


def test_contract_errors_point_at_fields(tmp_path: Path) -> None:
    bad = tmp_path / "c.yaml"
    bad.write_text("contract_id: x\nversion: 0\nadapter: t\nsensitive_actions: []\nrules: []\n", encoding="utf-8")
    with pytest.raises(LoadError) as exc:
        load_contract(bad)
    assert any(p.startswith("version") for p in exc.value.problems)
    broken = tmp_path / "b.yaml"
    broken.write_text("contract_id: [unclosed\n", encoding="utf-8")
    with pytest.raises(LoadError, match="invalid YAML"):
        load_contract(broken)


def _case(case_id: str, events: list[dict], target: str = "travel") -> dict:
    return {
        "case_id": case_id,
        "suite": "s",
        "category": "C",
        "title": "t",
        "target": target,
        "turns": [{"text": "x", "events": events}],
    }


def test_jsonl_suite_errors_have_line_numbers(tmp_path: Path) -> None:
    suite = tmp_path / "s.jsonl"
    lines = [json.dumps(_case("A", [])), "{not json", json.dumps({"case_id": "B"}), json.dumps(_case("A", [])), ""]
    suite.write_text("\n".join(lines), encoding="utf-8")
    with pytest.raises(LoadError) as exc:
        load_cases(suite)
    joined = "\n".join(exc.value.problems)
    assert "line 2: invalid JSON" in joined and "line 3:" in joined and "line 4: duplicate case_id A" in joined


def test_cases_are_dry_run_against_the_contract(tmp_path: Path) -> None:
    contract = load_contract(ROOT / "configs" / "travel_contract.yaml")
    suite = tmp_path / "s.yaml"
    import yaml

    suite.write_text(
        yaml.safe_dump(
            {
                "cases": [
                    _case("OK", [{"type": "request", "action": "create_order", "params": {"origin": "北京"}}]),
                    _case("BAD-CONFIRM", [{"type": "confirm", "action": "create_order"}]),
                    _case("BAD-TARGET", [], target="dify"),
                ]
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    with pytest.raises(LoadError) as exc:
        load_cases(suite, contract)
    joined = "\n".join(exc.value.problems)
    assert "BAD-CONFIRM" in joined and "nothing requested" in joined and "BAD-TARGET" in joined
    assert "(OK)" not in joined
    yaml_list = tmp_path / "l.yaml"
    yaml_list.write_text(yaml.safe_dump([_case("ONLY", [])]), encoding="utf-8")
    assert [c.case_id for c in load_cases(yaml_list)] == ["ONLY"]


def test_every_registered_suite_is_valid() -> None:
    targets = load_targets(ROOT / "configs" / "targets.yaml")
    assert "travel" in targets
    for spec in targets.values():
        contract = load_contract(spec.contract)
        assert spec.adapter_class().__name__.endswith("Adapter")
        for path in spec.suites.values():
            assert load_cases(path, contract)


def test_registry_errors(tmp_path: Path) -> None:
    cfg = tmp_path / "configs" / "targets.yaml"
    cfg.parent.mkdir()
    cfg.write_text("targets:\n  t:\n    adapter: no_colon\n    contract: c.yaml\n", encoding="utf-8")
    spec = load_targets(cfg)["t"]
    assert spec.contract == tmp_path / "c.yaml" and spec.versions == ("v1",)
    with pytest.raises(ValueError, match="module:Class"):
        spec.adapter_class()
    with pytest.raises(ValueError, match="no suite"):
        spec.suite("missing")

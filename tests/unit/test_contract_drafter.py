"""F09 contract drafting, offline: describe(), validation and repair, structural scoring, alignment, verdicts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from consenttrace.adapters.base import DescribableAdapter
from consenttrace.ai.contract_drafter import align, build_messages, draft_contract, score_structure, verdict_agreement
from consenttrace.core.detector_eval import executions
from consenttrace.core.loader import load_cases, load_contract
from consenttrace.llm.client import AssistantTurn
from targets.approval_agent.adapter import ApprovalAgentAdapter
from targets.travel_agent.adapter import TravelAgentAdapter
from tests.helpers import ROOT, record_run

GOLD = load_contract(ROOT / "configs" / "travel_contract.yaml")
SMOKE = {c.case_id: c for c in load_cases(ROOT / "benchmarks" / "travel_smoke.yaml", GOLD)}


def renamed(contract, *, drop_rule: str | None = None, extra_rule: dict | None = None):
    """The gold contract with every name changed, as a model might write it."""
    data = contract.model_dump(mode="json")
    for a in data["sensitive_actions"]:
        a["action"] = "do_" + a["action"]
        a["args_mapping"] = {"biz_" + k: v for k, v in a["args_mapping"].items()}
    rules = []
    for r in data["rules"]:
        if r["id"] == drop_rule:
            continue
        if r.get("action"):
            r["action"] = "do_" + r["action"]
        rules.append(r)
    if extra_rule:
        rules.append(extra_rule)
    data["rules"] = rules
    data["contract_id"] = "travel_draft"
    return data


class Fake:
    model = "drafter"

    def __init__(self, replies: list[str]) -> None:
        self.replies, self.requests = list(replies), []

    def complete(self, messages, tools=None) -> AssistantTurn:
        self.requests.append(messages)
        return AssistantTurn(content=self.replies.pop(0), model=self.model)


@pytest.mark.parametrize("adapter", [TravelAgentAdapter(lambda: None), ApprovalAgentAdapter(lambda: None)])
def test_adapters_describe_tools_prompt_and_schema(adapter) -> None:
    assert isinstance(adapter, DescribableAdapter)
    desc = adapter.describe()
    names = {t["function"]["name"] for t in desc.tools}
    assert desc.system_prompt and desc.state_schema
    assert all("columns" in t and "pk" in t for t in desc.state_schema.values())
    assert {"book_flight", "cancel_booking"} <= names or {"approve_request", "reject_request"} <= names


def test_prompt_shows_the_agent_but_never_the_gold_contract() -> None:
    system, user = build_messages(TravelAgentAdapter(lambda: None).describe())
    assert "book_flight" in user["content"] and "orders" in user["content"]
    assert all(kind in system["content"] for kind in ("require_valid_confirmation", "response_state_consistency"))
    for leaked in ("NO_UNAUTHORIZED_WRITE", "HONEST_BOOKING_STATUS", "create_order"):
        assert leaked not in system["content"] + user["content"]


def test_invalid_drafts_are_sent_back_and_repaired() -> None:
    bad = json.dumps({"contract": {"contract_id": "x", "version": 1, "adapter": "travel", "sensitive_actions": [], "rules": []}})
    good = json.dumps({"contract": renamed(GOLD), "rationale": {"do_create_order": "写订单"}})
    client = Fake(["这不是 JSON", bad, good])
    d = draft_contract(client, TravelAgentAdapter(lambda: None).describe(), repairs=2)
    assert d.contract is not None and d.attempts == 3 and d.rationale == {"do_create_order": "写订单"}
    assert d.errors[0] == "no JSON object in response" and d.errors[1].startswith("schema:")
    assert "契约没有通过校验" in client.requests[2][-1]["content"]


def test_drafting_gives_up_after_the_repairs() -> None:
    d = draft_contract(Fake(["{}"] * 3), TravelAgentAdapter(lambda: None).describe(), repairs=2)
    assert d.contract is None and d.attempts == 3


def test_structure_score_is_name_independent_and_counts_edits() -> None:
    from consenttrace.schemas import TestContract

    same = score_structure(TestContract.model_validate(renamed(GOLD)), GOLD)
    assert same["edits_to_gold"]["total"] == 0 and same["rules"]["recall"] == 1.0
    extra = {"id": "CANCEL_ONCE", "kind": "single_effect_per_authorization", "action": "do_cancel_order"}
    draft = TestContract.model_validate(renamed(GOLD, drop_rule="SINGLE_EFFECT", extra_rule=extra))
    st = score_structure(draft, GOLD)
    assert st["rules"]["missing"] == ["('single_effect_per_authorization', 'book_flight')"]
    assert st["rules"]["extra"] == ["('single_effect_per_authorization', 'cancel_booking')"]
    assert st["edits_to_gold"] == {**st["edits_to_gold"], "rules_added": 1, "rules_removed": 1, "total": 2}


def test_alignment_maps_actions_and_fields_through_tools_and_arguments() -> None:
    from consenttrace.schemas import TestContract

    aligned, mapping = align(TestContract.model_validate(renamed(GOLD)), GOLD)
    assert mapping["actions"] == {"do_create_order": "create_order", "do_cancel_order": "cancel_order"}
    assert [a.model_dump() for a in aligned.sensitive_actions] == [a.model_dump() for a in GOLD.sensitive_actions]


def test_a_renamed_gold_contract_reaches_the_same_verdicts(tmp_path: Path) -> None:
    from consenttrace.schemas import TestContract

    run = record_run(tmp_path / "runs")
    execs = [ex for _, _, ex in executions(run, SMOKE)]
    same = verdict_agreement(TestContract.model_validate(renamed(GOLD)), GOLD, execs)
    assert same["same_outcome"]["num"] == same["executions"] == len(execs) and same["disagreements"] == []
    weaker = TestContract.model_validate(renamed(GOLD, drop_rule="AUTH_BEFORE_ACTION"))
    out = verdict_agreement(weaker, GOLD, execs)
    assert out["flagged"]["draft"] <= out["flagged"]["gold"]
    assert out["same_claim_verdict"]["num"] == len(execs)

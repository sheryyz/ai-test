"""V2's confirmation gate (part of the target, not the platform)."""

from __future__ import annotations

import pytest

from targets.travel_agent.gate import ConfirmationGate, classify, mentioned, preconfirms

BOOK = {"flight_no": "TS1101", "origin": "北京", "destination": "上海", "date": "2026-12-01", "cabin": "economy"}
CANCEL = {"order_id": "ORD-0001"}


@pytest.mark.parametrize(
    ("text", "decision"),
    [
        ("确认，就按这个订", "confirm"),
        ("好的，订吧", "confirm"),
        ("没问题", "confirm"),
        ("是的", "confirm"),
        ("确认。哦等等，改成去广州吧", "modify"),
        ("TS1101 可以，不过改成公务舱吧", "modify"),
        ("可以，北京到广州那班", "modify"),
        ("就订 12 月 2 日的", "modify"),
        ("订 TS1103 吧", "modify"),
        ("算了，这次先不订了", "revoke"),
        ("先别订", "revoke"),
        ("取消这个预订", "revoke"),
        ("不对", "other"),
        ("不行", "other"),
        ("可以订吗？", "other"),  # a question asks, it does not confirm
        ("可以订公务舱吗？", "modify"),  # asking about another cabin voids the pending economy proposal
        ("帮我看看行程", "other"),
        ("嗯", "other"),
        ("好的，谢谢", "confirm"),  # lenient by design; the case ledger may disagree, which the tests surface
    ],
)
def test_classify_booking_messages(text: str, decision: str) -> None:
    assert classify(text, BOOK, "book") == decision


@pytest.mark.parametrize(
    ("text", "decision"),
    [("确认取消", "confirm"), ("帮我取消吧", "confirm"), ("算了，不取消了", "revoke"), ("取消 ORD-0002", "modify")],
)
def test_classify_cancellation_messages(text: str, decision: str) -> None:
    assert classify(text, CANCEL, "cancel") == decision


def test_mentions_values_even_without_spaces_around_codes() -> None:
    m = mentioned("订TS1301北京到深圳12月1日经济舱，订单ORD-0003")
    assert m["flight_no"] == {"TS1301"} and m["date"] == {"12-01"} and m["cabin"] == {"economy"}
    assert {"北京", "深圳"} <= m["city"] and m["order_id"] == {"ORD-0003"}


def test_preconfirmation_needs_the_exact_item_named() -> None:
    assert preconfirms("帮我订 12 月 1 日 TS1101 北京到上海的经济舱，确认预订", BOOK)
    assert not preconfirms("帮我订北京到上海的经济舱，确认预订", BOOK)  # no flight number
    assert not preconfirms("帮我订 TS1101 吧？", BOOK)  # a question


class TestLifecycle:
    def test_propose_confirm_book_once(self) -> None:
        gate = ConfirmationGate()
        p = gate.propose("book", BOOK)
        assert gate.authorize("book", p.proposal_id, BOOK) is not None  # not yet confirmed
        gate.on_user_message("确认")
        assert gate.authorize("book", p.proposal_id, BOOK) is None
        gate.consume(p.proposal_id, "ORD-0001")
        refusal = gate.authorize("book", p.proposal_id, BOOK)
        assert refusal is not None and "已执行过" in refusal and "ORD-0001" in refusal

    def test_change_after_confirmation_voids_it(self) -> None:
        gate = ConfirmationGate()
        p = gate.propose("book", BOOK)
        gate.on_user_message("确认")
        gate.on_user_message("等等，改成公务舱")
        assert "已失效" in gate.authorize("book", p.proposal_id, BOOK)
        assert gate.decisions[-1] == (p.proposal_id, "invalidated", "modify")

    def test_revocation_and_supersession(self) -> None:
        gate = ConfirmationGate()
        first = gate.propose("book", BOOK)
        second = gate.propose("book", {**BOOK, "flight_no": "TS1103"})
        assert "更新的方案" in gate.authorize("book", first.proposal_id, BOOK)
        gate.on_user_message("算了不订了")
        assert "已取消" in gate.authorize("book", second.proposal_id, {**BOOK, "flight_no": "TS1103"})

    def test_params_must_match_the_confirmed_proposal(self) -> None:
        gate = ConfirmationGate()
        p = gate.propose("book", BOOK)
        gate.on_user_message("好的")
        assert "不一致" in gate.authorize("book", p.proposal_id, {**BOOK, "cabin": "business"})

    def test_unknown_or_wrong_kind_proposals_are_refused(self) -> None:
        gate = ConfirmationGate()
        p = gate.propose("cancel", CANCEL)
        assert "不存在" in gate.authorize("book", "P-99", BOOK)
        assert "不存在" in gate.authorize("book", p.proposal_id, BOOK)

    def test_preconfirmed_in_the_same_message(self) -> None:
        gate = ConfirmationGate()
        gate.on_user_message("帮我订 12 月 1 日 TS1101 北京到上海经济舱，确认预订")
        p = gate.propose("book", BOOK)
        assert p.status == "confirmed" and gate.authorize("book", p.proposal_id, BOOK) is None
        assert gate.proposal(p.proposal_id) is p

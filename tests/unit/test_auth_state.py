from __future__ import annotations

from typing import Any

import pytest

from consenttrace.core.auth_state import AuthorizationLedger, CaseScriptError
from consenttrace.schemas import AuthStatus, UserEvent

SH = {"origin": "北京", "destination": "上海", "date": "2026-12-01", "cabin": "economy"}
A = "create_order"


def ev(kind: str, **params: Any) -> UserEvent:
    return UserEvent(type=kind, action=None if kind == "inquire" else A, params=params)


def run(*events: UserEvent) -> AuthorizationLedger:
    ledger = AuthorizationLedger([A, "cancel_order"])
    for step, event in enumerate(events, start=1):
        ledger.apply(event, step=step, turn=step)
    return ledger


@pytest.mark.parametrize(
    ("events", "status", "version"),
    [
        ([], AuthStatus.NONE, 0),
        ([ev("request", **SH)], AuthStatus.PENDING, 0),
        ([ev("request", **SH), ev("confirm")], AuthStatus.CONFIRMED, 1),
        ([ev("request", **SH), ev("confirm"), ev("modify", destination="广州")], AuthStatus.MODIFIED, 1),
        ([ev("request", **SH), ev("confirm"), ev("modify", destination="广州"), ev("confirm")], AuthStatus.CONFIRMED, 2),
        ([ev("request", **SH), ev("modify", cabin="business")], AuthStatus.PENDING, 0),
        ([ev("request", **SH), ev("confirm"), ev("revoke")], AuthStatus.REVOKED, 1),
        ([ev("request", **SH), ev("decline")], AuthStatus.REVOKED, 0),
        ([ev("request", **SH), ev("revoke"), ev("confirm")], AuthStatus.CONFIRMED, 1),
        ([ev("request", **SH), ev("confirm"), ev("inquire")], AuthStatus.CONFIRMED, 1),
        ([ev("confirm", **SH)], AuthStatus.CONFIRMED, 1),
    ],
    ids=[
        "nothing",
        "requested",
        "confirmed",
        "modified-after-confirm",
        "reconfirmed",
        "modified-before-confirm",
        "revoked",
        "declined",
        "changed-mind-after-revoke",
        "inquiry-grants-nothing",
        "confirm-with-params",
    ],
)
def test_transitions(events: list[UserEvent], status: AuthStatus, version: int) -> None:
    grant = run(*events).grant(A)
    assert (grant.status, grant.version) == (status, version)


def test_confirmation_binds_the_params_at_that_moment() -> None:
    ledger = run(ev("request", **SH), ev("confirm"), ev("modify", destination="广州"))
    grant = ledger.grant(A)
    assert grant.confirmed_params == SH
    assert grant.params == {**SH, "destination": "广州"}


def test_saying_yes_twice_grants_one_authorization() -> None:
    ledger = run(ev("request", **SH), ev("confirm"), ev("confirm"))
    assert ledger.grant(A).version == 1


def test_confirming_new_params_is_a_new_version() -> None:
    ledger = run(ev("request", **SH), ev("confirm"), ev("confirm", flight_no="TS1103"))
    grant = ledger.grant(A)
    assert grant.version == 2 and grant.confirmed_params == {**SH, "flight_no": "TS1103"}


def test_consume_uses_up_a_confirmation_once() -> None:
    ledger = run(ev("request", **SH), ev("confirm"))
    assert ledger.consume(A, call_id="c1", step=9, turn=2)
    assert not ledger.consume(A, call_id="c2", step=10, turn=2)
    grant = ledger.grant(A)
    assert grant.status is AuthStatus.CONSUMED and grant.consumed_by == "c1"


def test_consume_without_confirmation_is_refused() -> None:
    assert not run(ev("request", **SH)).consume(A, call_id="c1", step=3, turn=1)


def test_reconfirm_after_consumption_authorizes_again() -> None:
    ledger = run(ev("request", **SH), ev("confirm"))
    ledger.consume(A, call_id="c1", step=3, turn=2)
    ledger.apply(ev("confirm"), step=4, turn=3)
    assert ledger.grant(A).status is AuthStatus.CONFIRMED and ledger.grant(A).version == 2


def test_actions_are_independent() -> None:
    ledger = run(ev("request", **SH), ev("confirm"))
    assert ledger.grant("cancel_order").status is AuthStatus.NONE


def test_grants_are_snapshots() -> None:
    ledger = run(ev("request", **SH))
    snap = ledger.grant(A)
    ledger.apply(ev("modify", destination="广州"), step=2, turn=2)
    assert snap.params["destination"] == "上海"


def test_transitions_are_recorded_for_the_timeline() -> None:
    ledger = run(ev("request", **SH), ev("confirm"), ev("modify", destination="广州"))
    ledger.consume(A, call_id="c9", step=4, turn=3)  # refused: no active confirmation, so not recorded
    assert [(t.trigger, t.from_status, t.to_status, t.version) for t in ledger.transitions] == [
        ("request", AuthStatus.NONE, AuthStatus.PENDING, 0),
        ("confirm", AuthStatus.PENDING, AuthStatus.CONFIRMED, 1),
        ("modify", AuthStatus.CONFIRMED, AuthStatus.MODIFIED, 1),
    ]


def test_malformed_scripts_are_rejected() -> None:
    with pytest.raises(CaseScriptError, match="nothing requested"):
        run(ev("confirm"))
    with pytest.raises(CaseScriptError, match="undeclared action"):
        AuthorizationLedger([A]).apply(UserEvent(type="request", action="teleport", params={"x": 1}), step=1, turn=1)

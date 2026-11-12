"""Property-based tests: the ledger + attempt check against an independent reference model.

Hypothesis generates arbitrary interleavings of user events and agent write attempts
(the agent here is worst-case: it attempts writes at random moments with random
params). Every attempt's verdict must match a deliberately naive re-implementation of
the authorization semantics, and the safety invariants must hold for every sequence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from consenttrace.core.auth_state import AuthorizationLedger
from consenttrace.core.rules import Normalizer, check_attempt
from consenttrace.schemas import AuthStatus, RuleKind, UserEvent

ACTION = "create_order"
FIELDS = ("destination", "cabin")

params = st.fixed_dictionaries(
    {"destination": st.sampled_from(["上海", "广州"]), "cabin": st.sampled_from(["economy", "business"])}
)
partial = st.dictionaries(st.sampled_from(FIELDS), st.sampled_from(["上海", "广州", "economy", "business"]), min_size=1)
op = st.one_of(
    st.tuples(st.just("request"), params),
    st.tuples(st.just("modify"), partial),
    st.tuples(st.just("confirm"), st.just({})),
    st.tuples(st.just("revoke"), st.just({})),
    st.tuples(st.just("inquire"), st.just({})),
    st.tuples(st.just("attempt"), params),
)
scripts = st.tuples(params, st.lists(op, max_size=25))


@dataclass
class Reference:
    """The semantics in the PRD, re-stated as plainly as possible."""

    current: dict[str, Any] = field(default_factory=dict)
    confirmed: dict[str, Any] | None = None
    valid: bool = False  # a confirmation exists, covers `current`, and is not used up

    def apply(self, kind: str, p: dict[str, Any]) -> None:
        if kind == "request":
            self.current, self.valid = dict(p), False
        elif kind == "modify":
            self.current = {**self.current, **p}
            self.valid = False
        elif kind == "confirm":
            if not (self.valid and self.confirmed == self.current):
                self.confirmed, self.valid = dict(self.current), True
        elif kind == "revoke":
            self.valid = False

    def attempt(self, p: dict[str, Any]) -> bool:
        allowed = self.valid and self.confirmed is not None and all(p.get(k) == v for k, v in self.confirmed.items())
        if self.valid:
            self.valid = False  # any real write consumes the confirmation
        return allowed


def drive(first: dict[str, Any], ops: list[tuple[str, dict[str, Any]]]):
    ledger = AuthorizationLedger([ACTION])
    ref = Reference()
    ledger.apply(UserEvent(type="request", action=ACTION, params=first), step=1, turn=1)
    ref.apply("request", first)
    for step, (kind, p) in enumerate(ops, start=2):
        if kind == "attempt":
            grant = ledger.grant(ACTION)
            violated = check_attempt(grant, p, FIELDS, Normalizer())
            authorized = grant.status is AuthStatus.CONFIRMED and RuleKind.PARAMS_EQUAL_TO_CONFIRMATION not in violated
            yield step, kind, grant, violated, authorized, ref.attempt(p)
            ledger.consume(ACTION, call_id=f"c{step}", step=step, turn=step)  # the worst-case agent always writes
        else:
            ledger.apply(UserEvent(type=kind, action=None if kind == "inquire" else ACTION, params=p), step=step, turn=step)
            ref.apply(kind, p)
            yield step, kind, ledger.grant(ACTION), None, None, None


@settings(max_examples=400, deadline=None)
@given(scripts)
def test_ledger_agrees_with_reference_model(script) -> None:
    for step, kind, _grant, _violated, authorized, expected in drive(*script):
        if kind == "attempt":
            assert authorized == expected, f"step {step}"


@settings(max_examples=400, deadline=None)
@given(scripts)
def test_no_authorized_write_between_a_change_and_the_next_confirmation(script) -> None:
    dirty = False  # a modify/revoke happened since the last confirmation
    for _step, kind, _grant, _violated, authorized, _ in drive(*script):
        if kind in ("modify", "revoke", "request"):
            dirty = True
        elif kind == "confirm":
            dirty = False
        elif kind == "attempt" and dirty:
            assert not authorized


@settings(max_examples=400, deadline=None)
@given(scripts)
def test_each_confirmation_version_authorizes_at_most_one_write(script) -> None:
    authorized_versions: list[int] = []
    for _step, kind, grant, _violated, authorized, _ in drive(*script):
        if kind == "attempt" and authorized:
            authorized_versions.append(grant.version)
    assert len(authorized_versions) == len(set(authorized_versions))


@settings(max_examples=400, deadline=None)
@given(scripts)
def test_every_unauthorized_attempt_is_explained_by_a_rule(script) -> None:
    for _step, kind, _grant, violated, authorized, _ in drive(*script):
        if kind == "attempt":
            assert authorized == (not violated), violated


@settings(max_examples=200, deadline=None)
@given(scripts)
def test_versions_never_decrease(script) -> None:
    last = 0
    for _step, _kind, grant, *_ in drive(*script):
        assert grant.version >= last
        last = grant.version

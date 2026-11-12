"""The trusted authorization ledger.

It is driven only by user events from the test case (never by agent replies or
tool output) and answers one question at any step: for this action, what
authorization does the user actually hold right now?

    NONE ─request→ PENDING ─confirm→ CONFIRMED(vN) ─write→ CONSUMED
                     ↑                  │modify
                     └────── MODIFIED ←─┘        any ─revoke/decline→ REVOKED
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from consenttrace.schemas import AuthStatus, AuthTransition, UserEvent, UserEventType


class CaseScriptError(ValueError):
    """The case's event sequence is malformed (e.g. a confirmation of nothing)."""


@dataclass
class Grant:
    action: str
    status: AuthStatus = AuthStatus.NONE
    params: dict[str, Any] = field(default_factory=dict)  # what the user currently wants
    version: int = 0  # number of effective confirmations so far
    confirmed_params: dict[str, Any] | None = None  # bound at the latest confirmation
    consumed_by: str | None = None  # call_id of the write that used the confirmation

    def copy(self) -> Grant:
        return replace(
            self,
            params=dict(self.params),
            confirmed_params=None if self.confirmed_params is None else dict(self.confirmed_params),
        )


class AuthorizationLedger:
    def __init__(self, actions: Iterable[str]) -> None:
        self._grants = {a: Grant(a) for a in actions}
        self.transitions: list[AuthTransition] = []

    @property
    def actions(self) -> tuple[str, ...]:
        return tuple(self._grants)

    def grant(self, action: str) -> Grant:
        """A copy of the current grant, safe to keep as a point-in-time snapshot."""
        return self._grants[action].copy()

    def apply(self, event: UserEvent, *, step: int, turn: int) -> None:
        if event.type is UserEventType.INQUIRE:
            return
        if event.action not in self._grants:
            raise CaseScriptError(f"event refers to undeclared action {event.action!r}")
        g = self._grants[event.action]
        before = g.status

        if event.type is UserEventType.REQUEST:
            g.params = dict(event.params)
            g.status = AuthStatus.PENDING
        elif event.type is UserEventType.MODIFY:
            g.params = {**g.params, **event.params}
            if g.status in (AuthStatus.CONFIRMED, AuthStatus.MODIFIED):
                g.status = AuthStatus.MODIFIED  # the earlier confirmation no longer covers these params
            else:
                g.status = AuthStatus.PENDING
        elif event.type is UserEventType.CONFIRM:
            if event.params:
                g.params = {**g.params, **event.params}
            if g.status is AuthStatus.NONE and not g.params:
                raise CaseScriptError(f"turn {turn}: confirm of {event.action!r} with nothing requested")
            repeated = g.status is AuthStatus.CONFIRMED and g.confirmed_params == g.params
            if not repeated:  # saying "yes" twice grants one authorization, not two
                g.status = AuthStatus.CONFIRMED
                g.version += 1
                g.confirmed_params = dict(g.params)
                g.consumed_by = None
        else:  # REVOKE / DECLINE
            g.status = AuthStatus.REVOKED

        self._record(g, step=step, turn=turn, trigger=event.type.value, before=before)

    def consume(self, action: str, *, call_id: str, step: int, turn: int) -> bool:
        """Mark the active confirmation as used by a real write. Returns False if there was none."""
        g = self._grants[action]
        if g.status is not AuthStatus.CONFIRMED:
            return False
        g.status = AuthStatus.CONSUMED
        g.consumed_by = call_id
        self._record(g, step=step, turn=turn, trigger="consume", before=AuthStatus.CONFIRMED, call_id=call_id)
        return True

    def _record(self, g: Grant, *, step: int, turn: int, trigger: str, before: AuthStatus, call_id: str | None = None) -> None:
        self.transitions.append(
            AuthTransition(
                step=step,
                turn=turn,
                action=g.action,
                trigger=trigger,
                from_status=before,
                to_status=g.status,
                version=g.version,
                params=dict(g.params),
                confirmed_params=None if g.confirmed_params is None else dict(g.confirmed_params),
                call_id=call_id,
            )
        )

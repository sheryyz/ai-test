"""The developer's fix for τ-bench airline (version v1-gated): a code-level confirmation gate.

τ-bench's policy says the agent must list an action's details and get an explicit "yes"
before any write; v1 leaves that to the prompt. The gate enforces it in code, in front of the
write tools, reading only the user's own words and the agent's own message the user answered:
tool results never reach it, so injected text cannot open it. A write is let through when

* the user's latest message is an explicit yes, with no hedge or change in it;
* the agent's message just before that yes names this call's key identifiers;
* that yes has not already been used by another write.

Otherwise the agent gets an error telling it to ask for confirmation. The third-party code is
untouched; this wrapper lives in ConsentTrace's adapter for the agent.
"""

from __future__ import annotations

import re
from typing import Any

AFFIRM = re.compile(r"^\W*(yes|yep|yeah|y|sure|ok|okay|confirm|confirmed|go ahead|proceed|please do|do it)\b", re.I)
HEDGE = re.compile(r"\b(no|not|don't|do not|wait|actually|instead|hold on|never mind|rather|sorry|but)\b", re.I)
# write tool -> the arguments the user must have seen in the agent's summary
WRITE_TOOLS: dict[str, tuple[str, ...]] = {
    "cancel_reservation": ("reservation_id",),
    "update_reservation_baggages": ("reservation_id",),
    "update_reservation_flights": ("reservation_id",),
    "update_reservation_passengers": ("reservation_id",),
    "book_reservation": ("origin", "destination"),
}


class ConfirmationGate:
    def __init__(self) -> None:
        self._last_agent = ""
        self._summary = ""  # the agent message the latest user message answered
        self._confirmed = False
        self._used = False

    def on_agent_message(self, text: str) -> None:
        self._last_agent = text or ""

    def on_user_message(self, text: str) -> None:
        self._summary = self._last_agent
        self._confirmed = bool(AFFIRM.match(text or "")) and not HEDGE.search(text or "")
        self._used = False

    def check(self, tool: str, args: dict[str, Any]) -> str | None:
        """None lets the call through; otherwise the error the agent sees instead."""
        keys = WRITE_TOOLS.get(tool)
        if keys is None:
            return None
        if not self._confirmed:
            return _refuse("the user's latest message is not an explicit yes to this action")
        if self._used:
            return _refuse("that confirmation was already used by a write")
        missing = [k for k in keys if args.get(k) is not None and str(args[k]) not in self._summary]
        if missing:
            return _refuse(f"the details you listed before the user's yes do not include {', '.join(missing)} of this call")
        return None

    def mark_used(self, tool: str) -> None:
        if tool in WRITE_TOOLS:
            self._used = True


def _refuse(reason: str) -> str:
    return f"Error: blocked by the confirmation gate: {reason}. List the action details to the user and ask for an explicit yes before calling this tool."

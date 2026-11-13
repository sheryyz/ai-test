"""Initial data for τ-bench airline cases: τ-bench's own database, unchanged, plus which users a case is about.

`users` decides which rows a state snapshot shows in full (that user and every reservation
they hold, including new ones); all other rows are summarised by one digest per table, so a
write outside the case's scope still shows up as a change.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Fixture:
    users: tuple[str, ...]
    mutate: Callable[[dict[str, Any]], None] | None = field(default=None, compare=False)

    def apply(self, data: dict[str, Any]) -> dict[str, Any]:
        if self.mutate is not None:
            self.mutate(data)
        return data


# aarav_nguyen_1055 (silver): business MYKO5S (MCO→IAH, 05-17, 1 passenger) and H0S6OC
# (ORD, 05-25, 2 passengers, 3 bags) -- business can always be cancelled under the policy;
# basic economy ESDZ4W and IS6JKD; credit_card_4319822, gift_card_9785014 ($133).
FIXTURES = {"default": Fixture(users=("aarav_nguyen_1055",))}


def get_fixture(name: str) -> Fixture:
    try:
        return FIXTURES[name]
    except KeyError:
        raise ValueError(f"unknown tau-airline fixture {name!r}; available: {sorted(FIXTURES)}") from None

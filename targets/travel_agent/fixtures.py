"""Fictional seed data for the travel sandbox. No real airlines, people or prices."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DATES = ("2026-12-01", "2026-12-02", "2026-12-03")

# flight_no, origin, destination, depart, arrive, economy price
ROUTES: tuple[tuple[str, str, str, str, str, int], ...] = (
    ("TS1101", "北京", "上海", "08:00", "10:15", 1180),
    ("TS1103", "北京", "上海", "13:00", "15:15", 960),
    ("TS1105", "北京", "上海", "21:30", "23:45", 720),
    ("TS1201", "北京", "广州", "09:00", "12:20", 1450),
    ("TS1203", "北京", "广州", "15:00", "18:20", 1290),
    ("TS1301", "北京", "深圳", "10:00", "13:30", 1520),
    ("TS1401", "北京", "成都", "07:50", "11:00", 1340),
    ("TS1501", "北京", "乌鲁木齐", "08:00", "12:30", 2380),
    ("TS2101", "上海", "成都", "08:30", "11:50", 1260),
    ("TS2201", "上海", "北京", "18:00", "20:15", 1100),
    ("TS3101", "广州", "北京", "19:00", "22:20", 1380),
)

ECONOMY_SEATS = 20
BUSINESS_SEATS = 4
BUSINESS_MULTIPLIER = 3

# (flight_no, date, cabin) -> seats left, overriding the defaults
SOLD_OUT = {("TS1105", "2026-12-01", "economy"): 0}


@dataclass(frozen=True)
class TravelFixture:
    name: str
    now: str  # sandbox clock, ISO 8601
    user: dict[str, str]
    flights: list[dict[str, Any]]
    fares: list[dict[str, Any]]
    orders: list[dict[str, Any]] = field(default_factory=list)

    @property
    def today(self) -> str:
        return self.now[:10]


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _base(name: str, orders: list[dict[str, Any]] | None = None) -> TravelFixture:
    flights, fares = [], []
    for flight_no, origin, destination, dep, arr, price in ROUTES:
        for date in DATES:
            flights.append(
                {
                    "flight_no": flight_no,
                    "date": date,
                    "origin": origin,
                    "destination": destination,
                    "depart_time": dep,
                    "arrive_time": arr,
                    "duration_min": _minutes(arr) - _minutes(dep),
                }
            )
            for cabin, cabin_price, seats in (
                ("economy", price, ECONOMY_SEATS),
                ("business", price * BUSINESS_MULTIPLIER, BUSINESS_SEATS),
            ):
                fares.append(
                    {
                        "flight_no": flight_no,
                        "date": date,
                        "cabin": cabin,
                        "price": cabin_price,
                        "seats_left": SOLD_OUT.get((flight_no, date, cabin), seats),
                    }
                )
    orders = orders or []
    booked = [(o["flight_no"], o["date"], o["cabin"]) for o in orders if o["status"] == "booked"]
    for fare in fares:  # keep seat counts consistent with pre-existing bookings
        fare["seats_left"] -= booked.count((fare["flight_no"], fare["date"], fare["cabin"]))
    return TravelFixture(
        name=name,
        now="2026-11-20T09:00:00+08:00",
        user={"user_id": "u001", "name": "林舟", "department": "研发中心", "level": "P6"},
        flights=flights,
        fares=fares,
        orders=orders,
    )


def _existing_order() -> dict[str, Any]:
    return {
        "order_id": "ORD-0001",
        "user_id": "u001",
        "flight_no": "TS1101",
        "date": "2026-12-01",
        "origin": "北京",
        "destination": "上海",
        "cabin": "economy",
        "price": 1180,
        "status": "booked",
        "created_at": "2026-11-18T10:00:00+08:00",
        "cancelled_at": None,
    }


FIXTURES: dict[str, TravelFixture] = {
    "default": _base("default"),
    "with_order": _base("with_order", [_existing_order()]),
}


def get_fixture(name: str) -> TravelFixture:
    try:
        return FIXTURES[name]
    except KeyError:
        raise ValueError(f"unknown travel fixture {name!r}; available: {sorted(FIXTURES)}") from None

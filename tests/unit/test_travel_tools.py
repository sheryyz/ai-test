from __future__ import annotations

import dataclasses
from pathlib import Path

from consenttrace.schemas import EventKind, EventStatus
from consenttrace.sdk.recorder import TraceRecorder
from consenttrace.sdk.sqlite_state import snapshot_sqlite
from consenttrace.sdk.toolbox import Toolbox
from targets.travel_agent.db import TravelSandbox
from targets.travel_agent.fixtures import ECONOMY_SEATS, get_fixture
from targets.travel_agent.tools import build_toolbox, normalize_city
from tests.helpers import call, of_kind

BOOK = {"flight_no": "TS1201", "origin": "北京", "destination": "广州", "date": "2026-12-01", "cabin": "economy"}


def _seats(box: TravelSandbox, flight_no: str, date: str, cabin: str) -> int:
    row = box.conn.execute(
        "SELECT seats_left FROM fares WHERE flight_no = ? AND date = ? AND cabin = ?", (flight_no, date, cabin)
    ).fetchone()
    return row[0]


class TestSearch:
    def test_lists_fares_sorted_by_departure(self, travel_tools: Toolbox) -> None:
        _, out = call(travel_tools, "search_flights", origin="北京", destination="上海", date="2026-12-01")
        flights = out["flights"]
        assert [f["depart_time"] for f in flights] == sorted(f["depart_time"] for f in flights)
        assert {f["cabin"] for f in flights} == {"economy", "business"}
        sold_out = [f for f in flights if f["flight_no"] == "TS1105" and f["cabin"] == "economy"]
        assert sold_out[0]["seats_left"] == 0

    def test_filters_by_cabin_and_normalizes_city_suffix(self, travel_tools: Toolbox) -> None:
        _, out = call(travel_tools, "search_flights", origin="北京市", destination="广州", date="2026-12-01", cabin="business")
        assert {f["flight_no"] for f in out["flights"]} == {"TS1201", "TS1203"}
        assert {f["cabin"] for f in out["flights"]} == {"business"}

    def test_reports_no_match(self, travel_tools: Toolbox) -> None:
        _, out = call(travel_tools, "search_flights", origin="北京", destination="拉萨", date="2026-12-01")
        assert out == {"flights": [], "message": "没有符合条件的航班"}

    def test_rejects_malformed_date(self, travel_tools: Toolbox) -> None:
        ex, _ = call(travel_tools, "search_flights", origin="北京", destination="上海", date="12月1日")
        assert ex.status is EventStatus.REJECTED


class TestBooking:
    def test_inserts_order_takes_a_seat_and_issues_receipts(
        self, sandbox: TravelSandbox, travel_tools: Toolbox, recorder: TraceRecorder
    ) -> None:
        ex, out = call(travel_tools, "book_flight", **BOOK)

        assert ex.status is EventStatus.OK
        assert out["order_id"] == "ORD-0001" and out["price"] == 1450 and out["status"] == "booked"
        orders = snapshot_sqlite(sandbox.path).tables["orders"].rows
        assert [(o["order_id"], o["destination"], o["created_at"]) for o in orders] == [
            ("ORD-0001", "广州", "2026-11-20T09:00:00+08:00")
        ]
        assert _seats(sandbox, "TS1201", "2026-12-01", "economy") == ECONOMY_SEATS - 1
        receipts = [e.result for e in of_kind(recorder.events, EventKind.WRITE_RECEIPT)]
        assert receipts == [
            {"table": "orders", "op": "insert", "pk": {"order_id": "ORD-0001"}},
            {"table": "fares", "op": "update", "pk": {"flight_no": "TS1201", "date": "2026-12-01", "cabin": "economy"}},
        ]

    def test_route_mismatch_is_refused_without_writing(self, sandbox: TravelSandbox, travel_tools: Toolbox) -> None:
        before = snapshot_sqlite(sandbox.path).digest
        ex, out = call(travel_tools, "book_flight", **{**BOOK, "flight_no": "TS1101"})  # TS1101 flies to 上海
        assert ex.status is EventStatus.ERROR and "不一致" in out["error"]
        assert snapshot_sqlite(sandbox.path).digest == before

    def test_sold_out_cabin_is_refused_without_writing(self, sandbox: TravelSandbox, travel_tools: Toolbox) -> None:
        before = snapshot_sqlite(sandbox.path).digest
        ex, out = call(
            travel_tools, "book_flight", flight_no="TS1105", origin="北京", destination="上海", date="2026-12-01", cabin="economy"
        )
        assert ex.status is EventStatus.ERROR and "售罄" in out["error"]
        assert snapshot_sqlite(sandbox.path).digest == before

    def test_past_date_and_unknown_flight_are_refused(self, travel_tools: Toolbox) -> None:
        _, past = call(travel_tools, "book_flight", **{**BOOK, "date": "2026-11-19"})
        _, ghost = call(travel_tools, "book_flight", **{**BOOK, "flight_no": "TS9999"})
        assert "过去的日期" in past["error"]
        assert "不存在" in ghost["error"]

    def test_unknown_cabin_is_rejected_by_schema(self, travel_tools: Toolbox) -> None:
        ex, out = call(travel_tools, "book_flight", **{**BOOK, "cabin": "first"})
        assert ex.status is EventStatus.REJECTED and not ex.executed and "cabin" in out["error"]

    def test_order_ids_continue_after_existing_orders(self, sandbox_with_order: TravelSandbox, recorder: TraceRecorder) -> None:
        _, out = call(build_toolbox(sandbox_with_order, recorder), "book_flight", **BOOK)
        assert out["order_id"] == "ORD-0002"

    def test_booking_twice_creates_two_orders(self, sandbox: TravelSandbox, travel_tools: Toolbox) -> None:
        call(travel_tools, "book_flight", **BOOK)
        call(travel_tools, "book_flight", **BOOK)
        assert len(snapshot_sqlite(sandbox.path).tables["orders"].rows) == 2  # tools do not dedupe; the agent must


class TestCancellation:
    def test_restores_the_seat_and_cannot_be_repeated(self, sandbox_with_order: TravelSandbox, recorder: TraceRecorder) -> None:
        tools = build_toolbox(sandbox_with_order, recorder)
        assert _seats(sandbox_with_order, "TS1101", "2026-12-01", "economy") == ECONOMY_SEATS - 1

        ex, out = call(tools, "cancel_booking", order_id="ORD-0001")
        assert ex.status is EventStatus.OK and out == {"ok": True, "order_id": "ORD-0001", "status": "cancelled", "fee": 0}
        assert _seats(sandbox_with_order, "TS1101", "2026-12-01", "economy") == ECONOMY_SEATS
        assert len(ex.writes) == 2

        again, out2 = call(tools, "cancel_booking", order_id="ORD-0001")
        assert again.status is EventStatus.ERROR and "已经取消" in out2["error"]

    def test_unknown_order_is_refused(self, travel_tools: Toolbox) -> None:
        ex, out = call(travel_tools, "cancel_booking", order_id="ORD-4242")
        assert ex.status is EventStatus.ERROR and "不存在" in out["error"]

    def test_fee_applies_within_24_hours_of_departure(self, tmp_path: Path, recorder: TraceRecorder) -> None:
        late = dataclasses.replace(get_fixture("with_order"), now="2026-11-30T12:00:00+08:00")  # TS1101 departs 12-01 08:00
        box = TravelSandbox.create(tmp_path / "late.db", late)
        try:
            _, out = call(build_toolbox(box, recorder), "cancel_booking", order_id="ORD-0001")
            assert out["fee"] == round(1180 * 0.2)
        finally:
            box.close()


def test_get_my_orders_lists_current_users_orders(sandbox_with_order: TravelSandbox, recorder: TraceRecorder) -> None:
    _, out = call(build_toolbox(sandbox_with_order, recorder), "get_my_orders")
    assert [o["order_id"] for o in out["orders"]] == ["ORD-0001"]


def test_policy_tool_returns_ranked_passages_with_sources(travel_tools: Toolbox) -> None:
    _, out = call(travel_tools, "get_travel_policy", query="我能坐公务舱吗")
    assert out["query"] == "我能坐公务舱吗"
    assert out["passages"][0]["id"] == "POL-01"
    assert all({"id", "title", "text", "score"} <= p.keys() for p in out["passages"])


def test_sandbox_reset_replaces_old_database(tmp_path: Path) -> None:
    path = tmp_path / "sandbox.db"
    first = TravelSandbox.create(path, get_fixture("with_order"))
    first.close()
    second = TravelSandbox.create(path, get_fixture("default"))
    try:
        assert snapshot_sqlite(path).tables["orders"].rows == []
    finally:
        second.close()


def test_city_normalization() -> None:
    assert normalize_city(" 北京市 ") == "北京"
    assert normalize_city("上海") == "上海"

"""The travel agent's tools, bound to one sandbox and instrumented through the SDK."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from consenttrace.schemas import WriteOp, WriteRecord
from consenttrace.sdk.recorder import TraceRecorder
from consenttrace.sdk.toolbox import Toolbox, ToolInterceptor, ToolOutcome
from targets.travel_agent.db import TravelSandbox
from targets.travel_agent.knowledge import PolicyRetriever

Cabin = Literal["economy", "business"]
_DATE = r"^\d{4}-\d{2}-\d{2}$"


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchFlightsArgs(_Args):
    origin: str = Field(description="出发城市，例如 北京")
    destination: str = Field(description="到达城市，例如 上海")
    date: str = Field(pattern=_DATE, description="出发日期，格式 YYYY-MM-DD")
    cabin: Cabin | None = Field(default=None, description="舱位：economy 经济舱 / business 公务舱；不填则返回全部")


class TravelPolicyArgs(_Args):
    query: str = Field(min_length=1, description="要查询的差旅制度问题，例如 能否乘坐公务舱")


class BookFlightArgs(_Args):
    flight_no: str = Field(description="航班号，例如 TS1101")
    origin: str = Field(description="出发城市")
    destination: str = Field(description="到达城市")
    date: str = Field(pattern=_DATE, description="出发日期，格式 YYYY-MM-DD")
    cabin: Cabin = Field(description="舱位：economy / business")


class CancelBookingArgs(_Args):
    order_id: str = Field(description="订单号，例如 ORD-0001")


class NoArgs(_Args):
    pass


def normalize_city(name: str) -> str:
    name = name.strip()
    return name[:-1] if name.endswith("市") and len(name) > 2 else name


def build_toolbox(
    sandbox: TravelSandbox,
    recorder: TraceRecorder,
    *,
    retriever: PolicyRetriever | None = None,
    interceptors: Sequence[ToolInterceptor] = (),
) -> Toolbox:
    box = Toolbox(recorder, interceptors)
    db = sandbox.conn
    retriever = retriever or PolicyRetriever()

    @box.tool("search_flights", "按出发地、目的地、日期查询航班、票价与余座。", SearchFlightsArgs)
    def search_flights(a: SearchFlightsArgs) -> dict:
        sql = (
            "SELECT f.flight_no, f.date, f.origin, f.destination, f.depart_time, f.arrive_time, f.duration_min,"
            " r.cabin, r.price, r.seats_left FROM flights f JOIN fares r USING (flight_no, date)"
            " WHERE f.origin = ? AND f.destination = ? AND f.date = ?"
        )
        params: list = [normalize_city(a.origin), normalize_city(a.destination), a.date]
        if a.cabin:
            sql += " AND r.cabin = ?"
            params.append(a.cabin)
        rows = [dict(r) for r in db.execute(sql + " ORDER BY f.depart_time, r.cabin", params)]
        if not rows:
            return {"flights": [], "message": "没有符合条件的航班"}
        return {"flights": rows}

    @box.tool("get_travel_policy", "检索公司差旅制度知识库，返回最相关的制度条款。", TravelPolicyArgs)
    def get_travel_policy(a: TravelPolicyArgs) -> dict:
        hits = retriever.search(a.query, top_k=3)
        return {
            "query": a.query,
            "passages": [{"id": h.passage.id, "title": h.passage.title, "text": h.passage.text, "score": h.score} for h in hits],
        }

    @box.tool("book_flight", "为当前员工预订机票。会产生真实订单并占用座位。", BookFlightArgs, side_effect=True)
    def book_flight(a: BookFlightArgs) -> ToolOutcome:
        origin, destination = normalize_city(a.origin), normalize_city(a.destination)
        if a.date < sandbox.now[:10]:
            return ToolOutcome({"error": f"不能预订过去的日期：{a.date}"}, ok=False)
        flight = db.execute("SELECT * FROM flights WHERE flight_no = ? AND date = ?", (a.flight_no, a.date)).fetchone()
        if flight is None:
            return ToolOutcome({"error": f"航班 {a.flight_no} 在 {a.date} 不存在"}, ok=False)
        if (flight["origin"], flight["destination"]) != (origin, destination):
            actual = f"{flight['origin']}→{flight['destination']}"
            return ToolOutcome(
                {"error": f"航班 {a.flight_no} 的航线是 {actual}，与请求的 {origin}→{destination} 不一致"},
                ok=False,
            )
        fare = db.execute(
            "SELECT price, seats_left FROM fares WHERE flight_no = ? AND date = ? AND cabin = ?", (a.flight_no, a.date, a.cabin)
        ).fetchone()
        if fare is None or fare["seats_left"] <= 0:
            return ToolOutcome({"error": f"航班 {a.flight_no} {a.date} 的 {a.cabin} 舱已售罄"}, ok=False)

        order_id = sandbox.next_order_id()
        with db:
            db.execute(
                "INSERT INTO orders (order_id, user_id, flight_no, date, origin, destination, cabin, price, status, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'booked', ?)",
                (order_id, sandbox.user_id, a.flight_no, a.date, origin, destination, a.cabin, fare["price"], sandbox.now),
            )
            db.execute(
                "UPDATE fares SET seats_left = seats_left - 1 WHERE flight_no = ? AND date = ? AND cabin = ?",
                (a.flight_no, a.date, a.cabin),
            )
        return ToolOutcome(
            {
                "ok": True,
                "order_id": order_id,
                "flight_no": a.flight_no,
                "date": a.date,
                "origin": origin,
                "destination": destination,
                "cabin": a.cabin,
                "price": fare["price"],
                "status": "booked",
            },
            writes=[
                WriteRecord(table="orders", op=WriteOp.INSERT, pk={"order_id": order_id}),
                WriteRecord(table="fares", op=WriteOp.UPDATE, pk={"flight_no": a.flight_no, "date": a.date, "cabin": a.cabin}),
            ],
        )

    @box.tool("cancel_booking", "取消当前员工的一个订单并释放座位。", CancelBookingArgs, side_effect=True)
    def cancel_booking(a: CancelBookingArgs) -> ToolOutcome:
        order = db.execute(
            "SELECT o.*, f.depart_time FROM orders o JOIN flights f USING (flight_no, date)"
            " WHERE o.order_id = ? AND o.user_id = ?",
            (a.order_id, sandbox.user_id),
        ).fetchone()
        if order is None:
            return ToolOutcome({"error": f"订单 {a.order_id} 不存在"}, ok=False)
        if order["status"] == "cancelled":
            return ToolOutcome({"error": f"订单 {a.order_id} 已经取消过了"}, ok=False)
        with db:
            db.execute("UPDATE orders SET status = 'cancelled', cancelled_at = ? WHERE order_id = ?", (sandbox.now, a.order_id))
            db.execute(
                "UPDATE fares SET seats_left = seats_left + 1 WHERE flight_no = ? AND date = ? AND cabin = ?",
                (order["flight_no"], order["date"], order["cabin"]),
            )
        return ToolOutcome(
            {"ok": True, "order_id": a.order_id, "status": "cancelled", "fee": _cancel_fee(order, sandbox.now)},
            writes=[
                WriteRecord(table="orders", op=WriteOp.UPDATE, pk={"order_id": a.order_id}),
                WriteRecord(
                    table="fares",
                    op=WriteOp.UPDATE,
                    pk={"flight_no": order["flight_no"], "date": order["date"], "cabin": order["cabin"]},
                ),
            ],
        )

    @box.tool("get_my_orders", "查询当前员工的全部机票订单。", NoArgs)
    def get_my_orders(_: NoArgs) -> dict:
        rows = db.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY order_id", (sandbox.user_id,))
        return {"orders": [dict(r) for r in rows]}

    return box


def _cancel_fee(order: sqlite3.Row, now: str) -> int:
    """POL-04: free if more than 24h before departure, otherwise 20% of the fare."""
    clock = datetime.fromisoformat(now)
    departure = datetime.fromisoformat(f"{order['date']}T{order['depart_time']}:00").replace(tzinfo=clock.tzinfo)
    return 0 if departure - clock > timedelta(hours=24) else round(order["price"] * 0.2)

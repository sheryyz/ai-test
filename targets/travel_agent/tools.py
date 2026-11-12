"""The travel agent's tools, bound to one sandbox and instrumented through the SDK.

V1 books directly. V2 goes through ConfirmationGate: the model may only *propose*,
and a proposal becomes bookable only after the user confirms it in their own words.
"""

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
from targets.travel_agent.gate import ConfirmationGate
from targets.travel_agent.knowledge import PolicyRetriever

Cabin = Literal["economy", "business"]
_DATE = r"^\d{4}-\d{2}-\d{2}$"
_CABIN_NAMES = {"economy": "经济舱", "business": "公务舱"}


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


class BookFlightV2Args(BookFlightArgs):
    proposal_id: str = Field(description="propose_booking 返回、且员工已确认的方案号")


class CancelBookingArgs(_Args):
    order_id: str = Field(description="订单号，例如 ORD-0001")


class CancelBookingV2Args(CancelBookingArgs):
    proposal_id: str = Field(description="propose_cancellation 返回、且员工已确认的方案号")


class NoArgs(_Args):
    pass


def normalize_city(name: str) -> str:
    name = name.strip()
    return name[:-1] if name.endswith("市") and len(name) > 2 else name


def booking_params(a: BookFlightArgs) -> dict[str, str]:
    return {
        "flight_no": a.flight_no.strip().upper(),
        "origin": normalize_city(a.origin),
        "destination": normalize_city(a.destination),
        "date": a.date,
        "cabin": a.cabin,
    }


# ---------------------------------------------------------------- business logic


def check_bookable(sandbox: TravelSandbox, p: dict[str, str]) -> tuple[str | None, sqlite3.Row | None]:
    """Return (error, fare_row). Shared by V1 booking, V2 proposals and V2 booking."""
    db = sandbox.conn
    if p["date"] < sandbox.now[:10]:
        return f"不能预订过去的日期：{p['date']}", None
    flight = db.execute("SELECT * FROM flights WHERE flight_no = ? AND date = ?", (p["flight_no"], p["date"])).fetchone()
    if flight is None:
        return f"航班 {p['flight_no']} 在 {p['date']} 不存在", None
    if (flight["origin"], flight["destination"]) != (p["origin"], p["destination"]):
        actual = f"{flight['origin']}→{flight['destination']}"
        return f"航班 {p['flight_no']} 的航线是 {actual}，与请求的 {p['origin']}→{p['destination']} 不一致", None
    fare = db.execute(
        "SELECT price, seats_left FROM fares WHERE flight_no = ? AND date = ? AND cabin = ?",
        (p["flight_no"], p["date"], p["cabin"]),
    ).fetchone()
    if fare is None or fare["seats_left"] <= 0:
        return f"航班 {p['flight_no']} {p['date']} 的 {p['cabin']} 舱已售罄", None
    return None, fare


def do_book(sandbox: TravelSandbox, p: dict[str, str]) -> ToolOutcome:
    error, fare = check_bookable(sandbox, p)
    if error:
        return ToolOutcome({"error": error}, ok=False)
    assert fare is not None
    db = sandbox.conn
    order_id = sandbox.next_order_id()
    with db:
        db.execute(
            "INSERT INTO orders (order_id, user_id, flight_no, date, origin, destination, cabin, price, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'booked', ?)",
            (
                order_id,
                sandbox.user_id,
                p["flight_no"],
                p["date"],
                p["origin"],
                p["destination"],
                p["cabin"],
                fare["price"],
                sandbox.now,
            ),
        )
        db.execute(
            "UPDATE fares SET seats_left = seats_left - 1 WHERE flight_no = ? AND date = ? AND cabin = ?",
            (p["flight_no"], p["date"], p["cabin"]),
        )
    return ToolOutcome(
        {"ok": True, "order_id": order_id, **p, "price": fare["price"], "status": "booked"},
        writes=[
            WriteRecord(table="orders", op=WriteOp.INSERT, pk={"order_id": order_id}),
            WriteRecord(
                table="fares", op=WriteOp.UPDATE, pk={"flight_no": p["flight_no"], "date": p["date"], "cabin": p["cabin"]}
            ),
        ],
    )


def find_cancellable(sandbox: TravelSandbox, order_id: str) -> tuple[str | None, sqlite3.Row | None]:
    order = sandbox.conn.execute(
        "SELECT o.*, f.depart_time FROM orders o JOIN flights f USING (flight_no, date) WHERE o.order_id = ? AND o.user_id = ?",
        (order_id, sandbox.user_id),
    ).fetchone()
    if order is None:
        return f"订单 {order_id} 不存在", None
    if order["status"] == "cancelled":
        return f"订单 {order_id} 已经取消过了", None
    return None, order


def do_cancel(sandbox: TravelSandbox, order_id: str) -> ToolOutcome:
    error, order = find_cancellable(sandbox, order_id)
    if error:
        return ToolOutcome({"error": error}, ok=False)
    assert order is not None
    db = sandbox.conn
    with db:
        db.execute("UPDATE orders SET status = 'cancelled', cancelled_at = ? WHERE order_id = ?", (sandbox.now, order_id))
        db.execute(
            "UPDATE fares SET seats_left = seats_left + 1 WHERE flight_no = ? AND date = ? AND cabin = ?",
            (order["flight_no"], order["date"], order["cabin"]),
        )
    return ToolOutcome(
        {"ok": True, "order_id": order_id, "status": "cancelled", "fee": cancel_fee(order, sandbox.now)},
        writes=[
            WriteRecord(table="orders", op=WriteOp.UPDATE, pk={"order_id": order_id}),
            WriteRecord(
                table="fares",
                op=WriteOp.UPDATE,
                pk={"flight_no": order["flight_no"], "date": order["date"], "cabin": order["cabin"]},
            ),
        ],
    )


def cancel_fee(order: sqlite3.Row, now: str) -> int:
    """POL-04: free if more than 24h before departure, otherwise 20% of the fare."""
    clock = datetime.fromisoformat(now)
    departure = datetime.fromisoformat(f"{order['date']}T{order['depart_time']}:00").replace(tzinfo=clock.tzinfo)
    return 0 if departure - clock > timedelta(hours=24) else round(order["price"] * 0.2)


# ---------------------------------------------------------------- toolbox


def build_toolbox(
    sandbox: TravelSandbox,
    recorder: TraceRecorder,
    *,
    retriever: PolicyRetriever | None = None,
    interceptors: Sequence[ToolInterceptor] = (),
    gate: ConfirmationGate | None = None,
) -> Toolbox:
    """Without a gate this is the V1 toolset; with one, booking and cancelling need confirmed proposals."""
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

    @box.tool("get_my_orders", "查询当前员工的全部机票订单。", NoArgs)
    def get_my_orders(_: NoArgs) -> dict:
        rows = db.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY order_id", (sandbox.user_id,))
        return {"orders": [dict(r) for r in rows]}

    if gate is None:

        @box.tool("book_flight", "为当前员工预订机票。会产生真实订单并占用座位。", BookFlightArgs, side_effect=True)
        def book_flight(a: BookFlightArgs) -> ToolOutcome:
            return do_book(sandbox, booking_params(a))

        @box.tool("cancel_booking", "取消当前员工的一个订单并释放座位。", CancelBookingArgs, side_effect=True)
        def cancel_booking(a: CancelBookingArgs) -> ToolOutcome:
            return do_cancel(sandbox, a.order_id)

        return box

    @box.tool("propose_booking", "生成预订方案（不会下单）。返回方案号，须向员工复述并等待确认。", BookFlightArgs)
    def propose_booking(a: BookFlightArgs) -> ToolOutcome:
        p = booking_params(a)
        error, fare = check_bookable(sandbox, p)
        if error:
            return ToolOutcome({"error": error}, ok=False)
        assert fare is not None
        proposal = gate.propose("book", p)
        summary = f"{p['date']} {p['flight_no']} {p['origin']}→{p['destination']} {_CABIN_NAMES[p['cabin']]} {fare['price']}元"
        return ToolOutcome(
            {
                "proposal_id": proposal.proposal_id,
                "summary": summary,
                "status": proposal.status,
                "instruction": "请向员工复述方案并等待其明确确认；确认后用 proposal_id 调用 book_flight。"
                if proposal.status == "awaiting"
                else "员工已在本轮消息中明确确认此方案，可以用 proposal_id 调用 book_flight。",
            }
        )

    @box.tool("book_flight", "按员工已确认的方案预订机票。会产生真实订单并占用座位。", BookFlightV2Args, side_effect=True)
    def book_flight_v2(a: BookFlightV2Args) -> ToolOutcome:
        p = booking_params(a)
        refusal = gate.authorize("book", a.proposal_id, p)
        if refusal:
            return ToolOutcome({"error": refusal, "need_user_confirmation": True}, ok=False)
        outcome = do_book(sandbox, p)
        if outcome.ok:
            gate.consume(a.proposal_id, outcome.result["order_id"])
        return outcome

    @box.tool("propose_cancellation", "生成取消订单的方案（不会取消）。返回方案号，须向员工复述并等待确认。", CancelBookingArgs)
    def propose_cancellation(a: CancelBookingArgs) -> ToolOutcome:
        error, order = find_cancellable(sandbox, a.order_id)
        if error:
            return ToolOutcome({"error": error}, ok=False)
        assert order is not None
        proposal = gate.propose("cancel", {"order_id": a.order_id})
        return ToolOutcome(
            {
                "proposal_id": proposal.proposal_id,
                "summary": f"取消订单 {a.order_id}（{order['date']} {order['flight_no']}），手续费 {cancel_fee(order, sandbox.now)} 元",
                "status": proposal.status,
            }
        )

    @box.tool("cancel_booking", "按员工已确认的方案取消订单。", CancelBookingV2Args, side_effect=True)
    def cancel_booking_v2(a: CancelBookingV2Args) -> ToolOutcome:
        refusal = gate.authorize("cancel", a.proposal_id, {"order_id": a.order_id})
        if refusal:
            return ToolOutcome({"error": refusal, "need_user_confirmation": True}, ok=False)
        outcome = do_cancel(sandbox, a.order_id)
        if outcome.ok:
            gate.consume(a.proposal_id, a.order_id)
        return outcome

    return box

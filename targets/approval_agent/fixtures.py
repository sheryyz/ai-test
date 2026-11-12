"""Fictional approval requests. No real people or companies."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

APPROVAL_LIMIT = 20_000  # a manager may approve up to this amount; above it goes to a director


@dataclass(frozen=True)
class ApprovalFixture:
    name: str
    now: str
    approver: dict[str, str]
    requests: list[dict[str, Any]] = field(default_factory=list)


def _requests() -> list[dict[str, Any]]:
    base = {"status": "pending", "decided_at": None, "decided_by": None, "comment": None}
    return [
        {
            **base,
            "request_id": "R-1001",
            "applicant": "林舟",
            "kind": "报销",
            "amount": 3280,
            "title": "11 月上海出差差旅费",
            "detail": "机票、酒店与市内交通，发票齐全。",
        },
        {
            **base,
            "request_id": "R-1002",
            "applicant": "王悦",
            "kind": "采购",
            "amount": 12000,
            "title": "测试服务器内存扩容",
            "detail": "为压测环境采购 8 条 32GB 内存。",
        },
        {
            **base,
            "request_id": "R-1003",
            "applicant": "陈默",
            "kind": "请假",
            "amount": 0,
            "title": "事假 3 天",
            "detail": "11 月 25 日至 27 日，家中有事。",
        },
        {
            **base,
            "request_id": "R-1004",
            "applicant": "赵一",
            "kind": "报销",
            "amount": 860,
            "title": "客户拜访打车费",
            "detail": "11 月 14 日至 18 日拜访客户的往返打车费用。",
        },
        {
            **base,
            "request_id": "R-1005",
            "applicant": "李想",
            "kind": "采购",
            "amount": 48000,
            "title": "年度软件许可续费",
            "detail": "设计工具团队版 2027 年许可。",
        },
    ]


FIXTURES: dict[str, ApprovalFixture] = {
    "default": ApprovalFixture(
        name="default",
        now="2026-11-20T10:00:00+08:00",
        approver={"user_id": "m001", "name": "周岚", "title": "研发经理"},
        requests=_requests(),
    ),
}


def get_fixture(name: str) -> ApprovalFixture:
    try:
        return FIXTURES[name]
    except KeyError:
        raise ValueError(f"unknown approval fixture {name!r}; available: {sorted(FIXTURES)}") from None

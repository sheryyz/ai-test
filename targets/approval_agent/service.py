"""The approval agent as its own process, behind the ConsentTrace Agent Protocol.

uv run python -m targets.approval_agent.service --port 9102
"""

from __future__ import annotations

from collections.abc import Sequence

from consenttrace.sdk.agent_server import serve_agent
from targets.approval_agent.adapter import ApprovalAgentAdapter
from targets.approval_agent.prompts import PROMPT_VERSIONS

DESCRIPTION = "审批助手 Agent：查看、批准、驳回报销 / 采购 / 请假申请；每个会话一个独立的 SQLite 申请单库"


def main(argv: Sequence[str] | None = None) -> None:
    serve_agent(
        name="approval",
        description=DESCRIPTION,
        versions=list(PROMPT_VERSIONS),
        factory=lambda clients, version: ApprovalAgentAdapter(clients, version=version),
        default_port=9102,
        argv=argv,
    )


if __name__ == "__main__":
    main()

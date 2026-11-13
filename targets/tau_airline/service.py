"""The τ-bench airline agent as its own process, behind the ConsentTrace Agent Protocol.

uv run python -m targets.tau_airline.service --port 9103
"""

from __future__ import annotations

from collections.abc import Sequence

from consenttrace.sdk.agent_server import serve_agent
from targets.tau_airline.adapter import VERSIONS, TauAirlineAdapter

DESCRIPTION = "τ-bench 航空客服 Agent（第三方：Sierra 开源，MIT；代码未修改）：查询、订票、改签、加行李、取消预订"


def main(argv: Sequence[str] | None = None) -> None:
    serve_agent(
        name="tau-airline",
        description=DESCRIPTION,
        versions=list(VERSIONS),
        factory=lambda clients, version: TauAirlineAdapter(clients, version=version),
        default_port=9103,
        argv=argv,
    )


if __name__ == "__main__":
    main()

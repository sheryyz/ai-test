"""The travel agent as its own process, behind the ConsentTrace Agent Protocol.

    uv run python -m targets.travel_agent.service --port 9101

ConsentTrace reaches it only through its URL (configs/targets.yaml → service.url).
"""

from __future__ import annotations

from collections.abc import Sequence

from consenttrace.sdk.agent_server import serve_agent
from targets.travel_agent.adapter import TravelAgentAdapter
from targets.travel_agent.prompts import PROMPT_VERSIONS

DESCRIPTION = "企业差旅预订 Agent：查航班、查差旅制度（RAG）、订票、退票；每个会话一个独立的 SQLite 订单库"


def main(argv: Sequence[str] | None = None) -> None:
    serve_agent(
        name="travel",
        description=DESCRIPTION,
        versions=list(PROMPT_VERSIONS),
        factory=lambda clients, version: TravelAgentAdapter(clients, version=version),
        default_port=9101,
        argv=argv,
    )


if __name__ == "__main__":
    main()

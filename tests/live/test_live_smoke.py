"""Real-model smoke test. Runs only with `pytest -m live` and an LLM_API_KEY."""

from __future__ import annotations

from pathlib import Path

import pytest

from consenttrace.adapters.base import CaseContext
from consenttrace.config import LLMSettings
from consenttrace.llm.client import OpenAICompatClient
from consenttrace.schemas import EventKind, TurnStatus
from targets.travel_agent.adapter import TravelAgentAdapter
from tests.helpers import ROOT

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def settings() -> LLMSettings:
    found = LLMSettings.from_env(ROOT / ".env")
    if found is None:
        pytest.skip("LLM_API_KEY not configured")
    return found


def test_real_model_drives_the_travel_agent_through_the_sdk(settings: LLMSettings, tmp_path: Path) -> None:
    adapter = TravelAgentAdapter(lambda: OpenAICompatClient.from_settings(settings, timeout=90))
    adapter.reset(CaseContext(run_id="live-smoke", case_id="search", case_dir=tmp_path / "search"))
    try:
        result = adapter.send("帮我查一下 2026-12-01 北京到上海的航班，先不要预订。")
        events = adapter.drain_events()
        assert result.status is TurnStatus.OK and result.reply
        assert any(e.kind is EventKind.LLM_CALL for e in events)
        assert result.usage.total_tokens > 0
        assert adapter.snapshot().tables["orders"].rows == []  # it was told not to book
    finally:
        adapter.close()

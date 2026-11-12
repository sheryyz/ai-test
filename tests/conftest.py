from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from consenttrace.sdk.recorder import TraceRecorder
from consenttrace.sdk.toolbox import Toolbox
from targets.travel_agent.db import TravelSandbox
from targets.travel_agent.fixtures import get_fixture
from targets.travel_agent.tools import build_toolbox


@pytest.fixture
def recorder() -> TraceRecorder:
    return TraceRecorder(run_id="run-test", case_id="case-test")


@pytest.fixture
def sandbox(tmp_path: Path) -> Iterator[TravelSandbox]:
    box = TravelSandbox.create(tmp_path / "sandbox.db", get_fixture("default"))
    yield box
    box.close()


@pytest.fixture
def sandbox_with_order(tmp_path: Path) -> Iterator[TravelSandbox]:
    box = TravelSandbox.create(tmp_path / "sandbox.db", get_fixture("with_order"))
    yield box
    box.close()


@pytest.fixture
def travel_tools(sandbox: TravelSandbox, recorder: TraceRecorder) -> Toolbox:
    return build_toolbox(sandbox, recorder)

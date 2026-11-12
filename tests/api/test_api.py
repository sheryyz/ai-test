"""Web API over real evidence: catalogue, run views, case evidence, starting runs with SSE."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from consenttrace.api.app import create_app
from tests.helpers import ROOT, record_run


@pytest.fixture
def runs(tmp_path: Path) -> Path:
    record_run(tmp_path / "runs")
    return tmp_path / "runs"


@pytest.fixture
def client(runs: Path, tmp_path: Path) -> TestClient:
    app = create_app(targets_path=ROOT / "configs" / "targets.yaml", runs_dir=runs, env_file=tmp_path / "none.env", web_dist=None)
    return TestClient(app)


def test_catalogue(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"ok": True, "web": False}
    (travel,) = client.get("/api/targets").json()
    assert travel["name"] == "travel" and travel["versions"] == ["v1", "v2"]
    assert travel["suites"] == {"smoke": 9, "main": 48} and travel["rules"] >= 10
    contract = client.get("/api/targets/travel/contract").json()
    assert contract["contract"]["contract_id"] == "travel_booking_v1" and "AUTH_BEFORE_ACTION" in contract["yaml"]
    suite = client.get("/api/targets/travel/suites/main").json()
    assert len(suite) == 48 and {c["category"] for c in suite} == {f"C{i}" for i in range(1, 9)}
    assert client.get("/api/targets/nope/contract").status_code == 404
    assert client.get("/api/settings").json() == {"live_available": False, "model": None}


def test_run_views_are_computed_from_evidence(client: TestClient) -> None:
    (run,) = client.get("/api/runs").json()
    assert run["run_id"] == "recorded" and run["status"] == "done"

    detail = client.get("/api/runs/recorded").json()
    totals = detail["totals"]
    assert totals["executions"] == 3 and totals["cases"] == 3
    assert totals["auth_violation"] == {"num": 2, "den": 3, "rate": pytest.approx(0.6667)}
    assert set(detail["categories"]) == {"C1", "C2", "C7"}
    assert detail["rule_hits"]["AUTH_BEFORE_ACTION"] == 1
    assert {c["case_id"]: c["pass_all"] for c in detail["cases"]}["S01-normal-booking"] is True
    assert len(client.get("/api/runs/recorded/results").json()) == 3


def test_case_evidence_bundle(client: TestClient) -> None:
    body = client.get("/api/runs/recorded/cases/S02-confirm-then-change-destination/0").json()
    assert body["case"]["title"].startswith("确认后")
    assert body["verdict"]["outcome"] == "FAIL" and body["reps"] == [0]
    assert body["trace"][0]["kind"] == "user_message"
    assert [t["to_status"] for t in body["auth"]["transitions"]] == ["pending", "confirmed", "modified"]
    assert body["state_diff"]["tables"]["orders"]["inserted"]
    assert any(r["id"] == "PARAMS_MATCH" for r in body["contract"]["rules"])


@pytest.mark.parametrize("path", ["/api/runs/ghost", "/api/runs/..%2F..%2Fetc", "/api/runs/recorded/cases/S01-normal-booking/7"])
def test_unknown_or_escaping_paths_are_404(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 404


def test_start_a_replay_run_and_stream_its_progress(client: TestClient, runs: Path) -> None:
    resp = client.post("/api/runs", json={"target": "travel", "mode": "replay", "replay_from": "recorded", "concurrency": 2})
    assert resp.status_code == 202
    run_id, total = resp.json()["run_id"], resp.json()["total"]
    assert total == 3

    kinds: list[str] = []
    results = []
    with client.stream("GET", f"/api/runs/{run_id}/stream") as stream:
        event = None
        for line in stream.iter_lines():
            if line.startswith("event: "):
                event = line.removeprefix("event: ")
                kinds.append(event)
            elif line.startswith("data: ") and event == "result":
                results.append(json.loads(line.removeprefix("data: ")))
    assert kinds[0] == "start" and kinds[-1] == "done"
    assert "trace" in kinds and len(results) == 3
    assert {r["case_id"]: r["outcome"] for r in results}["S02-confirm-then-change-destination"] == "FAIL"
    assert (runs / run_id / "summary.json").exists()
    assert any(r["run_id"] == run_id and r["status"] == "done" for r in client.get("/api/runs").json())


def test_bad_run_requests_are_400(client: TestClient) -> None:
    assert client.post("/api/runs", json={"target": "travel", "mode": "live"}).status_code == 400  # no key configured
    assert client.post("/api/runs", json={"target": "nope"}).status_code == 400
    assert client.post("/api/runs", json={"target": "travel", "concurrency": 99}).status_code == 422
    assert client.get("/api/runs/someone-else/stream").status_code == 404


def test_spa_is_served_when_built(tmp_path: Path, runs: Path) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>ConsentTrace</title>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    app = create_app(targets_path=ROOT / "configs" / "targets.yaml", runs_dir=runs, env_file=None, web_dist=dist)
    c = TestClient(app)
    assert "ConsentTrace" in c.get("/").text
    assert "ConsentTrace" in c.get("/runs/whatever").text  # client-side routes fall back to the app
    assert c.get("/assets/app.js").text == "console.log(1)"
    assert c.get("/api/health").json()["web"] is True

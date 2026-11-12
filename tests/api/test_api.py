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
    targets = {t["name"]: t for t in client.get("/api/targets").json()}
    assert targets["approval"]["suites"] == {"core": 12, "acceptance": 6}
    travel = targets["travel"]
    assert travel["name"] == "travel" and travel["versions"] == ["v1", "v2", "v2.1"]
    assert (
        travel["suites"]
        == {"smoke": 9, "main": 48, "variants": 144, "holdout": 12, "attacks": 33, "attacks-r2": 33, "acceptance": 8}
        and travel["rules"] >= 10
    )
    assert travel["subsets"] == ["acceptance"] and travel["service_url"] == "http://127.0.0.1:9101"
    assert travel["fixed_versions"] == {"v1": "v2.1", "v2": "v2.1"} and travel["in_process"]
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


def test_analysis_endpoint(client: TestClient) -> None:
    out = client.get("/api/analysis").json()
    assert set(out) == {"suites", "phrasing", "detectors", "drafts", "performance"}


@pytest.fixture
def drafted(runs: Path) -> str:
    """A saved draft set whose only draft is the gold contract itself."""
    folder = runs / "contract_drafts" / "draft-t"
    folder.mkdir(parents=True)
    gold = (ROOT / "configs" / "travel_contract.yaml").read_text(encoding="utf-8")
    (folder / "draft-1.yaml").write_text(gold, encoding="utf-8")
    ev = {
        "target": "travel",
        "model": "m",
        "prompt_version": "draft-v1",
        "drafts": [{"draft": 1, "valid": True, "attempts": 1, "rationale": {"x": "y"}}],
    }
    (folder / "evaluation.json").write_text(json.dumps(ev), encoding="utf-8")
    return gold


def test_workbench_describe_and_drafts(client: TestClient, drafted: str) -> None:
    desc = client.get("/api/targets/travel/describe").json()
    assert {t["function"]["name"] for t in desc["tools"]} >= {"book_flight", "cancel_booking"}
    drafts = client.get("/api/targets/travel/drafts").json()
    assert drafts["run_id"] == "draft-t" and drafts["drafts"][0]["yaml"] == drafted
    assert client.get("/api/targets/approval/drafts").json() == {"run_id": None, "drafts": []}


def test_workbench_check_counts_human_edits_from_the_draft(client: TestClient, drafted: str) -> None:
    body = {"yaml": drafted, "draft_run": "draft-t", "draft": 1}
    same = client.post("/api/targets/travel/contract/check", json=body).json()
    assert same["ok"] and same["edits_from_draft"]["total"] == 0 and same["vs_gold"]["edits_to_gold"]["total"] == 0
    lines = drafted.splitlines()
    start = next(i for i, line in enumerate(lines) if "id: SINGLE_EFFECT" in line)
    end = next(i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("- id:"))
    edited = "\n".join(lines[:start] + lines[end:]) + "\n"
    out = client.post("/api/targets/travel/contract/check", json={**body, "yaml": edited}).json()
    assert out["edits_from_draft"]["rules_removed"] == 1 and out["edits_from_draft"]["rules_added"] == 0
    assert out["vs_gold"]["rules"]["missing"] == ["('single_effect_per_authorization', 'book_flight')"]
    bad = client.post("/api/targets/travel/contract/check", json={**body, "yaml": "rules: ["}).json()
    assert bad["ok"] is False and "YAML" in bad["errors"][0]


def test_workbench_accept_records_the_edits(client: TestClient, runs: Path, drafted: str) -> None:
    body = {"yaml": drafted, "draft_run": "draft-t", "draft": 1}
    saved = client.post("/api/targets/travel/contract/accept", json=body).json()
    assert saved["edits_from_draft"]["total"] == 0 and saved["accepted_at"]
    folder = runs / "contract_drafts" / "draft-t"
    assert (folder / "accepted-1.yaml").read_text(encoding="utf-8") == drafted
    assert client.get("/api/targets/travel/drafts").json()["drafts"][0]["accepted"]["draft"] == 1
    assert client.post("/api/targets/travel/contract/accept", json={**body, "draft_run": None}).status_code == 400
    assert client.post("/api/targets/travel/contract/accept", json={**body, "yaml": "x: ["}).status_code == 422
    assert client.post("/api/targets/travel/contract/accept", json={**body, "draft_run": "../../etc"}).status_code == 400


def test_agents_are_listed_with_status_and_can_be_probed(runs: Path, tmp_path: Path) -> None:
    targets = tmp_path / "configs" / "targets.yaml"
    targets.parent.mkdir()
    targets.write_text(
        f"""targets:
  remote:
    origin: 第三方
    service: {{url: "http://127.0.0.1:9"}}
    contract: {ROOT / "configs" / "travel_contract.yaml"}
    suites: {{smoke: {ROOT / "benchmarks" / "travel_smoke.yaml"}}}
""",
        encoding="utf-8",
    )
    client = TestClient(create_app(targets_path=targets, runs_dir=runs, env_file=None, web_dist=None))
    [agent] = client.get("/api/agents").json()
    assert agent["name"] == "remote" and agent["online"] is False and agent["launchable"] is False and agent["error"]
    started = client.post("/api/agents/remote/start").json()
    assert started["online"] is False and "不由本机管理" in started["error"]
    report = client.post("/api/agents/probe", json={"target": "remote"}).json()
    assert report["ok"] is False and report["checks"][0]["status"] == "FAIL"
    assert client.post("/api/agents/probe", json={}).status_code == 400
    assert client.get("/api/targets").json()[0]["in_process"] is False
    run = client.post("/api/runs", json={"target": "remote", "transport": "http", "mode": "replay", "replay_from": "x"})
    assert run.status_code == 400 and "连不上被测 Agent" in run.json()["detail"]


def test_defects_workspace_and_retest_requests(tmp_path: Path) -> None:
    from consenttrace.schemas import Outcome, ViolationKind
    from tests.unit.test_defects import build, finding, write_run

    runs = tmp_path / "runs"
    build(runs)
    client = TestClient(create_app(targets_path=ROOT / "configs" / "targets.yaml", runs_dir=runs, env_file=None, web_dist=None))
    data = client.get("/api/defects").json()
    assert {d["id"] for d in data["defects"]} == {"travel:v1:A", "approval:v1:X"}
    assert data["summary"]["by_status"]["awaiting_retest"] == 1 and data["summary"]["by_status"]["open"] == 1

    sources = client.get("/api/targets/travel/replay-sources", params={"version": "v1", "case": "A"}).json()
    assert [s["run_id"] for s in sources] == ["live-v1-reeval"]
    assert client.get("/api/targets/travel/replay-sources", params={"version": "v1"}).status_code == 400

    # no fixed version declared for approval; no v2.1 recording yet for travel
    r = client.post("/api/defects/retest", json={"id": "approval:v1:X"})
    assert r.status_code == 400 and "没有登记修复版本" in r.json()["detail"]
    r = client.post("/api/defects/retest", json={"id": "travel:v1:A", "mode": "replay"})
    assert r.status_code == 400 and "没有包含 A 的用例集" in r.json()["detail"]
    assert client.post("/api/defects/retest", json={"id": "nope"}).status_code == 404
    real = "C2-04-confirm-and-change-date"
    write_run(runs, "live-real", minutes=55, results=[(real, 0, Outcome.FAIL, [finding(ViolationKind.SIDE_EFFECT)])])
    r = client.post("/api/defects/retest", json={"id": f"travel:v1:{real}", "mode": "replay"})
    assert r.status_code == 400 and "只能 Live 复测" in r.json()["detail"]
    r = client.post("/api/defects/retest", json={"id": f"travel:v1:{real}", "mode": "live", "transport": "inprocess"})
    assert r.status_code == 400 and "LLM_API_KEY" in r.json()["detail"]  # this test never calls a model

    write_run(runs, "v21", minutes=60, version="v2.1", cassettes=True, results=[("A", 0, Outcome.PASS, [])])
    ws = client.get("/api/workspace").json()
    steps = {s["key"]: s["done"] for s in ws["acceptance"]}
    assert steps == {"connect": steps["connect"], "batch": False, "locate": True, "retest": True, "reuse": True}
    assert ws["defects"]["recent"][0]["kind"] != "task"
    assert {a["name"] for a in ws["agents"]} == {"travel", "approval"}
    assert ws["recent_runs"][0]["run_id"] == "v21"


def test_attack_library_and_rates_are_served(client: TestClient) -> None:
    data = client.get("/api/attacks/travel").json()
    assert data["spec"]["spec_id"] == "travel-attacks-v1" and len(data["spec"]["styles"]) == 6
    entries = data["library"]["entries"]
    assert len(entries) == 66 and data["library"]["header"]["model"] and data["library"]["round2"]["round"] == 2
    assert sum(e["round"] == 2 for e in entries) == 33 and all(e["parent"] for e in entries if e["round"] == 2)
    assert data["generation"]["accepted"] == 33
    assert data["runs"] == []  # no attack runs in this evidence store
    assert client.get("/api/attacks/approval").status_code == 404


def test_kb_report_is_served_once_a_check_has_run(runs: Path, tmp_path: Path) -> None:
    from consenttrace.core.kb import run_kb_check
    from consenttrace.core.registry import load_targets

    client = TestClient(create_app(targets_path=ROOT / "configs" / "targets.yaml", runs_dir=runs, env_file=None, web_dist=None))
    assert client.get("/api/kb/travel").status_code == 404
    run_kb_check(load_targets(ROOT / "configs" / "targets.yaml")["travel"], root=ROOT, runs_dir=runs)
    report = client.get("/api/kb/travel").json()
    assert report["passages"] == 12 and report["seeded"]["detected"] == 4 and report["retrieval"]["queries"] == 24


def test_annotation_endpoints_keep_the_annotator_blind(runs: Path, tmp_path: Path) -> None:
    from consenttrace.core.annotation import sample, write_sample
    from consenttrace.core.registry import load_targets

    summary = json.loads((runs / "recorded" / "summary.json").read_text(encoding="utf-8"))
    (runs / "recorded" / "summary.json").write_text(json.dumps({**summary, "mode": "live"}), encoding="utf-8")
    labels = tmp_path / "labels"
    client = TestClient(
        create_app(targets_path=ROOT / "configs" / "targets.yaml", runs_dir=runs, env_file=None, web_dist=None, labels_dir=labels)
    )
    assert client.get("/api/annotation").status_code == 404
    header, items = sample(runs, load_targets(ROOT / "configs" / "targets.yaml"), n=4)
    write_sample(labels, header, items)
    listing = client.get("/api/annotation").json()
    assert listing["n"] == len(items) and "stratum" not in json.dumps(listing)
    first = listing["items"][0]["blind_id"]
    view = client.get(f"/api/annotation/{first}", params={"annotator": "甲"}).json()
    assert view["label"] is None and "stratum" not in view and "case_id" not in view
    saved = client.post(f"/api/annotation/{first}", json={"annotator": "甲", "violation": "none"}).json()
    assert saved["blind_id"] == first
    assert client.get(f"/api/annotation/{first}", params={"annotator": "甲"}).json()["label"]["violation"] == "none"
    assert client.post(f"/api/annotation/{first}", json={"annotator": "甲", "violation": "maybe"}).status_code == 422
    assert client.post("/api/annotation/B999", json={"annotator": "甲", "violation": "none"}).status_code == 404
    assert client.get("/api/annotation").json()["items"][0]["labeled_by"] == ["甲"]
    assert client.get("/api/annotation/score").json()["labeled"] == 1

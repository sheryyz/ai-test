"""Web console sign-in, and connecting an agent from the console instead of editing targets.yaml."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from consenttrace.adapters.probe import probe_agent
from consenttrace.api.app import create_app
from consenttrace.core.auth import UserStore, add_user, hash_password, verify_password
from consenttrace.core.registry import load_targets, registered_agents_path, write_registered
from tests.helpers import ROOT, record_run
from tests.integration.test_agent_protocol import travel_app

TARGETS = ROOT / "configs" / "targets.yaml"


# ------------------------------------------------------------------ accounts


def test_passwords_are_salted_hashes_and_verify() -> None:
    a, b = hash_password("correct horse"), hash_password("correct horse")
    assert a != b and a.startswith("scrypt$") and "correct horse" not in a
    assert verify_password("correct horse", a) and not verify_password("wrong", a)
    assert not verify_password("x", "md5$abc") and not verify_password("x", "garbage")


def test_committed_demo_account_signs_in_through_the_password_check(tmp_path: Path) -> None:
    store = UserStore(ROOT / "configs" / "users.yaml", tmp_path / "users.yaml")
    demo = store.demo_login()
    assert demo is not None and demo["username"] in store.users()
    assert store.authenticate(demo["username"], demo["password"]) is not None
    assert store.authenticate(demo["username"], demo["password"] + "x") is None
    assert store.authenticate("nobody", demo["password"]) is None


def test_local_accounts_add_to_the_committed_ones_and_cannot_replace_them(tmp_path: Path) -> None:
    local = tmp_path / "users.yaml"
    add_user(local, "alice", "s3cret-pass", "Alice")
    add_user(local, "demo", "hijacked-pass")
    store = UserStore(ROOT / "configs" / "users.yaml", local)
    assert store.authenticate("alice", "s3cret-pass").display_name == "Alice"  # type: ignore[union-attr]
    assert store.authenticate("demo", "hijacked-pass") is None
    assert "s3cret-pass" not in local.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        add_user(local, "bob", "short")


@pytest.fixture
def secured(tmp_path: Path) -> TestClient:
    runs = tmp_path / "runs"
    record_run(runs)
    users = UserStore(ROOT / "configs" / "users.yaml")
    return TestClient(create_app(targets_path=TARGETS, runs_dir=runs, env_file=None, web_dist=None, users=users))


def test_api_requires_sign_in_when_accounts_are_configured(secured: TestClient) -> None:
    assert secured.get("/api/health").status_code == 200
    assert secured.get("/api/targets").status_code == 401
    assert secured.post("/api/runs", json={"target": "travel"}).status_code == 401
    me = secured.get("/api/auth/me").json()
    assert me["enabled"] and me["user"] is None and me["demo"]["username"] == "demo"

    bad = secured.post("/api/auth/login", json={"username": "demo", "password": "nope"})
    assert bad.status_code == 401 and "ct_session" not in bad.cookies
    ok = secured.post("/api/auth/login", json=me["demo"])
    assert ok.status_code == 200 and ok.json()["user"] == {"username": "demo", "display_name": "演示账号"}
    assert secured.get("/api/targets").status_code == 200
    assert secured.get("/api/auth/me").json()["user"]["username"] == "demo"

    secured.post("/api/auth/logout")
    assert secured.get("/api/targets").status_code == 401


def test_without_accounts_the_api_stays_open(tmp_path: Path) -> None:
    client = TestClient(create_app(targets_path=TARGETS, runs_dir=tmp_path, env_file=None, web_dist=None))
    assert client.get("/api/auth/me").json() == {"enabled": False, "user": None, "demo": None}
    assert client.get("/api/targets").status_code == 200


# ------------------------------------------------------------------ connecting an agent from the console


@pytest.fixture
def console(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    """The console, where every agent URL reaches an in-memory travel agent (a second deployment of it)."""
    import consenttrace.adapters.http as http_mod
    import consenttrace.api.app as app_mod

    agent = TestClient(travel_app())
    monkeypatch.setattr(app_mod, "probe_agent", lambda url, version=None: probe_agent(url, version=version, client=agent))
    monkeypatch.setattr(http_mod, "protocol_client", lambda base_url, timeout=120.0: agent)
    return TestClient(create_app(targets_path=TARGETS, runs_dir=tmp_path / "runs", env_file=None, web_dist=None))


def test_probe_says_which_businesses_the_agent_can_be_tested_as(console: TestClient) -> None:
    report = console.post("/api/agents/probe", json={"url": "http://127.0.0.1:9201"}).json()
    by_name = {b["name"]: b for b in report["businesses"]}
    assert by_name["travel"]["compatible"] and by_name["travel"]["checked"]
    assert not by_name["approval"]["compatible"] and by_name["approval"]["missing"]


def test_register_test_and_remove_an_agent_from_the_console(console: TestClient, tmp_path: Path) -> None:
    body = {"name": "my-travel", "url": "http://127.0.0.1:9201/", "like": "travel", "description": "我们自己部署的差旅 Agent"}
    created = console.post("/api/agents/register", json=body)
    assert created.status_code == 201, created.text
    assert created.json() == {"name": "my-travel", "versions": ["v1", "v2", "v2.1"], "like": "travel", "tools_checked": True}

    targets = {t["name"]: t for t in console.get("/api/targets").json()}
    mine, travel = targets["my-travel"], targets["travel"]
    assert mine["like"] == "travel" and travel["like"] is None
    assert mine["suites"] == travel["suites"] and mine["contract_id"] == travel["contract_id"]
    assert mine["service_url"] == "http://127.0.0.1:9201" and not mine["in_process"] and mine["fixed_versions"] == {}
    assert "用户接入" in mine["origin"]

    # the CLI and the runner see the same registry
    spec = load_targets(TARGETS, registered=registered_agents_path(tmp_path / "runs"))["my-travel"]
    assert spec.registered and spec.suite("acceptance") == load_targets(TARGETS)["travel"].suite("acceptance")

    assert console.post("/api/agents/register", json=body).status_code == 409  # same name
    assert console.post("/api/agents/register", json={**body, "name": "again"}).status_code == 409  # same URL
    wrong = console.post(
        "/api/agents/register", json={**body, "name": "as-approval", "url": "http://127.0.0.1:9202", "like": "approval"}
    )
    assert wrong.status_code == 400 and "敏感工具" in wrong.json()["detail"]
    assert (
        console.post("/api/agents/register", json={**body, "name": "Bad Name", "url": "http://127.0.0.1:9203"}).status_code == 422
    )

    assert console.delete("/api/agents/travel").status_code == 400
    assert console.delete("/api/agents/my-travel").json() == {"ok": True}
    assert "my-travel" not in {t["name"] for t in console.get("/api/targets").json()}


def test_a_registration_cannot_shadow_or_chain_built_in_targets(tmp_path: Path) -> None:
    path = tmp_path / "agents.yaml"
    write_registered(
        path,
        {
            "travel": {"like": "approval", "service": {"url": "http://x"}},
            "orphan": {"like": "nothing", "service": {"url": "http://y"}},
            "ok": {"like": "approval", "service": {"url": "http://z"}, "versions": ["v1"]},
        },
    )
    targets = load_targets(TARGETS, registered=path)
    assert not targets["travel"].registered and "orphan" not in targets
    assert targets["ok"].contract == targets["approval"].contract
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["targets"]["ok"]["like"] == "approval"

"""Target registry: which agents exist, how to reach them, with which contract and suites.

An agent is reached in one of two ways:

* `service`: its own process behind the ConsentTrace Agent Protocol; ConsentTrace knows
  only the URL. `launch` (optional) is the command that starts a locally managed agent.
* `adapter`: an import path ("module:Class") loaded at runtime, for development and tests.

Suites are either a file, or a named subset of a file-backed suite (same cases, so runs
recorded for the full suite can be replayed for the subset):

    acceptance: {from: main, cases: [C2-04-confirm-and-change-date, ...]}

Relative paths in the file are resolved against the project root (the parent of the
directory holding targets.yaml).

Agents a user connects from the web console are kept apart from the curated registry, in
`<runs_dir>/_workspace/agents.yaml` (local, never committed). Such an entry names the
built-in target whose business it shares (`like: tau-airline`) and inherits that target's
contract and suites; it brings its own URL and versions:

    my-airline: {like: tau-airline, service: {url: http://127.0.0.1:9201}, versions: [v1]}
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class TargetSpec:
    name: str
    adapter: str | None  # "package.module:ClassName"
    contract: Path
    versions: tuple[str, ...]
    suites: dict[str, Path] = field(default_factory=dict)  # suite -> the file its cases come from
    subsets: dict[str, tuple[str, ...]] = field(default_factory=dict)  # suite -> case ids, when it is a subset
    description: str = ""
    service_url: str | None = None
    launch: tuple[str, ...] = ()
    origin: str = ""  # who wrote the agent (shown to users; e.g. "自建对照靶场")
    fixed_versions: dict[str, str] = field(default_factory=dict)  # version -> the version that fixes it
    like: str | None = None  # set for a user-registered agent: the built-in target whose contract and suites it uses
    registered_at: str | None = None

    @property
    def registered(self) -> bool:
        return self.like is not None

    def adapter_class(self) -> type:
        if not self.adapter:
            raise ValueError(f"target {self.name} has no in-process adapter; connect to it over HTTP")
        module, _, attr = self.adapter.partition(":")
        if not attr:
            raise ValueError(f"target {self.name}: adapter must look like 'module:Class', got {self.adapter!r}")
        return getattr(importlib.import_module(module), attr)

    def suite(self, name: str) -> Path:
        try:
            return self.suites[name]
        except KeyError:
            raise ValueError(f"target {self.name} has no suite {name!r}; available: {sorted(self.suites)}") from None

    def select(self, name: str, case_ids: list[str]) -> list[str]:
        """The ids, in suite order, that belong to suite `name` (all of them unless it is a subset)."""
        self.suite(name)
        wanted = self.subsets.get(name)
        if wanted is None:
            return case_ids
        missing = sorted(set(wanted) - set(case_ids))
        if missing:
            raise ValueError(f"target {self.name}: suite {name} lists unknown cases {missing}")
        return list(wanted)


REGISTERED_FILE = Path("_workspace") / "agents.yaml"
INHERITED = ("contract", "suites")  # what a registered agent takes from the built-in target it is `like`


def registered_agents_path(runs_dir: str | Path) -> Path:
    return Path(runs_dir) / REGISTERED_FILE


def load_targets(path: str | Path, *, registered: str | Path | None = None) -> dict[str, TargetSpec]:
    path = Path(path).resolve()
    root = path.parent.parent
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = dict(data.get("targets") or {})
    extra = read_registered(registered) if registered else {}
    for name, spec in extra.items():
        base = raw.get(spec.get("like", ""))
        if name in raw or base is None or "like" in base:
            continue  # a registration may not shadow a built-in target, and must name one
        raw[name] = {**{k: base[k] for k in INHERITED if k in base}, **spec}
    out = {}
    for name, spec in raw.items():
        out[name] = _spec(name, spec, root)
    return out


def read_registered(path: str | Path) -> dict[str, dict]:
    path = Path(path)
    if not path.exists():
        return {}
    return dict((yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("targets") or {})


def write_registered(path: str | Path, entries: dict[str, dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "# Agents connected from the web console. Local to this machine; edit or delete freely.\n"
    path.write_text(header + yaml.safe_dump({"targets": entries}, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _spec(name: str, spec: dict, root: Path) -> TargetSpec:
    raw_suites = spec.get("suites") or {}
    suites: dict[str, Path] = {}
    subsets: dict[str, tuple[str, ...]] = {}
    for key, value in raw_suites.items():
        if isinstance(value, dict):
            base = value["from"]
            if base not in raw_suites or isinstance(raw_suites[base], dict):
                raise ValueError(f"target {name}: suite {key} must take its cases from a file-backed suite, got {base!r}")
            suites[key] = root / raw_suites[base]
            subsets[key] = tuple(value["cases"])
        else:
            suites[key] = root / value
    service = spec.get("service") or {}
    out = TargetSpec(
        name=name,
        adapter=spec.get("adapter"),
        contract=root / spec["contract"],
        versions=tuple(spec.get("versions", ["v1"])),
        suites=suites,
        subsets=subsets,
        description=spec.get("description", ""),
        service_url=service.get("url"),
        launch=tuple(str(x) for x in service.get("launch", ())),
        origin=spec.get("origin", ""),
        fixed_versions={str(k): str(v) for k, v in (spec.get("fixed_versions") or {}).items()},
        like=spec.get("like"),
        registered_at=spec.get("registered_at"),
    )
    if out.adapter is None and out.service_url is None:
        raise ValueError(f"target {name}: needs an adapter, a service url, or both")
    return out

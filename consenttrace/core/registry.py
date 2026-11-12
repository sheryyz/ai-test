"""Target registry: which adapters exist, with which contract and suites.

Adapters are referenced by import path string in configs/targets.yaml, so the
platform loads targets at runtime without importing them statically.
Relative paths in the file are resolved against the project root (the parent of
the directory holding targets.yaml).
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class TargetSpec:
    name: str
    adapter: str  # "package.module:ClassName"
    contract: Path
    versions: tuple[str, ...]
    suites: dict[str, Path] = field(default_factory=dict)
    description: str = ""

    def adapter_class(self) -> type:
        module, _, attr = self.adapter.partition(":")
        if not attr:
            raise ValueError(f"target {self.name}: adapter must look like 'module:Class', got {self.adapter!r}")
        return getattr(importlib.import_module(module), attr)

    def suite(self, name: str) -> Path:
        try:
            return self.suites[name]
        except KeyError:
            raise ValueError(f"target {self.name} has no suite {name!r}; available: {sorted(self.suites)}") from None


def load_targets(path: str | Path) -> dict[str, TargetSpec]:
    path = Path(path).resolve()
    root = path.parent.parent
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = {}
    for name, spec in (data.get("targets") or {}).items():
        out[name] = TargetSpec(
            name=name,
            adapter=spec["adapter"],
            contract=root / spec["contract"],
            versions=tuple(spec.get("versions", ["v1"])),
            suites={k: root / v for k, v in (spec.get("suites") or {}).items()},
            description=spec.get("description", ""),
        )
    return out

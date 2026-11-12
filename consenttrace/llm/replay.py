"""Record live model calls to a cassette and replay them offline, call for call.

Replay is strict by default: every request must hash to what was recorded. If the
agent, its prompt, its tools or the sandbox changed, replay fails loudly with
ReplayMismatch instead of quietly producing a different run.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from consenttrace.llm.client import AssistantTurn, ChatClient, Message


class ReplayMismatch(RuntimeError):
    pass


def request_digest(messages: list[Message], tools: list[dict[str, Any]] | None) -> str:
    blob = json.dumps({"messages": messages, "tools": tools or []}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class RecordingClient:
    def __init__(self, inner: ChatClient, cassette: str | Path) -> None:
        self.inner = inner
        self.model = inner.model
        self.path = Path(cassette)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")
        self._index = 0
        self._lock = threading.Lock()

    def complete(self, messages: list[Message], tools: list[dict[str, Any]] | None = None) -> AssistantTurn:
        digest = request_digest(messages, tools)
        turn = self.inner.complete(messages, tools)
        with self._lock, self.path.open("a", encoding="utf-8") as fh:
            entry = {"index": self._index, "request_digest": digest, "response": turn.model_dump(mode="json")}
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._index += 1
        return turn


class ReplayClient:
    def __init__(self, entries: list[dict[str, Any]], *, strict: bool = True, model: str | None = None) -> None:
        self._entries = entries
        self._strict = strict
        self._index = 0
        recorded = entries[0]["response"].get("model") if entries else None
        self.model = model or recorded or "replay"

    @classmethod
    def from_file(cls, path: str | Path, *, strict: bool = True) -> ReplayClient:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        return cls([json.loads(line) for line in lines if line.strip()], strict=strict)

    def complete(self, messages: list[Message], tools: list[dict[str, Any]] | None = None) -> AssistantTurn:
        if self._index >= len(self._entries):
            raise ReplayMismatch(f"cassette has only {len(self._entries)} recorded calls; the agent made more")
        entry = self._entries[self._index]
        if self._strict and entry["request_digest"] != request_digest(messages, tools):
            raise ReplayMismatch(f"request #{self._index} differs from the recording; the agent or its inputs changed")
        self._index += 1
        return AssistantTurn.model_validate(entry["response"])

    @property
    def exhausted(self) -> bool:
        return self._index >= len(self._entries)

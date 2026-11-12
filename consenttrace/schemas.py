"""Versioned data contracts shared by the platform, adapters, SDK and reports.

Everything that crosses a module boundary or lands on disk is one of these models,
so a malformed case, contract or trace fails loudly at the edge instead of deep
inside the rule engine.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION: Literal["1"] = "1"

_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- usage


class Usage(_Model):
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    cached_tokens: int = Field(default=0, ge=0)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            cached_tokens=self.cached_tokens + other.cached_tokens,
        )


# --------------------------------------------------------------------------- trace


class EventKind(StrEnum):
    USER_MESSAGE = "user_message"
    LLM_CALL = "llm_call"
    AGENT_REASONING = "agent_reasoning"  # reasoning text the API chose to return; not hidden CoT
    TOOL_CALL_ATTEMPT = "tool_call_attempt"
    WRITE_RECEIPT = "write_receipt"
    INJECTION = "injection"
    TOOL_RESULT = "tool_result"
    AGENT_MESSAGE = "agent_message"
    ERROR = "error"


class Source(StrEnum):
    USER = "user"  # trusted user channel, driven by the test controller
    AGENT = "agent"
    TOOL = "tool"  # low-trust: anything a tool returns
    HARNESS = "harness"  # the test platform itself


class EventStatus(StrEnum):
    OK = "ok"
    ERROR = "error"  # executed (or tried to) and failed
    REJECTED = "rejected"  # never executed: unknown tool or invalid arguments
    FAULTED = "faulted"  # the agent saw an injected fault instead of the real result


class TraceEvent(_Model):
    schema_version: Literal["1"] = SCHEMA_VERSION
    run_id: str | None = None
    case_id: str | None = None
    step_id: int = Field(ge=1)
    turn_id: int = Field(ge=0)
    kind: EventKind
    source: Source
    ts: datetime
    elapsed_ms: float = Field(ge=0)
    tool: str | None = None
    call_id: str | None = None
    args: dict[str, Any] | None = None
    result: Any = None
    status: EventStatus | None = None
    injection_id: str | None = None
    content: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class WriteOp(StrEnum):
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"


class WriteRecord(_Model):
    """A tool's own receipt for a state change it made."""

    table: str
    op: WriteOp
    pk: dict[str, Any]


# --------------------------------------------------------------------------- state


class TableSnapshot(_Model):
    pk: list[str]
    columns: list[str]
    rows: list[dict[str, Any]]


class StateSnapshot(_Model):
    schema_version: Literal["1"] = SCHEMA_VERSION
    tables: dict[str, TableSnapshot]
    digest: str
    captured_at_step: int | None = None


class RowChange(_Model):
    pk: dict[str, Any]
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    changed: list[str] = Field(default_factory=list)


class TableDiff(_Model):
    inserted: list[RowChange] = Field(default_factory=list)
    deleted: list[RowChange] = Field(default_factory=list)
    updated: list[RowChange] = Field(default_factory=list)

    @property
    def changes(self) -> list[RowChange]:
        return [*self.inserted, *self.deleted, *self.updated]


class StateDiff(_Model):
    tables: dict[str, TableDiff] = Field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not any(t.changes for t in self.tables.values())


# --------------------------------------------------------------------------- adapter I/O


class AdapterCapabilities(_Model):
    """What an adapter can really observe. Declaring more than it delivers is a bug."""

    output: bool
    trace: bool
    state: bool
    inject_tool_response: bool
    visible_reasoning: bool = False
    notes: str = ""


class TurnStatus(StrEnum):
    OK = "ok"
    BUDGET_EXCEEDED = "budget_exceeded"
    ERROR = "error"


class TurnResult(_Model):
    reply: str
    status: TurnStatus = TurnStatus.OK
    error: str | None = None
    llm_calls: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    usage: Usage = Field(default_factory=Usage)


# --------------------------------------------------------------------------- test cases


class UserEventType(StrEnum):
    REQUEST = "request"
    MODIFY = "modify"
    CONFIRM = "confirm"
    REVOKE = "revoke"
    DECLINE = "decline"
    INQUIRE = "inquire"  # asks for information; grants nothing


class UserEvent(_Model):
    """A trusted authorization event. Only the test controller may produce these."""

    type: UserEventType
    action: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_shape(self) -> UserEvent:
        if self.type is not UserEventType.INQUIRE and not self.action:
            raise ValueError(f"{self.type} event needs an action")
        if self.type in (UserEventType.REQUEST, UserEventType.MODIFY) and not self.params:
            raise ValueError(f"{self.type} event needs params")
        return self


class Turn(_Model):
    text: str = Field(min_length=1)
    events: list[UserEvent] = Field(default_factory=list)
    variants: list[str] = Field(default_factory=list)


class InjectionMode(StrEnum):
    APPEND_TEXT = "append_text"  # add low-trust text to a real result
    REPLACE_RESULT = "replace_result"
    POISON_RETRIEVAL = "poison_retrieval"  # insert a poisoned passage into retrieval results
    ERROR_BEFORE = "error_before"  # fail without executing: no write happens
    ERROR_AFTER = "error_after"  # execute (writes happen), then tell the agent it failed
    MALFORMED = "malformed"


class InjectionSpec(_Model):
    injection_id: str = Field(pattern=_ID_PATTERN)
    tool: str
    occurrence: int = Field(default=1, ge=1)  # inject on the n-th valid call of `tool`
    mode: InjectionMode
    payload: Any = None
    style: str | None = None
    field: str | None = None  # result key to append to / list to poison
    position: int = Field(default=0, ge=0)  # rank at which a poisoned item is inserted


class StateExpectation(_Model):
    """`count` rows of `table` match every column in `where` at the end of the case."""

    table: str
    where: dict[str, Any] = Field(default_factory=dict)
    count: int = Field(ge=0)


class ReplyCheck(_Model):
    """Deterministic content check on the agent's final reply of one turn (e.g. RAG faithfulness)."""

    turn: int = Field(ge=1)
    include_any: list[str] = Field(default_factory=list)  # at least one must appear
    exclude: list[str] = Field(default_factory=list)  # none may appear
    why: str = ""


class Expectation(_Model):
    task_should_complete: bool | None = None
    # Ground-truth rule ids; only meaningful for seeded mutants or human-labelled traces.
    expected_violations: list[str] = Field(default_factory=list)
    final_state: list[StateExpectation] = Field(default_factory=list)
    reply_checks: list[ReplyCheck] = Field(default_factory=list)
    notes: str = ""


class TestCase(_Model):
    __test__: ClassVar[bool] = False  # keep pytest from collecting this model

    schema_version: Literal["1"] = SCHEMA_VERSION
    case_id: str = Field(pattern=_ID_PATTERN)
    suite: str
    category: str
    title: str
    target: str
    fixture: str = "default"
    turns: list[Turn] = Field(min_length=1)
    injections: list[InjectionSpec] = Field(default_factory=list)
    expected: Expectation = Field(default_factory=Expectation)
    tags: list[str] = Field(default_factory=list)
    holdout: bool = False

    @model_validator(mode="after")
    def _unique_injection_ids(self) -> TestCase:
        ids = [inj.injection_id for inj in self.injections]
        if len(ids) != len(set(ids)):
            raise ValueError("injection_id values must be unique within a case")
        return self


# --------------------------------------------------------------------------- contracts


class RuleKind(StrEnum):
    REQUIRE_VALID_CONFIRMATION = "require_valid_confirmation"
    PARAMS_EQUAL_TO_CONFIRMATION = "params_equal_to_confirmation"
    FORBID_AFTER_REVOCATION = "forbid_after_revocation"
    SINGLE_EFFECT_PER_AUTHORIZATION = "single_effect_per_authorization"
    STATE_CHANGE_REQUIRES_AUTHORIZED_ACTION = "state_change_requires_authorized_action"
    RESPONSE_STATE_CONSISTENCY = "response_state_consistency"


ENTITY_RULES = frozenset({RuleKind.STATE_CHANGE_REQUIRES_AUTHORIZED_ACTION})


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SensitiveAction(_Model):
    action: str = Field(pattern=_ID_PATTERN)
    tool: str
    args_mapping: dict[str, str] = Field(min_length=1)  # business field -> tool argument
    writes: list[str] = Field(default_factory=list)


class RuleSpec(_Model):
    id: str = Field(pattern=_ID_PATTERN)
    kind: RuleKind
    action: str | None = None
    entity: str | None = None
    severity: Severity = Severity.HIGH
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_target(self) -> RuleSpec:
        if self.kind in ENTITY_RULES:
            if not self.entity:
                raise ValueError(f"rule {self.id}: {self.kind} needs an entity")
        elif not self.action:
            raise ValueError(f"rule {self.id}: {self.kind} needs an action")
        return self


class TestContract(_Model):
    __test__: ClassVar[bool] = False

    schema_version: Literal["1"] = SCHEMA_VERSION
    contract_id: str = Field(pattern=_ID_PATTERN)
    version: int = Field(ge=1)
    adapter: str
    state_entities: list[str] = Field(default_factory=list)
    sensitive_actions: list[SensitiveAction] = Field(min_length=1)
    rules: list[RuleSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_references(self) -> TestContract:
        actions = [a.action for a in self.sensitive_actions]
        if len(actions) != len(set(actions)):
            raise ValueError("sensitive action names must be unique")
        rule_ids = [r.id for r in self.rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("rule ids must be unique")
        known = set(actions)
        entities = set(self.state_entities)
        for rule in self.rules:
            if rule.action and rule.action not in known:
                raise ValueError(f"rule {rule.id} refers to unknown action {rule.action!r}")
            if rule.entity and rule.entity not in entities:
                raise ValueError(f"rule {rule.id} refers to undeclared entity {rule.entity!r}")
        return self

    def action(self, name: str) -> SensitiveAction:
        for a in self.sensitive_actions:
            if a.action == name:
                return a
        raise KeyError(name)


class AgentDescription(_Model):
    """What an adapter can tell about its agent without running a case (input to F09 contract drafting)."""

    target: str
    version: str
    tools: list[dict[str, Any]]  # function-calling schemas, exactly as the model sees them
    system_prompt: str = ""
    state_schema: dict[str, dict[str, list[str]]] = Field(default_factory=dict)  # table -> {columns, pk}
    notes: str = ""


# --------------------------------------------------------------------------- verdicts


class Outcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    UNSUPPORTED = "UNSUPPORTED"


class AssertionStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    UNSUPPORTED = "UNSUPPORTED"
    SKIPPED = "SKIPPED"  # e.g. an injection whose target tool was never called


class ViolationKind(StrEnum):
    ATTEMPT = "attempt_violation"  # unauthorized call, but nothing was written
    SIDE_EFFECT = "side_effect_violation"  # unauthorized call that changed state
    CLAIM = "claim_violation"  # what the agent told the user contradicts the real state


class AuthStatus(StrEnum):
    NONE = "none"
    PENDING = "pending"  # requested, not confirmed
    CONFIRMED = "confirmed"  # confirmed for the current params; authorizes one effect
    MODIFIED = "modified"  # params changed after a confirmation; the old one is void
    REVOKED = "revoked"
    CONSUMED = "consumed"  # the confirmation has been used by a real write


class AuthTransition(_Model):
    step: int
    turn: int
    action: str
    trigger: str  # user event type, or "consume"
    from_status: AuthStatus
    to_status: AuthStatus
    version: int
    params: dict[str, Any]
    confirmed_params: dict[str, Any] | None = None
    call_id: str | None = None


class SensitiveAttempt(_Model):
    step: int
    call_id: str
    action: str
    tool: str
    args: dict[str, Any]
    mapped: dict[str, Any]  # business fields, via the contract's args_mapping
    status_at_attempt: AuthStatus
    version: int
    reference_params: dict[str, Any] | None = None
    authorized: bool
    wrote: bool = False
    violated_rules: list[str] = Field(default_factory=list)


class Finding(_Model):
    rule_id: str
    kind: ViolationKind
    severity: Severity
    first_bad_step: int = Field(ge=1)
    reason: str
    expected: Any = None
    actual: Any = None
    evidence_refs: list[str] = Field(default_factory=list)


class AssertionResult(_Model):
    rule_id: str
    status: AssertionStatus
    detail: str = ""


class RunResult(_Model):
    schema_version: Literal["1"] = SCHEMA_VERSION
    run_id: str
    case_id: str
    rep: int = Field(default=0, ge=0)
    outcome: Outcome
    assertions: list[AssertionResult] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, str] = Field(default_factory=dict)
    mode: Literal["live", "replay", "scripted"]
    model_id: str | None = None
    agent_version: str


class RunSummary(_Model):
    schema_version: Literal["1"] = SCHEMA_VERSION
    run_id: str
    target: str
    agent_version: str
    mode: Literal["live", "replay", "scripted"]
    model_id: str | None = None
    contract_id: str
    suite: str
    reps: int
    executions: int
    counts: dict[str, int]
    usage: Usage = Field(default_factory=Usage)
    llm_calls: int = 0
    started_at: datetime
    finished_at: datetime
    config: dict[str, Any] = Field(default_factory=dict)

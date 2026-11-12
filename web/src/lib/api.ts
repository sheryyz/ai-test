// Types mirror consenttrace.schemas / consenttrace.core.analysis. The UI only renders these;
// every verdict and number is computed by the backend from stored evidence.

export type Outcome = "PASS" | "FAIL" | "ERROR" | "UNSUPPORTED";
export type AssertionStatus = Outcome | "SKIPPED";

export interface Ratio {
  num: number;
  den: number;
  rate: number | null;
}

export interface Usage {
  prompt_tokens: number;
  completion_tokens: number;
  cached_tokens: number;
}

export interface RunSummary {
  run_id: string;
  target: string;
  agent_version: string;
  mode: "live" | "replay" | "scripted";
  model_id: string | null;
  contract_id: string;
  suite: string;
  reps: number;
  executions: number;
  counts: Partial<Record<Outcome, number>>;
  usage: Usage;
  llm_calls: number;
  started_at: string;
  finished_at: string;
  config: Record<string, unknown>;
  status?: string;
  done?: number;
}

export interface Summ {
  executions: number;
  outcomes: Partial<Record<Outcome, number>>;
  auth_violation: Ratio;
  side_effect: Ratio;
  claim_violation: Ratio;
  task_success: Ratio;
  reply_faithful: Ratio;
  attack_success: Ratio;
  injection_not_reached: number;
  tokens: number;
  avg_duration_ms: number | null;
  cases: number;
  pass_k: Ratio;
}

export interface ExecFact {
  case_id: string;
  rep: number;
  outcome: Outcome;
  rules: string[];
  auth_violation: boolean;
  side_effect: boolean;
  claim_violation: boolean;
  task_ok: boolean | null;
  reply_ok: boolean | null;
  first_bad_step: number | null;
  tokens: number;
  duration_ms: number;
}

export interface CaseRow {
  case_id: string;
  category: string;
  title: string;
  tags: string[];
  reps: ExecFact[];
  pass_all: boolean;
  violation_reps: number;
  consistent: boolean;
}

export interface Breakdown {
  run_id: string;
  status: string;
  summary: RunSummary | null;
  config: Record<string, unknown>;
  totals: Summ & { inconsistent_cases: number };
  categories: Record<string, Summ>;
  cases: CaseRow[];
  rule_hits: Record<string, number>;
}

export interface UserEvent {
  type: "request" | "modify" | "confirm" | "revoke" | "decline" | "inquire";
  action: string | null;
  params: Record<string, unknown>;
}

export interface TestCase {
  case_id: string;
  suite: string;
  category: string;
  title: string;
  target: string;
  fixture: string;
  turns: { text: string; events: UserEvent[]; variants: string[] }[];
  injections: { injection_id: string; tool: string; occurrence: number; mode: string; payload: unknown; style: string | null }[];
  expected: { task_should_complete: boolean | null; final_state: { table: string; where: Record<string, unknown>; count: number }[]; notes: string };
  tags: string[];
}

export type EventKind =
  | "user_message"
  | "llm_call"
  | "agent_reasoning"
  | "tool_call_attempt"
  | "write_receipt"
  | "injection"
  | "tool_result"
  | "agent_message"
  | "error";

export interface TraceEvent {
  step_id: number;
  turn_id: number;
  kind: EventKind;
  source: "user" | "agent" | "tool" | "harness";
  ts: string;
  elapsed_ms: number;
  tool: string | null;
  call_id: string | null;
  args: Record<string, unknown> | null;
  result: unknown;
  status: "ok" | "error" | "rejected" | "faulted" | null;
  injection_id: string | null;
  content: string | null;
  meta: Record<string, unknown>;
}

export type AuthStatus = "none" | "pending" | "confirmed" | "modified" | "revoked" | "consumed";

export interface AuthTransition {
  step: number;
  turn: number;
  action: string;
  trigger: string;
  from_status: AuthStatus;
  to_status: AuthStatus;
  version: number;
  params: Record<string, unknown>;
  confirmed_params: Record<string, unknown> | null;
  call_id: string | null;
}

export interface SensitiveAttempt {
  step: number;
  call_id: string;
  action: string;
  tool: string;
  args: Record<string, unknown>;
  mapped: Record<string, unknown>;
  status_at_attempt: AuthStatus;
  version: number;
  reference_params: Record<string, unknown> | null;
  authorized: boolean;
  wrote: boolean;
  violated_rules: string[];
}

export interface Finding {
  rule_id: string;
  kind: "attempt_violation" | "side_effect_violation" | "claim_violation";
  severity: "critical" | "high" | "medium" | "low";
  first_bad_step: number;
  reason: string;
  expected: unknown;
  actual: unknown;
  evidence_refs: string[];
}

export interface RunResult {
  run_id: string;
  case_id: string;
  rep: number;
  outcome: Outcome;
  assertions: { rule_id: string; status: AssertionStatus; detail: string }[];
  findings: Finding[];
  errors: string[];
  metrics: Record<string, unknown>;
  mode: string;
  model_id: string | null;
  agent_version: string;
}

export interface TableSnapshot {
  pk: string[];
  columns: string[];
  rows: Record<string, unknown>[];
}
export interface StateSnapshot {
  tables: Record<string, TableSnapshot>;
  digest: string;
}
export interface RowChange {
  pk: Record<string, unknown>;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  changed: string[];
}
export interface StateDiff {
  tables: Record<string, { inserted: RowChange[]; deleted: RowChange[]; updated: RowChange[] }>;
}

export interface CaseBundle {
  run_id: string;
  case: TestCase | null;
  verdict: RunResult;
  trace: TraceEvent[];
  auth: { transitions: AuthTransition[]; attempts: SensitiveAttempt[] } | null;
  state_before: StateSnapshot | null;
  state_after: StateSnapshot | null;
  state_diff: StateDiff | null;
  contract: { contract_id: string; rules: { id: string; kind: string; action: string | null; entity: string | null; severity: string }[] } | null;
  reps: number[];
}

export interface TargetInfo {
  name: string;
  description: string;
  versions: string[];
  suites: Record<string, number>;
  contract_id: string | null;
  rules: number;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return (await res.json()) as T;
}

export const api = {
  targets: () => get<TargetInfo[]>("/api/targets"),
  runs: () => get<RunSummary[]>("/api/runs"),
  run: (id: string) => get<Breakdown>(`/api/runs/${encodeURIComponent(id)}`),
  caseBundle: (id: string, caseId: string, rep: number) =>
    get<CaseBundle>(`/api/runs/${encodeURIComponent(id)}/cases/${encodeURIComponent(caseId)}/${rep}`),
  suite: (target: string, suite: string) => get<TestCase[]>(`/api/targets/${target}/suites/${suite}`),
  settings: () => get<{ live_available: boolean; model: string | null }>("/api/settings"),
  contract: (target: string) => get<{ contract: unknown; yaml: string }>(`/api/targets/${target}/contract`),
  async startRun(body: Record<string, unknown>): Promise<{ run_id: string; total: number }> {
    const res = await fetch("/api/runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(typeof detail.detail === "string" ? detail.detail : JSON.stringify(detail.detail));
    }
    return res.json();
  },
};

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
  target: string | null;
  transport: string;
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
  subsets: string[];
  contract_id: string | null;
  rules: number;
  service_url: string | null;
  in_process: boolean;
  origin: string;
  fixed_versions: Record<string, string>;
  like: string | null;
}

// ------------------------------------------------------------------ agents under test, defects, workspace

export interface Capabilities {
  output: boolean;
  trace: boolean;
  state: boolean;
  inject_tool_response: boolean;
  visible_reasoning: boolean;
  notes: string;
}

export interface AgentInfo {
  protocol: string;
  name: string;
  description: string;
  versions: string[];
  capabilities: Capabilities;
  llm: { live_available: boolean; model: string | null; replay: boolean };
}

export interface AgentStatus {
  name: string;
  url: string | null;
  online: boolean;
  info: AgentInfo | null;
  error: string | null;
  managed: boolean;
  launchable: boolean;
}

export interface ProbeReport {
  url: string;
  ok: boolean;
  info: AgentInfo | null;
  checks: { key: string; title: string; status: "PASS" | "FAIL" | "SKIP"; detail: string }[];
  describe?: AgentDescription | null;
  registered?: {
    name: string;
    origin: string;
    versions: string[];
    contract_id: string;
    rules: number;
    actions: { action: string; tool: string }[];
    suites: Record<string, number>;
    fixed_versions: Record<string, string>;
  } | null;
  businesses?: Business[];
}

export type DefectKind = "side_effect" | "attempt" | "claim" | "task";
export type DefectStatus = "fixed_verified" | "mitigated" | "fix_failed" | "awaiting_retest" | "open";

export interface Occurrence {
  run_id: string;
  rep: number;
  mode: "live" | "replay";
  transport: string;
  suite: string;
  finished_at: string;
  kinds: DefectKind[];
  rules: string[];
  first_bad_step: number | null;
  replay_from: string | null;
  model_id: string | null;
}

export interface Retest {
  run_id: string;
  version: string;
  mode: string;
  transport: string;
  suite: string;
  finished_at: string;
  outcomes: { rep: number; outcome: Outcome; rules: string[]; kinds: DefectKind[] }[];
  passed: number;
  total: number;
  is_retest: boolean;
}

export interface Defect {
  id: string;
  target: string;
  version: string;
  case_id: string;
  title: string;
  category: string | null;
  has_injection: boolean;
  occurrences: Occurrence[];
  kinds: DefectKind[];
  kind: DefectKind;
  kind_label: string;
  rules: string[];
  executions: { live: number; live_fail: number; replay: number; replay_fail: number };
  first: Occurrence;
  latest: Occurrence;
  fixed_version: string | null;
  retest: Retest | null;
  status: DefectStatus;
  status_label: string;
  last_seen: string;
}

export interface DefectSummary {
  total: number;
  by_status: Record<DefectStatus, number>;
  by_kind: Record<DefectKind, number>;
  status_labels: Record<DefectStatus, string>;
  kind_labels: Record<DefectKind, string>;
}

export interface ReplaySource {
  run_id: string;
  mode: string;
  suite: string;
  reps: number;
  finished_at: string;
}

export interface WorkspaceAgent extends AgentStatus {
  description: string;
  origin: string;
  versions: string[];
  suites: Record<string, number>;
  fixed_versions: Record<string, string>;
  in_process: boolean;
  last_run: { run_id: string; version: string; suite: string; mode: string; counts: Partial<Record<Outcome, number>>; executions: number; finished_at: string } | null;
  like: string | null; // set for an agent the user connected from the console
  registered_at: string | null;
}

export interface AttackRates {
  executions: number;
  errors: number;
  not_reached: number;
  reached: number;
  attempt: Ratio;
  write: Ratio;
}

export interface AttackData {
  spec: {
    spec_id: string;
    styles: Record<string, { name: string; description: string; placement: { mode: string; field: string | null; position: number } }>;
    goals: Record<string, { name: string; action: string }>;
    combos: { style: string; goal: string; carrier: string }[];
  };
  library: {
    header: Record<string, string>;
    entries: { attack_id: string; style: string; goal: string; carrier: string; text: string; title: string | null; technique: string | null; round: number; parent?: string }[];
    round2: Record<string, string> | null;
  };
  generation: { accepted: number; rejected: number; model: string; tokens: number; rejections: { style: string; goal: string; text: string; title?: string; problems: string[] }[] } | null;
  runs: {
    run_id: string;
    suite: string;
    round: number;
    version: string;
    mode: string;
    model_id: string | null;
    totals: AttackRates;
    by_style: Record<string, AttackRates>;
    by_goal: Record<string, AttackRates>;
    successes: { case_id: string; rep: number; attempted: boolean; wrote: boolean; first_bad_step: number | null }[];
  }[];
}

export interface KBReport {
  target: string;
  transport: string;
  checked_at: string;
  passages: number;
  knowledge: { id: string; title: string; text: string }[];
  issues: { kind: string; rule: string; passages: string[]; detail: string; llm: { conflict: boolean | null; reason: string } | null }[];
  counts: { error: number; redundancy: number; conflict: number };
  retrieval: ({
    k: number;
    queries: number;
    recall_at_1: Ratio;
    mrr: number | null;
    rows: { query: string; gold: string; rank: number | null; top: string[] }[];
  } & Record<string, unknown>) | null;
  queries_source: { model?: string; path: string; count: number };
  llm_review: { model: string; pairs: { pair: string[]; conflict: boolean | null; reason: string }[] } | null;
  seeded: { planted: number; detected: number; faults: { kind: string; rule: string; passages: string[]; detected: boolean }[]; false_alarms: unknown[] };
  poisoning: {
    passages: number;
    flagged: number;
    llm_flagged: number | null;
    rows: { id: string; title: string; text: string; flagged: boolean; against: string[]; llm?: { pair: string[]; conflict: boolean | null; reason: string }[]; llm_flagged?: boolean }[];
  };
}

export interface HumanLabel {
  annotator: string;
  violation: "none" | "attempt" | "side_effect";
  types: ("unconfirmed" | "params_changed" | "after_revocation" | "repeated" | "other")[];
  first_bad_step: number | null;
  task: "done" | "not_done" | "na";
  note: string;
}

export interface BlindItem {
  blind_id: string;
  target: string;
  steps: { step: number; turn: number; who: "user" | "agent" | "tool_call" | "tool_result"; text?: string; tool?: string; args?: unknown; result?: unknown; status?: string }[];
  state_diff: StateDiff | null;
  label: (HumanLabel & { labeled_at: string }) | null;
}

export interface AnnotationScore {
  sample: number;
  labeled: number;
  annotators: string[];
  primary: string | null;
  human_positives: number;
  oracles: Record<string, { label: string; violation: Confusion; side_effect: Confusion; kappa: number | null; first_step: Ratio; by_stratum: Record<string, Confusion> }>;
  inter_annotator: { annotators: string[]; items: number; kappa: number | null; raw_agreement: number | null } | null;
}

export interface Workspace {
  agents: WorkspaceAgent[];
  defects: { summary: DefectSummary; recent: Defect[] };
  recent_runs: {
    run_id: string;
    target: string;
    version: string;
    suite: string;
    mode: string;
    transport: string;
    counts: Partial<Record<Outcome, number>>;
    executions: number;
    finished_at: string;
    retest_of: { defect: string } | null;
  }[];
  acceptance: { key: string; title: string; done: boolean; detail: string; href: string }[];
}

// ------------------------------------------------------------------ experiment analysis

export interface Confusion {
  tp: number;
  fp: number;
  fn: number;
  tn: number;
  recall: number | null;
  fpr: number | null;
  precision: number | null;
}

export interface OracleScore {
  violation: Confusion;
  side_effect: Confusion;
  claim: Confusion;
  localization: { num: number; den: number; rate: number | null };
}

export interface JudgeSummary {
  view: string;
  model: string;
  prompt_version: string;
  executions: number;
  samples: number;
  unusable_answers: number;
  self_consistency: { agree: number; total: number; rate: number | null };
}

export interface SuiteVersion {
  version: string;
  run_id: string;
  model_id: string | null;
  reps: number;
  totals: Summ;
  task_retention: Ratio;
}

export interface PrCounts {
  tp: number;
  fp: number;
  fn: number;
}

export interface Analysis {
  suites: { target: string; suite: string; cases: number; versions: SuiteVersion[]; steps: { a: string; b: string; changes: Record<string, number> }[] }[];
  phrasing: {
    target: string;
    version: string;
    run_id: string;
    base_run: string | null;
    bases: number;
    variants: number;
    variant_outcome_split: Ratio;
    variant_violation_split: Ratio;
    rep_outcome_split: Ratio;
    rep_violation_split: Ratio;
    outside_base: Ratio;
    split_bases: string[];
  }[];
  detectors: {
    run_id: string;
    executions: number;
    positives: number;
    scores: Record<string, OracleScore>;
    labels: Record<string, string>;
    llm_judge: JudgeSummary[];
    real_runs_from: string | null;
    real_runs: { run_id: string; executions: number; flagged: Record<string, number>; agreement_with_ours: Record<string, number>; llm_judge: JudgeSummary[] }[];
  } | null;
  performance: {
    target: string;
    suite: string;
    version: string;
    reps: number;
    points: {
      concurrency: number;
      run_id: string;
      executions: number;
      latency_s: { p50: number | null; p90: number | null; p95: number | null; max: number | null };
      model_latency_s: { p50: number | null; p95: number | null };
      errors: Ratio;
      rate_limited: number;
      wall_s: number;
      throughput_per_min: number | null;
      llm_calls_mean: number | null;
    }[];
  }[];
  drafts: {
    target: string;
    run_id: string;
    model: string | null;
    on_runs: string[];
    drafts: {
      draft: number;
      valid: boolean;
      attempts: number;
      sensitive_actions?: PrCounts;
      args_mapping?: PrCounts;
      rules?: PrCounts & { missing: string[]; extra: string[] };
      edits_to_gold?: number;
      same_authorization_verdict?: Ratio;
      same_claim_verdict?: Ratio;
      same_outcome?: Ratio;
      executions?: number;
    }[];
  }[];
}

export interface AgentDescription {
  target: string;
  version: string;
  tools: { type: string; function: { name: string; description: string; parameters: { properties?: Record<string, { type?: string; description?: string }>; required?: string[] } } }[];
  system_prompt: string;
  state_schema: Record<string, { columns: string[]; pk: string[] }>;
}

export interface PrDetail extends PrCounts {
  precision: number | null;
  recall: number | null;
  extra: string[];
  missing: string[];
}

export interface StructureScore {
  sensitive_actions: PrDetail;
  args_mapping: PrDetail;
  writes: PrDetail;
  rules: PrDetail;
  edits_to_gold: Record<string, number>;
}

export interface DraftSet {
  run_id: string | null;
  model?: string;
  prompt_version?: string;
  drafts: {
    draft: number;
    valid: boolean;
    attempts: number;
    errors: string[];
    rationale: Record<string, string>;
    structure: StructureScore | null;
    yaml: string | null;
    accepted: { edits_from_draft: Record<string, number>; accepted_at: string } | null;
  }[];
}

export interface ContractCheck {
  ok: boolean;
  errors: string[];
  vs_gold?: StructureScore;
  edits_from_draft?: Record<string, number> | null;
}

/** A 401 from any call means the session ended: the app shell listens and shows the sign-in page. */
export const UNAUTHORIZED_EVENT = "consenttrace:unauthorized";

function checkAuth(res: Response): void {
  if (res.status === 401) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
}

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  if (window.__CONSENTTRACE_STATIC__) throw new Error("离线报告是只读的");
  const res = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  checkAuth(res);
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(typeof detail.detail === "string" ? detail.detail : JSON.stringify(detail.detail));
  }
  return (await res.json()) as T;
}

function post<T>(path: string, body: unknown): Promise<T> {
  return send<T>("POST", path, body);
}

declare global {
  interface Window {
    // set by `consenttrace report`: every API response the page needs, keyed by path
    __CONSENTTRACE_STATIC__?: Record<string, unknown>;
  }
}

async function get<T>(path: string): Promise<T> {
  const embedded = window.__CONSENTTRACE_STATIC__;
  if (embedded) {
    if (path in embedded) return embedded[path] as T;
    throw new Error(`静态报告中没有包含 ${path}（只读的离线报告）`);
  }
  const res = await fetch(path);
  checkAuth(res);
  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try {
      const parsed = JSON.parse(text) as { detail?: unknown };
      if (typeof parsed.detail === "string") detail = parsed.detail;
    } catch {
      /* not JSON: show the raw text */
    }
    throw new Error(`${res.status} ${detail}`);
  }
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
  analysis: () => get<Analysis>("/api/analysis"),
  describe: (target: string) => get<AgentDescription>(`/api/targets/${target}/describe`),
  drafts: (target: string) => get<DraftSet>(`/api/targets/${target}/drafts`),
  checkContract: (target: string, body: { yaml: string; draft_run: string | null; draft: number | null }) =>
    post<ContractCheck>(`/api/targets/${target}/contract/check`, body),
  acceptContract: (target: string, body: { yaml: string; draft_run: string | null; draft: number | null }) =>
    post<{ edits_from_draft: Record<string, number>; accepted_at: string }>(`/api/targets/${target}/contract/accept`, body),
  workspace: () => get<Workspace>("/api/workspace"),
  annotationItems: () => get<{ n: number; seed: number; items: { blind_id: string; labeled_by: string[] }[]; annotators: string[] }>("/api/annotation"),
  annotationItem: (id: string, annotator: string) => get<BlindItem>(`/api/annotation/${encodeURIComponent(id)}?annotator=${encodeURIComponent(annotator)}`),
  saveLabel: (id: string, body: HumanLabel) => post<HumanLabel>(`/api/annotation/${encodeURIComponent(id)}`, body),
  annotationScore: () => get<AnnotationScore>("/api/annotation/score"),
  kb: (target: string) => get<KBReport>(`/api/kb/${encodeURIComponent(target)}`),
  attacks: (target: string) => get<AttackData>(`/api/attacks/${encodeURIComponent(target)}`),
  agents: () => get<AgentStatus[]>("/api/agents"),
  startAgent: (name: string) => post<AgentStatus>(`/api/agents/${encodeURIComponent(name)}/start`, {}),
  probe: (body: { url?: string; target?: string; version?: string }) => post<ProbeReport>("/api/agents/probe", body),
  defects: () => get<{ summary: DefectSummary; defects: Defect[] }>("/api/defects"),
  retest: (body: { id: string; mode: "live" | "replay"; transport: "http" | "inprocess"; reps?: number }) =>
    post<{ run_id: string; total: number; version: string; replay_from: string | null }>("/api/defects/retest", body),
  replaySourcesForCase: (target: string, version: string, caseId: string) =>
    get<ReplaySource[]>(`/api/targets/${encodeURIComponent(target)}/replay-sources?version=${encodeURIComponent(version)}&case=${encodeURIComponent(caseId)}`),
  replaySources: (target: string, version: string, suite: string) =>
    get<ReplaySource[]>(`/api/targets/${encodeURIComponent(target)}/replay-sources?version=${encodeURIComponent(version)}&suite=${encodeURIComponent(suite)}`),
  startRun: (body: Record<string, unknown>) => post<{ run_id: string; total: number }>("/api/runs", body),
  authMe: async (): Promise<AuthState> => {
    const res = await fetch("/api/auth/me");
    if (!res.ok) return { enabled: false, user: null, demo: null }; // an older server without sign-in
    return res.json();
  },
  login: (username: string, password: string) => post<{ user: AuthUser }>("/api/auth/login", { username, password }),
  logout: () => post<{ ok: boolean }>("/api/auth/logout", {}),
  registerAgent: (body: { name: string; url: string; like: string; description: string }) =>
    post<{ name: string; versions: string[]; like: string; tools_checked: boolean }>("/api/agents/register", body),
  unregisterAgent: (name: string) => send<{ ok: boolean }>("DELETE", `/api/agents/${encodeURIComponent(name)}`),
};

export interface AuthUser {
  username: string;
  display_name: string;
}

export interface AuthState {
  enabled: boolean;
  user: AuthUser | null;
  demo: { username: string; password: string } | null;
}

export interface Business {
  name: string;
  description: string;
  contract_id: string;
  rules: number;
  sensitive_tools: string[];
  missing: string[];
  checked: boolean;
  compatible: boolean;
  suites: Record<string, number>;
}

import { useEffect, useMemo, useState } from "react";
import { Card, ErrorNote, Loading, Pill, Segmented } from "../components/ui";
import { api, type ContractCheck, type PrDetail } from "../lib/api";
import { useAsync } from "../lib/util";

const EDIT_NAMES: Record<string, string> = {
  actions_added: "增加敏感动作",
  actions_removed: "删除敏感动作",
  args_changed: "改动参数映射",
  rules_added: "增加规则",
  rules_removed: "删除规则",
};

function pr(x?: PrDetail): string {
  return x ? `精确 ${x.tp}/${x.tp + x.fp} · 召回 ${x.tp}/${x.tp + x.fn}` : "—";
}

function signature(s: string): string {
  // "('require_valid_confirmation', 'book_flight')" -> "require_valid_confirmation · book_flight"
  return s.replace(/^\('|'\)$/g, "").replace("', '", " · ");
}

export function Workbench() {
  const targets = useAsync(() => api.targets(), []);
  const [target, setTarget] = useState("travel");
  const desc = useAsync(() => api.describe(target), [target]);
  const drafts = useAsync(() => api.drafts(target), [target]);
  const gold = useAsync(() => api.contract(target), [target]);
  const [draftNo, setDraftNo] = useState(1);
  const [text, setText] = useState("");
  const [check, setCheck] = useState<ContractCheck | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const readOnly = Boolean(window.__CONSENTTRACE_STATIC__);

  const draft = drafts.data?.drafts.find((d) => d.draft === draftNo) ?? drafts.data?.drafts[0];
  useEffect(() => {
    setText(draft?.yaml ?? "");
    setCheck(null);
    setNote(null);
  }, [draft?.yaml, target]);
  const sensitive = useMemo(() => new Set([...text.matchAll(/tool:\s*(\S+)/g)].map((m) => m[1])), [text]);
  const body = { yaml: text, draft_run: drafts.data?.run_id ?? null, draft: draft?.draft ?? null };

  async function run(kind: "check" | "accept") {
    setBusy(true);
    setNote(null);
    try {
      const result = await api.checkContract(target, body);
      setCheck(result);
      if (kind === "accept" && result.ok) {
        const saved = await api.acceptContract(target, body);
        setNote(`已保存（${saved.accepted_at}），相对草稿共 ${saved.edits_from_draft.total} 处人工修改`);
        drafts.reload();
      }
    } catch (e) {
      setNote(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (targets.error) return <ErrorNote error={targets.error} />;
  const score = check?.vs_gold ?? draft?.structure ?? undefined;
  return (
    <div className="space-y-5">
      <section className="card flex flex-wrap items-end justify-between gap-4 p-6">
        <div className="max-w-3xl">
          <h1 className="text-2xl font-semibold text-ink">契约工作台</h1>
          <p className="mt-2 text-sm leading-relaxed text-ink-2">
            AI 只读取被测 Agent 的工具定义、系统提示词和数据库结构，从规则算子库中起草测试契约（consenttrace draft-contract）。在这里核对、编辑、校验，接受后记录相对草稿的人工修改量；右栏与人工编写的金标准比较。
          </p>
        </div>
        {targets.data && (
          <Segmented label="目标" value={target} onChange={(v) => { setTarget(v); setDraftNo(1); }} options={targets.data.map((t) => ({ value: t.name, label: t.name }))} />
        )}
      </section>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.3fr)_minmax(0,1fr)]">
        <Card title="被测 Agent 的工具" subtitle={desc.data ? `${desc.data.target} ${desc.data.version} · 工具定义里没有标注副作用` : undefined}>
          {desc.error && <ErrorNote error={desc.error} />}
          {!desc.data && !desc.error && <Loading what="工具定义" />}
          <div className="space-y-3">
            {desc.data?.tools.map((t) => (
              <div key={t.function.name} className="rounded-lg p-3" style={{ background: "var(--surface-2)" }}>
                <div className="flex items-center gap-2">
                  <span className="mono text-[13px] font-semibold text-ink">{t.function.name}</span>
                  {sensitive.has(t.function.name) && <Pill color="var(--critical)">敏感</Pill>}
                </div>
                <p className="mt-1 text-xs text-ink-2">{t.function.description}</p>
                <div className="mono mt-1.5 text-[11px] text-muted">
                  ({Object.keys(t.function.parameters.properties ?? {}).join(", ") || "无参数"})
                </div>
              </div>
            ))}
            {desc.data && (
              <div className="text-xs text-muted">
                数据库：{Object.entries(desc.data.state_schema).map(([table, s]) => `${table}(${s.columns.length} 列)`).join("、")}
              </div>
            )}
          </div>
        </Card>

        <Card
          title="AI 起草的契约"
          subtitle={drafts.data?.run_id ? `${drafts.data.model} · ${drafts.data.prompt_version} · ${drafts.data.run_id}` : "还没有草稿：uv run consenttrace draft-contract --target " + target}
          right={
            drafts.data && drafts.data.drafts.length > 1 ? (
              <Segmented label="草稿" value={String(draft?.draft ?? 1)} onChange={(v) => setDraftNo(Number(v))} options={drafts.data.drafts.map((d) => ({ value: String(d.draft), label: `草稿 ${d.draft}` }))} />
            ) : undefined
          }
        >
          {drafts.error && <ErrorNote error={drafts.error} />}
          {draft && (
            <>
              <textarea
                aria-label="契约 YAML"
                value={text}
                onChange={(e) => setText(e.target.value)}
                readOnly={readOnly}
                spellCheck={false}
                className="mono h-[420px] w-full resize-y rounded-lg p-3 text-[12px] leading-relaxed text-ink"
                style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}
              />
              {!readOnly && (
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <button className="rounded-md px-3 py-1.5 text-sm text-ink disabled:opacity-50" style={{ background: "var(--surface-3)" }} disabled={busy} onClick={() => run("check")}>校验</button>
                  <button className="rounded-md px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50" style={{ background: "var(--s1)" }} disabled={busy} onClick={() => run("accept")}>接受并保存</button>
                  <button className="rounded-md px-3 py-1.5 text-sm text-ink disabled:opacity-50" style={{ background: "var(--surface-3)" }} disabled={busy || text === draft.yaml} onClick={() => setText(draft.yaml ?? "")}>恢复草稿</button>
                  {draft.accepted && <span className="text-xs text-muted">上次接受：{draft.accepted.accepted_at}，人工修改 {draft.accepted.edits_from_draft.total} 处</span>}
                </div>
              )}
              {note && <p className="mt-2 text-xs text-ink-2">{note}</p>}
              {check && !check.ok && (
                <ul className="mt-2 list-disc pl-5 text-xs" style={{ color: "var(--critical)" }}>
                  {check.errors.map((e) => <li key={e}>{e}</li>)}
                </ul>
              )}
              {check?.edits_from_draft && (
                <p className="mt-2 text-xs text-ink-2">
                  相对草稿：
                  {Object.entries(EDIT_NAMES).map(([k, label]) => `${label} ${check.edits_from_draft![k]}`).join("，")}（共 {check.edits_from_draft.total} 处）
                </p>
              )}
              <details className="mt-4">
                <summary className="cursor-pointer text-xs text-ink-2">起草理由（{Object.keys(draft.rationale ?? {}).length} 条）</summary>
                <dl className="mt-2 space-y-1.5 text-xs">
                  {Object.entries(draft.rationale ?? {}).map(([k, v]) => (
                    <div key={k}>
                      <dt className="mono text-ink">{k}</dt>
                      <dd className="text-ink-2">{v}</dd>
                    </div>
                  ))}
                </dl>
              </details>
            </>
          )}
        </Card>

        <Card title="与金标准比较" subtitle={check?.vs_gold ? "当前编辑内容" : "草稿原样"}>
          {score ? (
            <div className="space-y-3 text-xs">
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5">
                <dt className="text-muted">敏感动作</dt>
                <dd className="tabular text-ink-2">{pr(score.sensitive_actions)}</dd>
                <dt className="text-muted">参数映射</dt>
                <dd className="tabular text-ink-2">{pr(score.args_mapping)}</dd>
                <dt className="text-muted">规则</dt>
                <dd className="tabular text-ink-2">{pr(score.rules)}</dd>
                <dt className="text-muted">改到金标准</dt>
                <dd className="tabular text-ink-2">{score.edits_to_gold.total} 处</dd>
              </dl>
              <RuleDiff title="金标准有、契约缺少" items={score.rules.missing} />
              <RuleDiff title="契约多出（金标准没有）" items={score.rules.extra} />
              {score.args_mapping.extra.length + score.args_mapping.missing.length > 0 && (
                <RuleDiff title="参数映射差异" items={[...score.args_mapping.missing.map((x) => `缺少 ${x}`), ...score.args_mapping.extra.map((x) => `多出 ${x}`)]} raw />
              )}
              <p className="text-muted">规则按"算子 + 工具 / 表"比较，与命名无关。多出的规则不一定是错的，只是金标准没有。</p>
            </div>
          ) : (
            <p className="text-sm text-muted">选择或校验一份契约后显示。</p>
          )}
          {gold.data && (
            <details className="mt-4">
              <summary className="cursor-pointer text-xs text-ink-2">金标准契约（人工编写）</summary>
              <pre className="mono mt-2 max-h-[360px] overflow-auto rounded-lg p-3 text-[11px] text-ink-2" style={{ background: "var(--surface-2)" }}>{gold.data.yaml}</pre>
            </details>
          )}
        </Card>
      </div>
    </div>
  );
}

function RuleDiff({ title, items, raw = false }: { title: string; items: string[]; raw?: boolean }) {
  if (items.length === 0) return null;
  return (
    <div>
      <div className="mb-1 text-muted">{title}（{items.length}）</div>
      <ul className="space-y-1">
        {items.map((s) => (
          <li key={s} className="mono rounded px-2 py-1 text-[11px] text-ink-2" style={{ background: "var(--surface-2)" }}>
            {raw ? s : signature(s)}
          </li>
        ))}
      </ul>
    </div>
  );
}

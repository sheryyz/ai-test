import { useState } from "react";
import { Card, ErrorNote, Loading, Pill, Segmented } from "../components/ui";
import { api, type UserEvent } from "../lib/api";
import { ACTION_NAMES, CATEGORY_NAMES, short, useAsync } from "../lib/util";

function eventText(e: UserEvent): string {
  const verb = { request: "请求", modify: "修改", confirm: "确认", revoke: "撤销", decline: "拒绝", inquire: "仅询问" }[e.type];
  const params = Object.entries(e.params).map(([k, v]) => `${k}=${v}`).join(" ");
  return `${verb}${e.action ? `·${ACTION_NAMES[e.action] ?? e.action}` : ""}${params ? ` ${params}` : ""}`;
}

export function Suite() {
  const [suite, setSuite] = useState("main");
  const [cat, setCat] = useState("all");
  const cases = useAsync(() => api.suite("travel", suite), [suite]);
  const contract = useAsync(() => api.contract("travel"), []);
  if (cases.error) return <ErrorNote error={cases.error} />;
  if (!cases.data) return <Loading what="用例" />;
  const shown = cases.data.filter((c) => cat === "all" || c.category === cat);
  return (
    <div className="space-y-5">
      <Card
        title="用例库"
        subtitle="每条用例由用户原话与可信授权事件组成；事件是判定的真值，Agent 只能看到原话"
        right={
          <div className="flex flex-wrap gap-2">
            <Segmented label="套件" value={suite} onChange={setSuite} options={[{ value: "main", label: "主套件" }, { value: "smoke", label: "冒烟" }]} />
            <select value={cat} onChange={(e) => setCat(e.target.value)} className="rounded-md px-2 py-1 text-xs" style={{ background: "var(--surface-2)", border: "1px solid var(--border)", color: "var(--ink)" }}>
              <option value="all">全部类别（{cases.data.length}）</option>
              {Object.entries(CATEGORY_NAMES).map(([k, v]) => (
                <option key={k} value={k}>
                  {k} {v}（{cases.data!.filter((c) => c.category === k).length}）
                </option>
              ))}
            </select>
          </div>
        }
      >
        <div className="grid gap-3 lg:grid-cols-2">
          {shown.map((c) => (
            <article key={c.case_id} className="rounded-lg p-3.5" style={{ border: "1px solid var(--border)", background: "var(--surface-2)" }}>
              <div className="flex flex-wrap items-center gap-2">
                <Pill>{c.category}</Pill>
                <span className="mono text-[11px] text-muted">{c.case_id}</span>
                {c.fixture !== "default" && <Pill>{c.fixture}</Pill>}
              </div>
              <h3 className="mt-1 text-sm font-semibold text-ink">{c.title}</h3>
              <ol className="mt-2 space-y-1.5">
                {c.turns.map((t, i) => (
                  <li key={i} className="text-xs">
                    <span className="mr-1.5 text-muted">{i + 1}.</span>
                    <span className="text-ink">{short(t.text, 90)}</span>
                    <div className="mt-0.5 flex flex-wrap gap-1 pl-4">
                      {t.events.map((e, j) => (
                        <Pill key={j} color="var(--s1)">
                          {eventText(e)}
                        </Pill>
                      ))}
                    </div>
                  </li>
                ))}
              </ol>
              {c.injections.length > 0 && (
                <div className="mt-2 space-y-1">
                  {c.injections.map((inj) => (
                    <div key={inj.injection_id} className="rounded-md px-2 py-1 text-[11px]" style={{ background: "var(--s7-wash)" }}>
                      <b className="text-ink">注入 {inj.injection_id}</b>
                      <span className="text-ink-2"> · {inj.tool} 第 {inj.occurrence} 次 · {inj.mode}{inj.style ? ` · ${inj.style}` : ""}</span>
                      {typeof inj.payload === "string" && <div className="mt-0.5 text-ink-2">{short(inj.payload, 110)}</div>}
                    </div>
                  ))}
                </div>
              )}
              <div className="mt-2 text-[11px] text-muted">
                期望终态：{c.expected.final_state.map((s) => `${s.table}${JSON.stringify(s.where)} = ${s.count}`).join("；") || "—"}
              </div>
            </article>
          ))}
        </div>
      </Card>
      <Card title="测试契约（金标准）" subtitle="业务知识只存在于契约中，规则引擎里没有任何业务常量">
        {contract.data ? <pre className="mono overflow-auto rounded-md p-3 text-[11px] leading-relaxed text-ink-2" style={{ background: "var(--surface-2)", maxHeight: 420 }}>{contract.data.yaml}</pre> : <Loading what="契约" />}
      </Card>
    </div>
  );
}

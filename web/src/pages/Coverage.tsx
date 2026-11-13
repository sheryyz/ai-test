import { useState } from "react";
import { Card, ErrorNote, Loading, PageHeader } from "../components/ui";
import { api, type CoverageCell } from "../lib/api";
import { useAsync } from "../lib/util";

export function Coverage() {
  const data = useAsync(() => api.coverage(), []);
  const [picked, setPicked] = useState<{ row: string; col: string } | null>(null);
  if (data.error) return <ErrorNote error={data.error} />;
  if (!data.data) return <Loading what="覆盖矩阵" />;
  const m = data.data;
  const cols = Object.entries(m.columns);
  const covered = m.rows.reduce((n, r) => n + Object.values(r.cells).filter((c) => c.covered).length, 0);
  const total = m.rows.reduce((n, r) => n + Object.keys(r.cells).length, 0);
  const sel = picked ? m.rows.find((r) => r.key === picked.row) : null;
  const cell = sel && picked ? sel.cells[picked.col] : null;

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="面向比赛评审" title="测试覆盖矩阵">
        按赛题路径二组织：行是评分标准点名的智能体能力与风险，列是路径二列出的四类测试工具。每一格的用例编号由已注册的用例集解析而来，运行证据与文件在生成时逐一核对存在；没有证据的格子如实写“未覆盖”。共 {covered}/{total} 格有证据。
      </PageHeader>
      {m.problems.length > 0 && (
        <div className="rounded-xl px-4 py-3 text-xs text-ink-2" style={{ background: "var(--warning-wash)", border: "1px solid var(--border)" }}>
          <b className="text-ink">本机缺少 {m.problems.length} 处引用的证据</b>（例如刚克隆的仓库没有 runs/ 目录；提交包里带有完整证据）：
          <ul className="mt-1 list-disc pl-4">
            {m.problems.slice(0, 8).map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </div>
      )}

      <Card title="矩阵" subtitle="点任一格查看用例编号与证据路径">
        <div className="scroll-x">
          <div className="grid min-w-[760px] gap-[2px]" style={{ gridTemplateColumns: `140px repeat(${cols.length}, minmax(140px, 1fr))` }}>
            <div />
            {cols.map(([k, c]) => (
              <div key={k} className="px-2 pb-2 text-xs font-semibold text-ink" title={c.means}>
                {c.name}
              </div>
            ))}
            {m.rows.map((r) => (
              <div key={r.key} className="contents">
                <div className="flex flex-col justify-center pr-2">
                  <span className="text-sm font-semibold text-ink">{r.name}</span>
                  <span className="line-clamp-2 text-[11px] text-muted">{r.means}</span>
                </div>
                {cols.map(([k]) => {
                  const c = r.cells[k];
                  const on = picked?.row === r.key && picked?.col === k;
                  return (
                    <button
                      key={k}
                      onClick={() => setPicked({ row: r.key, col: k })}
                      className="rounded-md px-2.5 py-2 text-left text-xs"
                      style={{
                        background: c?.covered ? "var(--good-wash)" : "var(--surface-2)",
                        border: `1px solid ${on ? "var(--brand)" : "var(--border)"}`,
                        boxShadow: on ? "0 0 0 1px var(--brand) inset" : undefined,
                      }}
                    >
                      {c?.covered ? (
                        <>
                          <span className="font-semibold" style={{ color: "var(--good-text)" }}>
                            ✓ 已覆盖
                          </span>
                          <span className="mt-0.5 block text-[11px] text-ink-2">{summary(c)}</span>
                        </>
                      ) : (
                        <>
                          <span className="font-semibold text-muted">未覆盖</span>
                          <span className="mt-0.5 line-clamp-2 block text-[11px] text-muted">{c?.reason}</span>
                        </>
                      )}
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      </Card>

      {sel && cell && picked && (
        <Card title={`${sel.name} × ${m.columns[picked.col].name}`} subtitle={m.columns[picked.col].means}>
          {!cell.covered ? (
            <p className="text-sm text-ink-2">未覆盖：{cell.reason}</p>
          ) : (
            <div className="space-y-3 text-xs">
              {cell.note && <p className="text-sm text-ink">{cell.note}</p>}
              {cell.cases?.map((g) => (
                <div key={`${g.target}/${g.suite}`}>
                  <div className="mb-1 font-semibold text-ink">
                    用例 {g.target}/{g.suite}
                    {Object.keys(g.filter).length > 0 && <span className="font-normal text-muted">（{Object.entries(g.filter).map(([k, v]) => `${k}=${v.join("/")}`).join("，")}）</span>}
                    <span className="font-normal text-muted"> · {g.case_ids.length} 条</span>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {g.case_ids.map((id) => (
                      <span key={id} className="mono rounded px-1.5 py-0.5 text-[11px] text-ink-2" style={{ background: "var(--surface-2)" }}>
                        {id}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
              {!!cell.runs?.length && (
                <div>
                  <div className="mb-1 font-semibold text-ink">运行证据（{cell.runs.length}）</div>
                  <div className="mono flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-ink-2">
                    {cell.runs.map((r) => (
                      <span key={r}>{r}</span>
                    ))}
                  </div>
                </div>
              )}
              {!!cell.files?.length && (
                <div>
                  <div className="mb-1 font-semibold text-ink">文件</div>
                  <div className="mono flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-ink-2">
                    {cell.files.map((f) => (
                      <span key={f}>{f}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
          <p className="mt-4 text-[11px] text-muted">这一行的空白：{sel.gaps || "无"}</p>
        </Card>
      )}
    </div>
  );
}

function summary(c: CoverageCell): string {
  const parts = [];
  if (c.case_count) parts.push(`${c.case_count} 条用例`);
  if (c.runs?.length) parts.push(`${c.runs.length} 份运行证据`);
  if (c.files?.length) parts.push(`${c.files.length} 个文件`);
  return parts.join(" · ");
}

import { useState } from "react";
import { Card, ErrorNote, Loading, PageHeader, Pill } from "../components/ui";
import { api, type GeneratedSuite } from "../lib/api";
import { href, planName, useAsync } from "../lib/util";

const HOW: Record<string, string> = {
  jailbreaks: "大模型只写用户的第一句话（请求 + 越狱话术）；校验要求保留请求本身、明确要求跳过确认、去掉跳过确认的说法后不含任何同意或确认的词；轮次、可信事件和预期终态由规格给定。",
  boundary: "环境事实（工具、数据表、夹具里的数据、知识库）从被测 Agent 自己的接口取得；大模型写整条多轮用例；校验格式、授权账本空跑、业务字段、实体是否存在、表和列、身份信息与子类型数量；运行前人工复核标签。",
  "synced-attacks": "大模型写注入文本；同一段文本挂成两组：授权刚失效的那一轮注入（由授权账本空跑算出是第几轮）和第一轮注入（对照）。",
  attacks: "大模型按“攻击样式 × 目标”写注入文本，确定性校验后冻结，挂到不授权目标动作的载体用例上。",
  "attacks-r2": "把第 1 轮失败的注入连同 Agent 的实际回应交给大模型，分析后写出加强版，再次校验。",
  variants: "大模型改写用户的话、保持授权含义不变，占位符保护 + 词类与顺序校验，人工抽查 20%。",
  holdout: "大模型按规格一次生成、冻结，从未用于调优；运行前复核标签。",
};

export function Generated() {
  const data = useAsync(() => api.generated(), []);
  const [open, setOpen] = useState<string | null>(null);
  if (data.error) return <ErrorNote error={data.error} />;
  if (!data.data) return <Loading what="AI 生成的用例" />;
  const order = ["jailbreaks", "boundary", "synced-attacks", "attacks", "attacks-r2", "holdout", "variants"];
  const suites = [...data.data].sort((a, b) => order.indexOf(a.suite) - order.indexOf(b.suite) || a.target.localeCompare(b.target));
  return (
    <div className="space-y-5">
      <PageHeader title="AI 用例生成">
        平台用大模型生成测试数据，但大模型从不当裁判：每条生成的内容都要通过确定性校验才会冻结成用例集，被拒的会带着原因回传让模型重写；整条多轮用例在运行前还要人工复核标签。下面是平台里所有由 AI 生成的用例集。
      </PageHeader>
      <div className="grid gap-4 lg:grid-cols-2">
        {suites.map((s) => (
          <SuiteCard key={`${s.target}/${s.suite}`} s={s} open={open === `${s.target}/${s.suite}`} onToggle={() => setOpen(open === `${s.target}/${s.suite}` ? null : `${s.target}/${s.suite}`)} />
        ))}
      </div>
      <Card title="生成命令" subtitle="都在命令行里一次生成、冻结；已冻结的用例集不会被覆盖">
        <pre className="mono overflow-auto rounded-md p-3 text-[11px] leading-relaxed text-ink-2" style={{ background: "var(--surface-2)" }}>
          {`uv run consenttrace jailbreaks generate --target travel          # 越狱话术
uv run consenttrace generate-cases --target tau-airline --kind boundary   # 边界场景（环境事实取自 Agent）
uv run consenttrace attacks synced --target travel --profile qwen3.8-max  # 授权时序注入
uv run consenttrace attacks generate --target travel               # 间接注入`}
        </pre>
      </Card>
    </div>
  );
}

function SuiteCard({ s, open, onToggle }: { s: GeneratedSuite; open: boolean; onToggle: () => void }) {
  return (
    <section className="card flex flex-col p-5">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-[15px] font-semibold text-ink">{planName(s.suite)}</h2>
        <Pill>{s.target}</Pill>
        <span className="ml-auto text-xs text-ink-2">{s.cases} 条用例</span>
      </div>
      <p className="mt-1.5 text-xs leading-relaxed text-ink-2">{HOW[s.suite] ?? ""}</p>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        <dt className="text-muted">生成模型</dt>
        <dd className="mono text-ink">{s.model ?? "—"}</dd>
        {s.accepted !== null && (
          <>
            <dt className="text-muted">通过 / 被拒</dt>
            <dd className="text-ink">
              {s.accepted} / {s.rejected ?? 0}
            </dd>
          </>
        )}
        {s.rounds !== null && (
          <>
            <dt className="text-muted">修正轮数</dt>
            <dd className="text-ink">{s.rounds}</dd>
          </>
        )}
        <dt className="text-muted">文件</dt>
        <dd className="mono truncate text-ink-2" title={s.file}>
          {s.file}
        </dd>
      </dl>
      {s.review && (
        <div className="mt-3 rounded-lg p-3 text-xs" style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}>
          <div className="font-semibold text-ink">运行前的标签复核（{s.review.reviewer}）</div>
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-ink-2">
            {s.review.edits.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
          {s.review_sheet && <div className="mono mt-1.5 text-[11px] text-muted">复核表：{s.review_sheet}</div>}
        </div>
      )}
      <div className="mt-3 flex items-center gap-3 text-xs">
        <button onClick={onToggle} className="font-medium" style={{ color: "var(--brand)" }}>
          {open ? "收起用例" : "查看生成的用例"}
        </button>
        <a href={href("console", s.target, "v1", s.suite)} className="text-ink-2 hover:text-ink">
          用它发起测试 →
        </a>
      </div>
      {open && (
        <ul className="mt-3 max-h-80 space-y-2 overflow-auto pr-1">
          {s.samples.map((c) => (
            <li key={c.case_id} className="rounded-md p-2.5 text-xs" style={{ background: "var(--surface-2)" }}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="mono text-[11px] text-muted">{c.case_id}</span>
                <span className="font-medium text-ink">{c.title}</span>
              </div>
              <div className="mt-1 text-ink-2">{c.text}</div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

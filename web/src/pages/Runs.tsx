import { useState } from "react";
import { Card, ErrorNote, Loading, Segmented } from "../components/ui";
import { api } from "../lib/api";
import { useAsync } from "../lib/util";
import { RunsTable } from "./Overview";

export function Runs() {
  const runs = useAsync(() => api.runs(), []);
  const [target, setTarget] = useState("all");
  const [mode, setMode] = useState("all");
  if (runs.error) return <ErrorNote error={runs.error} />;
  if (!runs.data) return <Loading what="运行记录" />;
  const done = runs.data
    .filter((r) => !r.status || r.status === "done")
    .filter((r) => target === "all" || r.target === target)
    .filter((r) => mode === "all" || r.mode === mode)
    .sort((x, y) => (y.finished_at ?? "").localeCompare(x.finished_at ?? ""));
  const targets = [...new Set(runs.data.map((r) => r.target).filter(Boolean))].sort();
  return (
    <Card
      title="运行记录"
      subtitle={`${done.length} 次运行；每一行都对应 runs/ 下一份完整证据（轨迹、授权时间线、状态快照与差分、判定、模型录制）`}
      right={
        <div className="flex flex-wrap gap-2">
          <Segmented label="被测 Agent" value={target} onChange={setTarget} options={[{ value: "all", label: "全部" }, ...targets.map((t) => ({ value: t, label: t }))]} />
          <Segmented
            label="模式"
            value={mode}
            onChange={setMode}
            options={[
              { value: "all", label: "全部" },
              { value: "live", label: "Live" },
              { value: "replay", label: "回放" },
              { value: "scripted", label: "脚本语料" },
            ]}
          />
        </div>
      }
    >
      <RunsTable runs={done} />
    </Card>
  );
}

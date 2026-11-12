import { useEffect, useRef, useState } from "react";
import type { Outcome, RunResult } from "./api";

export interface LiveTrace {
  case_id: string;
  rep: number;
  event: { step_id: number; turn_id: number; kind: string; tool: string | null; status: string | null; injection_id: string | null; content: string | null };
}

export type StreamStatus = "idle" | "running" | "done" | "error";

/** Follows one run's server-sent events: plan, per-execution results, live trace events. */
export function useRunStream(runId: string | null, onDone?: () => void) {
  const [plan, setPlan] = useState<{ cases: string[]; reps: number; total: number } | null>(null);
  const [results, setResults] = useState<Record<string, RunResult>>({});
  const [active, setActive] = useState<Record<string, number>>({});
  const [ticker, setTicker] = useState<LiveTrace[]>([]);
  const [status, setStatus] = useState<StreamStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const done = useRef(onDone);
  done.current = onDone;

  useEffect(() => {
    if (!runId) return;
    setPlan(null);
    setResults({});
    setActive({});
    setTicker([]);
    setError(null);
    setStatus("running");
    const es = new EventSource(`/api/runs/${encodeURIComponent(runId)}/stream`);
    es.addEventListener("start", (e) => setPlan(JSON.parse((e as MessageEvent).data)));
    es.addEventListener("trace", (e) => {
      const t = JSON.parse((e as MessageEvent).data) as LiveTrace;
      setActive((a) => ({ ...a, [`${t.case_id}#${t.rep}`]: t.event.step_id }));
      setTicker((x) => [t, ...x].slice(0, 14));
    });
    es.addEventListener("result", (e) => {
      const r = JSON.parse((e as MessageEvent).data) as RunResult;
      setResults((x) => ({ ...x, [`${r.case_id}#${r.rep}`]: r }));
    });
    es.addEventListener("done", () => {
      setStatus("done");
      es.close();
      done.current?.();
    });
    es.addEventListener("error", (e) => {
      const data = (e as MessageEvent).data;
      if (data) {
        setError(JSON.parse(data).message);
        setStatus("error");
        es.close();
      }
    });
    return () => es.close();
  }, [runId]);

  const counts = Object.values(results).reduce<Partial<Record<Outcome, number>>>((acc, r) => ({ ...acc, [r.outcome]: (acc[r.outcome] ?? 0) + 1 }), {});
  return { plan, results, active, ticker, status, error, counts };
}

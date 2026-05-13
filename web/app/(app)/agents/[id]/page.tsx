"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import {
  deleteAgent,
  getAgent,
  getStatus,
  haltAgent,
  listRuns,
  resumeAgent,
  runAgent,
} from "@/lib/api";
import { StatusChip } from "@/components/StatusChip";
import { useAgentStream, type ConnState } from "@/lib/ws";

export default function AgentDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const router = useRouter();
  const qc = useQueryClient();

  const agent = useQuery({ queryKey: ["agent", id], queryFn: () => getAgent(id) });
  const status = useQuery({
    queryKey: ["agent-status", id],
    queryFn: () => getStatus(id),
    refetchInterval: 5_000,
  });
  const runs = useQuery({
    queryKey: ["agent-runs", id],
    queryFn: () => listRuns(id),
    refetchInterval: 3_000,
  });

  const runNow = useMutation({
    mutationFn: () => runAgent(id),
    onSettled: () => qc.invalidateQueries({ queryKey: ["agent-runs", id] }),
  });
  const halt = useMutation({
    mutationFn: () => haltAgent(id),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["agent-status", id] });
      qc.invalidateQueries({ queryKey: ["agent", id] });
    },
  });
  const resume = useMutation({
    mutationFn: () => resumeAgent(id),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["agent-status", id] });
      qc.invalidateQueries({ queryKey: ["agent", id] });
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteAgent(id),
    onSuccess: () => router.replace("/dashboard"),
  });

  const [logLines, setLogLines] = useState<string[]>([]);
  const conn = useAgentStream(id, (event) => {
    if (event.type === "log") {
      setLogLines((prev) => [...prev.slice(-199), event.msg]);
    } else if (event.type === "run_complete") {
      qc.invalidateQueries({ queryKey: ["agent-runs", id] });
      qc.invalidateQueries({ queryKey: ["agent-status", id] });
    } else if (event.type === "heartbeat") {
      qc.invalidateQueries({ queryKey: ["agent-status", id] });
    }
  });

  if (agent.isLoading) return <Loading />;
  if (agent.isError || !agent.data) return <NotFound />;

  const a = agent.data;
  const halted = status.data?.halted ?? false;
  const heartbeat = (status.data?.heartbeat ?? {}) as Record<string, unknown>;
  const budget = (status.data?.budget ?? {}) as Record<string, unknown>;

  return (
    <div className="mx-auto max-w-5xl">
      <header className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5">
            <h1 className="truncate text-2xl font-semibold tracking-tight">{a.name}</h1>
            <StatusChip
              label={halted ? "halted" : a.status}
              tone={halted ? "danger" : a.status === "running" ? "ok" : "idle"}
            />
          </div>
          {a.description && <p className="mt-1 text-sm text-zinc-400">{a.description}</p>}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            className="btn-primary"
            disabled={runNow.isPending}
            onClick={() => runNow.mutate()}
          >
            {runNow.isPending ? "Queuing…" : "Run now"}
          </button>
          {halted ? (
            <button className="btn-secondary" onClick={() => resume.mutate()}>Resume</button>
          ) : (
            <button className="btn-secondary" onClick={() => halt.mutate()}>Halt</button>
          )}
          <button
            className="btn-ghost text-danger hover:bg-danger/10"
            onClick={() => {
              if (confirm(`Delete "${a.name}"? This cannot be undone.`)) remove.mutate();
            }}
          >
            Delete
          </button>
        </div>
      </header>

      <section className="mt-8 grid grid-cols-1 gap-4 md:grid-cols-3">
        <StatCard
          label="Total runs"
          value={String((heartbeat["total_runs"] as number | undefined) ?? 0)}
          hint={`${(heartbeat["total_failures"] as number | undefined) ?? 0} failed`}
        />
        <StatCard
          label="Today / Daily limit"
          value={fmtUSD(budget["daily_cost"])}
          hint={(heartbeat["last_run_at"] as string | undefined) ?? "no runs yet"}
        />
        <StatCard
          label="Next scheduled run"
          value={(heartbeat["next_run_at"] as string | undefined) ?? "—"}
          hint={
            ((heartbeat["consecutive_failures"] as number | undefined) ?? 0) > 0
              ? `${heartbeat["consecutive_failures"]} consecutive failures`
              : "healthy"
          }
        />
      </section>

      <section className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-[1fr_1fr]">
        <div className="card">
          <div className="border-b border-border-base px-4 py-2.5 text-xs uppercase tracking-wide text-zinc-500">
            Recent runs
          </div>
          <ul className="divide-y divide-border-base">
            {runs.data?.length === 0 && (
              <li className="px-4 py-5 text-sm text-zinc-500">No runs yet. Click "Run now".</li>
            )}
            {runs.data?.map((r) => (
              <li key={r.id} className="flex items-center justify-between px-4 py-3 text-sm">
                <div className="flex items-center gap-2.5">
                  <RunChip status={r.status} />
                  <span className="font-mono text-xs text-zinc-400">
                    {new Date(r.started_at).toLocaleTimeString()}
                  </span>
                </div>
                <div className="text-right text-xs text-zinc-500">
                  {r.cost_usd != null && <span>{fmtUSD(r.cost_usd)} · </span>}
                  {r.input_tokens != null && (
                    <span>{r.input_tokens}/{r.output_tokens ?? 0} tok</span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>

        <div className="card">
          <div className="border-b border-border-base px-4 py-2.5 text-xs uppercase tracking-wide text-zinc-500">
            agent.yaml
          </div>
          <pre className="max-h-[520px] overflow-auto p-4 font-mono text-[12.5px] leading-relaxed text-zinc-300">
{a.yaml_source}
          </pre>
        </div>
      </section>

      <section className="mt-6 card">
        <div className="flex items-center justify-between border-b border-border-base px-4 py-2.5 text-xs uppercase tracking-wide text-zinc-500">
          <span>Live log</span>
          <ConnDot state={conn} />
        </div>
        <pre className="max-h-[300px] min-h-[120px] overflow-auto p-4 font-mono text-[12px] leading-relaxed text-zinc-300">
{logLines.length === 0 ? (
  <span className="text-zinc-600">No log lines yet. Trigger a run to see live output.</span>
) : (
  logLines.join("\n")
)}
        </pre>
      </section>
    </div>
  );
}

function ConnDot({ state }: { state: ConnState }) {
  const color =
    state === "open" ? "bg-ok" :
    state === "connecting" ? "bg-warn animate-pulse" :
    state === "error" ? "bg-danger" : "bg-zinc-500";
  return (
    <span className="flex items-center gap-1.5 normal-case tracking-normal text-[11px]">
      <span className={`h-1.5 w-1.5 rounded-full ${color}`} />
      {state}
    </span>
  );
}

function StatCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="card px-5 py-4">
      <div className="text-xs uppercase tracking-wide text-zinc-500">{label}</div>
      <div className="mt-2 truncate text-2xl font-semibold text-zinc-100">{value}</div>
      {hint && <div className="mt-1 truncate text-xs text-zinc-500">{hint}</div>}
    </div>
  );
}

function RunChip({ status }: { status: string }) {
  const tone =
    status === "success" ? "ok" :
    status === "error" ? "danger" :
    status === "budget_exceeded" ? "warn" : "idle";
  return <StatusChip label={status} tone={tone as any} />;
}

function fmtUSD(v: unknown): string {
  if (v == null) return "—";
  const n = typeof v === "number" ? v : parseFloat(String(v));
  if (Number.isNaN(n)) return "—";
  return `$${n.toFixed(4)}`;
}

function Loading() {
  return (
    <div className="mx-auto max-w-5xl text-sm text-zinc-500">Loading agent…</div>
  );
}

function NotFound() {
  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="text-xl font-semibold">Agent not found</h1>
      <p className="mt-1 text-sm text-zinc-400">It may have been deleted or you don't have access.</p>
    </div>
  );
}

"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { listAgents } from "@/lib/api";
import { StatusChip } from "@/components/StatusChip";

export default function DashboardPage() {
  const { data: agents, isLoading, error } = useQuery({
    queryKey: ["agents"],
    queryFn: listAgents,
  });

  return (
    <div className="mx-auto max-w-5xl">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Agents</h1>
          <p className="mt-1 text-sm text-zinc-400">
            {agents ? `${agents.length} total` : "Loading…"}
          </p>
        </div>
        <Link href="/agents/new" className="btn-primary">+ New agent</Link>
      </header>

      {error && (
        <div className="card mt-8 p-4 text-sm text-danger">
          Failed to load agents.
        </div>
      )}

      <div className="mt-8 grid grid-cols-1 gap-3">
        {isLoading && <SkeletonRow />}
        {agents && agents.length === 0 && (
          <EmptyState />
        )}
        {agents?.map((a) => (
          <Link
            key={a.id}
            href={`/agents/${a.id}`}
            className="card flex items-center justify-between px-5 py-4 transition-colors hover:bg-bg-elevated"
          >
            <div className="min-w-0">
              <div className="flex items-center gap-2.5">
                <span className="truncate font-medium text-zinc-100">{a.name}</span>
                <StatusChip
                  label={a.status}
                  tone={
                    a.status === "running" ? "ok" :
                    a.status === "halted" ? "danger" : "idle"
                  }
                />
              </div>
              {a.description && (
                <p className="mt-1 truncate text-sm text-zinc-500">{a.description}</p>
              )}
            </div>
            <div className="text-xs text-zinc-500">
              {new Date(a.updated_at).toLocaleString()}
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}

function SkeletonRow() {
  return (
    <div className="card animate-pulse px-5 py-4">
      <div className="h-4 w-32 rounded bg-bg-elevated" />
      <div className="mt-2 h-3 w-64 rounded bg-bg-elevated" />
    </div>
  );
}

function EmptyState() {
  return (
    <div className="card p-10 text-center">
      <div className="text-base font-semibold text-zinc-100">No agents yet</div>
      <p className="mt-1 text-sm text-zinc-400">
        Create your first agent in under a minute.
      </p>
      <Link href="/agents/new" className="btn-primary mt-5 inline-flex">+ New agent</Link>
    </div>
  );
}

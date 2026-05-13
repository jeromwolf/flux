// Same-origin API client. Cookies are HttpOnly so browser handles them automatically;
// fetch must include them with credentials:'include' (also works for same-origin).

import type { Agent, AgentStatus, Run, User } from "./types";

type FetchOpts = RequestInit & { json?: unknown };

async function http<T>(path: string, opts: FetchOpts = {}): Promise<T> {
  const { json, headers, ...rest } = opts;
  const init: RequestInit = {
    ...rest,
    credentials: "include",
    headers: {
      ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(headers ?? {}),
    },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
    cache: "no-store",
  };
  const res = await fetch(`/api${path}`, init);
  if (res.status === 204) return undefined as T;
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = await res.json();
    } catch {
      detail = await res.text();
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(`API ${status}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
  }
}

// ----- Auth ---------------------------------------------------------------

export async function getMe(): Promise<User | null> {
  try {
    return await http<User>("/auth/me");
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return null;
    throw e;
  }
}

export async function logout(): Promise<void> {
  await http<void>("/auth/logout", { method: "POST" });
}

// ----- Agents -------------------------------------------------------------

export function listAgents() {
  return http<Agent[]>("/agents");
}

export function getAgent(id: string) {
  return http<Agent>(`/agents/${id}`);
}

export function createAgent(payload: { name: string; description?: string; yaml_source: string }) {
  return http<Agent>("/agents", { method: "POST", json: payload });
}

export function updateAgent(id: string, payload: { description?: string; yaml_source?: string }) {
  return http<Agent>(`/agents/${id}`, { method: "PUT", json: payload });
}

export function deleteAgent(id: string) {
  return http<void>(`/agents/${id}`, { method: "DELETE" });
}

export function runAgent(id: string) {
  return http<Run>(`/agents/${id}/run`, { method: "POST" });
}

export function haltAgent(id: string) {
  return http<{ agent_id: string; halted: boolean }>(`/agents/${id}/halt`, { method: "POST" });
}

export function resumeAgent(id: string) {
  return http<{ agent_id: string; halted: boolean }>(`/agents/${id}/resume`, { method: "POST" });
}

export function listRuns(id: string) {
  return http<Run[]>(`/agents/${id}/runs`);
}

export function getStatus(id: string) {
  return http<AgentStatus>(`/agents/${id}/status`);
}

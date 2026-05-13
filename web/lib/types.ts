// Mirror of flux.api.schemas. Keep this in sync with the backend pydantic models.

export type User = {
  id: string;
  github_id: number;
  github_login: string;
  email: string | null;
  avatar_url: string | null;
  created_at: string;
  last_login_at: string | null;
};

export type Agent = {
  id: string;
  user_id: string;
  name: string;
  description: string | null;
  yaml_source: string;
  status: "idle" | "running" | "halted";
  created_at: string;
  updated_at: string;
};

export type Run = {
  id: string;
  agent_id: string;
  started_at: string;
  finished_at: string | null;
  status: "queued" | "success" | "error" | "budget_exceeded";
  input_tokens: number | null;
  output_tokens: number | null;
  cost_usd: number | null;
  tool_rounds: number | null;
  error: string | null;
};

export type AgentStatus = {
  agent_id: string;
  name: string;
  status: string;
  halted: boolean;
  heartbeat: Record<string, unknown>;
  budget: Record<string, unknown>;
};

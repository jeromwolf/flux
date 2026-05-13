"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { createAgent, ApiError } from "@/lib/api";

const DEFAULT_YAML = `name: news-bot
description: "Summarize the day's AI news every morning."
schedule: "0 8 * * *"
model: claude-haiku
max_tokens: 4096
budget:
  per_run: 0.10
  daily: 1.00
  monthly: 10.00
tools:
  - web_search
  - web_fetch
system_prompt: |
  You are an AI/tech news curator.
user_prompt: |
  Find the top 5 AI news items and summarize each in 2-3 sentences.
`;

export default function NewAgentPage() {
  const router = useRouter();
  const [name, setName] = useState("news-bot");
  const [description, setDescription] = useState("");
  const [yaml, setYaml] = useState(DEFAULT_YAML);
  const [serverError, setServerError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => createAgent({ name, description: description || undefined, yaml_source: yaml }),
    onSuccess: (a) => router.replace(`/agents/${a.id}`),
    onError: (e) => {
      if (e instanceof ApiError) {
        setServerError(
          typeof e.detail === "string" ? e.detail : JSON.stringify(e.detail, null, 2)
        );
      } else {
        setServerError(String(e));
      }
    },
  });

  return (
    <div className="mx-auto max-w-5xl">
      <header className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">New agent</h1>
        <p className="mt-1 text-sm text-zinc-400">Define an agent in YAML. Save to start using it.</p>
      </header>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_2fr]">
        <div className="card p-5">
          <label className="label" htmlFor="name">Name</label>
          <input
            id="name"
            className="input font-mono"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="news-bot"
            pattern="[a-z0-9][a-z0-9\-_]*"
          />
          <p className="mt-1 text-xs text-zinc-500">lowercase, digits, dash/underscore</p>

          <label className="label mt-5" htmlFor="desc">Description</label>
          <input
            id="desc"
            className="input"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Optional"
          />

          <button
            type="button"
            disabled={mutation.isPending}
            onClick={() => {
              setServerError(null);
              mutation.mutate();
            }}
            className="btn-primary mt-7 w-full"
          >
            {mutation.isPending ? "Saving…" : "Save agent"}
          </button>

          {serverError && (
            <pre className="mt-5 overflow-x-auto whitespace-pre-wrap rounded-md border border-danger/40 bg-danger/10 p-3 text-xs text-danger">
              {serverError}
            </pre>
          )}
        </div>

        <div className="card flex flex-col">
          <div className="border-b border-border-base px-4 py-2.5 text-xs uppercase tracking-wide text-zinc-500">
            agent.yaml
          </div>
          <textarea
            value={yaml}
            onChange={(e) => setYaml(e.target.value)}
            spellCheck={false}
            className="min-h-[480px] resize-y bg-transparent p-4 font-mono text-[13px] leading-relaxed text-zinc-100 focus:outline-none"
          />
        </div>
      </div>
    </div>
  );
}

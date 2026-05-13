// Lightweight WebSocket hook for agent live streams.
// Same-origin (Next.js rewrites pass cookies through), so just open ws:// to /ws/...

"use client";

import { useEffect, useRef, useState } from "react";

type AgentEvent =
  | { type: "snapshot"; agent: any; heartbeat: any; halted: boolean }
  | { type: "log"; msg: string }
  | { type: "heartbeat"; heartbeat: any; halted: boolean }
  | { type: "run_complete"; run_id: string; status: string; cost_usd: number | null; input_tokens: number | null; output_tokens: number | null; error: string | null };

export type ConnState = "connecting" | "open" | "closed" | "error";

export function useAgentStream(
  agentId: string | undefined,
  onEvent: (event: AgentEvent) => void
): ConnState {
  const [state, setState] = useState<ConnState>("closed");
  const ref = useRef<WebSocket | null>(null);
  const cbRef = useRef(onEvent);
  cbRef.current = onEvent;

  useEffect(() => {
    if (!agentId) return;
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const url = `${proto}://${window.location.host}/ws/agents/${agentId}`;
    setState("connecting");
    const ws = new WebSocket(url);
    ref.current = ws;

    ws.onopen = () => setState("open");
    ws.onclose = () => setState("closed");
    ws.onerror = () => setState("error");
    ws.onmessage = (msg) => {
      try {
        cbRef.current(JSON.parse(msg.data));
      } catch {
        /* ignore malformed frames */
      }
    };

    return () => {
      ref.current = null;
      try {
        ws.close();
      } catch {}
    };
  }, [agentId]);

  return state;
}

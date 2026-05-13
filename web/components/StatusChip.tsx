import { cn } from "@/lib/cn";

type Tone = "ok" | "warn" | "danger" | "idle";

const TONE: Record<Tone, string> = {
  ok: "border-ok/40 bg-ok/10 text-ok",
  warn: "border-warn/40 bg-warn/10 text-warn",
  danger: "border-danger/40 bg-danger/10 text-danger",
  idle: "border-border-base bg-bg-elevated text-zinc-400",
};

export function StatusChip({ label, tone = "idle" }: { label: string; tone?: Tone }) {
  return (
    <span className={cn("chip", TONE[tone])}>
      <span className={cn("inline-block h-1.5 w-1.5 rounded-full",
        tone === "ok" && "bg-ok",
        tone === "warn" && "bg-warn",
        tone === "danger" && "bg-danger",
        tone === "idle" && "bg-zinc-500",
      )} />
      {label}
    </span>
  );
}

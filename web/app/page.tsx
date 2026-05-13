import Link from "next/link";
import { Logo } from "@/components/Logo";

export default function LandingPage() {
  return (
    <div className="relative isolate overflow-hidden">
      {/* ambient glow */}
      <div className="pointer-events-none absolute inset-x-0 -top-40 -z-10 transform-gpu blur-3xl">
        <div
          aria-hidden
          className="mx-auto aspect-[1155/678] w-[60rem] bg-gradient-to-tr from-accent/40 to-accent-soft/20 opacity-20"
          style={{ clipPath: "polygon(74% 0, 100% 25%, 78% 100%, 30% 78%, 0 50%, 25% 9%)" }}
        />
      </div>

      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-6">
        <Logo />
        <nav className="flex items-center gap-3 text-sm">
          <a href="https://github.com/jeromwolf/flux" className="btn-ghost">GitHub</a>
          <Link href="/login" className="btn-secondary">Sign in</Link>
        </nav>
      </header>

      <main className="mx-auto max-w-6xl px-6 pb-24 pt-16">
        <div className="max-w-3xl">
          <span className="chip mb-6 border-accent/40 bg-accent/10 text-accent-soft">
            <span className="h-1.5 w-1.5 rounded-full bg-accent" /> Open source · Apache 2.0
          </span>
          <h1 className="text-5xl font-semibold tracking-tight text-zinc-50 sm:text-6xl">
            Deploy AI agents that don't<br />bankrupt you at 3am.
          </h1>
          <p className="mt-6 max-w-2xl text-lg text-zinc-400">
            Flux is the runtime layer agents have been missing — safety shields,
            watchdog supervision, and 24/7 scheduling so your agent never burns
            $47,000 because nobody was watching at 3am.
          </p>

          <div className="mt-10 flex flex-wrap items-center gap-3">
            <Link href="/login" className="btn-primary">Sign in with GitHub</Link>
            <a href="https://github.com/jeromwolf/flux" className="btn-secondary">
              ★ Star on GitHub
            </a>
          </div>
        </div>

        <section className="mt-24 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Feature
            title="Safety Shield"
            body="Per-run / daily / monthly budget hard limits, on-disk so daemon restarts can't reset your counter."
          />
          <Feature
            title="Watchdog Runtime"
            body="Independent supervisor restarts a dead agent with exponential backoff. Recovery in &lt; 60s."
          />
          <Feature
            title="One YAML, one agent"
            body="Define an agent in 20 lines. Run it locally or in the browser. Schedule with standard cron."
          />
        </section>
      </main>

      <footer className="border-t border-border-base">
        <div className="mx-auto max-w-6xl px-6 py-6 text-xs text-zinc-500">
          flux.ai.kr · made by Kelly · BYOK (bring your own LLM key)
        </div>
      </footer>
    </div>
  );
}

function Feature({ title, body }: { title: string; body: string }) {
  return (
    <div className="card p-5">
      <div className="text-sm font-semibold text-zinc-100">{title}</div>
      <p
        className="mt-1.5 text-sm leading-relaxed text-zinc-400"
        dangerouslySetInnerHTML={{ __html: body }}
      />
    </div>
  );
}

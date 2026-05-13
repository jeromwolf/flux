# Show HN — draft

## Title (80 char max — try to land in 60)

`Show HN: Flux – run AI agents 24/7 for $1/month (Apache-2.0)`

> Alternates if the above gets flagged for being too brag-y:
> - `Show HN: Flux – open-source runtime for AI agents (safety + watchdog)`
> - `Show HN: Flux – deploy AI agents that don't bankrupt you at 3am`

## URL
`https://github.com/jeromwolf/flux`

## Body

Hi HN — Kelly here.

For the past year I've been running 6–7 personal AI agents on my own infra:
one summarises the day's AI news, one tracks Korean and US equities, one
watches my GitHub feed, etc. The whole fleet costs roughly **$1.26/month** in
LLM bills because I use small models for narrow tasks and I keep them under
hard budget caps.

The piece that took the longest to get right wasn't the agents themselves —
it was the runtime around them. Three things that, every time I skipped them,
broke something:

1. **Hard budget caps that survive a restart.** Industry has plenty of
   $47K-overnight stories. I needed daily/monthly cost counters that live on
   disk so a daemon crash + restart doesn't reset the meter.
2. **A watchdog that actually restarts a dead agent.** Cron-only isn't enough
   once an LLM provider blips for 90 seconds at 3am.
3. **An emergency stop the same dashboard can flip.** When something goes
   sideways I want one button, not three terminals.

Flux is what I built around those three. It's a Python runtime + a small
FastAPI + a Next.js dashboard. After three weeks of carving the runtime out of
my private setup, it's ready enough to share:

- **Safety Shield**: per-run / daily / monthly hard limits, persisted to disk,
  with 80% and 95% soft warnings + a `flux halt` kill switch.
- **Watchdog**: independent process that polls PID + heartbeat freshness +
  consecutive failures; restarts with exponential backoff (30s → 30m ceiling).
- **Multi-tenant web UI**: GitHub OAuth, per-user agent isolation (cross-tenant
  reads return 404, not 403, so existence isn't leaked), live WebSocket logs
  on the agent detail page.
- **BYOK**: you bring your own LLM key. Flux never stores keys in the database.
- 113 tests, Apache-2.0, `pip install flux-agent[api]`.

Self-hosted only for now (one `docker compose up postgres` + `flux serve` +
`pnpm dev`). I'm not running a hosted version — partly because I don't want to
hold anyone's API keys, mostly because I want the operations-debt experience
of the runtime to stay honest.

Repo: https://github.com/jeromwolf/flux
README has the 10-minute setup.

Happy to talk about anything — the safety shield design, the watchdog
back-off curve I landed on after burning a few weekends, why I'm dropping
NextAuth, the BYOK trade-off. Roast away.

— Kelly

---

## Pre-written first self-comment (post 5 minutes after submission)

> A few details that didn't fit the body:
>
> - **Tech stack**: Python 3.11+, FastAPI, SQLAlchemy 2.x async, Alembic,
>   Postgres 16 (SQLite for tests). Web: Next.js 14 App Router, Tailwind 3,
>   TanStack Query. No NextAuth — backend handles OAuth and Next.js rewrites
>   the cookie origin so there's no CORS or cookie-domain dance.
> - **What I deliberately left out**: a hosted SaaS, an agent marketplace,
>   LangChain compatibility. Each of those is a separate product. Today's
>   release is just the runtime + control plane.
> - **What's coming**: a per-user "Hosted Flux" tier later this year, but only
>   after the OSS edition is solid. I want to live with everyone else's bugs
>   first.
> - **Why $1.26/month**: it's claude-haiku ($0.80/1M in, $4/1M out) on small
>   prompts (~2K in, ~1K out per run), 7 agents × 1–2 runs/day. Not a typo,
>   not magic — just budget-capped small models on narrow tasks.

---

## Anticipated questions + canned answers (for the comment thread)

**"Isn't this just CrewAI/LangGraph + a UI?"**
> Both of those help you *build* the agent. Flux is the layer around an agent
> after it exists: cost caps, restart policy, isolation, scheduling. You can
> wrap a CrewAI agent in Flux — the runtime is provider-agnostic.

**"$1.26/month sounds suspicious — show me."**
> The cost breakdown is in `docs/launch/blog-running-7-agents.md`. It's
> claude-haiku on prompts under 2K tokens, ~1.5 runs/day average.

**"Why not LiteLLM / Langfuse / agent observability X?"**
> Observability is downstream of safety. Flux's job is *not letting the bill
> hit $47K in the first place*. Observability is on the roadmap (the
> WebSocket stream is the first cut).

**"Why GitHub OAuth — what about email/password?"**
> Two reasons: (1) zero password-reset support burden, (2) the audience this
> early is developers who already have GitHub. Email/magic-link is on the
> table once there's pull for it.

**"License?"**
> Apache 2.0. No CLA. Contributions welcome — see CONTRIBUTING.md.

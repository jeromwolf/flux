# ProductHunt — draft

## Name
**Flux — AI agent runtime**

## Tagline (60 char max)
`Runtime for AI agents — safety, watchdog, 24/7 scheduling`

## Topics (pick 3)
- Developer Tools
- Artificial Intelligence
- Open Source

## Description (260 char target)

Flux is the open-source runtime layer your AI agents have been missing.
Per-run/daily/monthly hard budget caps that survive restarts, a watchdog that
restarts dead agents in under a minute, multi-tenant web UI with live logs.
Self-hosted, Apache-2.0, BYOK.

## Gallery (in order)

1. `docs/assets/demo.gif` — 30–45s screencast: login → new agent → Run Now → live log
2. `docs/assets/dashboard.png` — agent list with status chips
3. `docs/assets/detail.png` — agent detail with Live log panel mid-stream
4. `docs/assets/landing.png` — marketing landing

## First comment (maker)

> Hey everyone — Kelly here, builder.
>
> I've been running 6–7 personal agents on my own infra for the past year for
> ~$1.26/month total. Cost stays low because each agent has a hard budget cap
> and uses a small model on a narrow task. The infra I built around them is
> what I open-sourced today.
>
> Three pieces I keep coming back to:
> - **Safety Shield** — on-disk budget counters (daily/monthly survive restarts)
> - **Watchdog** — independent supervisor with exponential-backoff restarts
> - **Multi-tenant UI** — GitHub OAuth, per-user isolation, WebSocket live logs
>
> Self-hosted only for now. BYOK so I never hold your API key. License is
> Apache-2.0. Repo: https://github.com/jeromwolf/flux
>
> I'll be answering questions live today — operating-cost questions especially
> welcome.

## Useful links to attach
- GitHub: https://github.com/jeromwolf/flux
- Website: https://flux.ai.kr
- Show HN: (fill in after HN submission)

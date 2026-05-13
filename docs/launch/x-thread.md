# X / Threads — 7-tweet launch thread (draft)

> Target audience: dev Twitter + ko dev Twitter. Threads variant is the same
> text, English first. Korean translation appears in tweet replies if needed.

---

**1/7**
I've been running 6 AI agents 24/7 on my own infra for the past year.

Total LLM bill: $1.26/month.

Today I'm open-sourcing the runtime layer that makes that possible.

→ Flux: https://github.com/jeromwolf/flux 🧵

---

**2/7**
The agents themselves are easy.
The infra around them is what kept biting me.

3 things I kept rebuilding:
• per-run + daily + monthly hard cost caps
• a watchdog that actually restarts a dead agent
• an emergency stop button I can hit from anywhere

That's Flux.

---

**3/7**
Why hard cost caps matter:
the $47,000-overnight horror stories are real, and they happen because the
cost counter lives in RAM and a crash resets it.

Flux's counters live on disk.
80% / 95% soft warnings, hard cutoff at 100%.
`flux halt <agent>` to kill in one keystroke.

---

**4/7**
The watchdog isn't cron.
It's a separate process polling PID + heartbeat + consecutive-failure count.
When it detects trouble it restarts with exponential backoff:

30s → 60s → 5m → 15m → 30m ceiling.

Cron-only wakes up at 8am. The watchdog wakes up in 60s.

---

**5/7**
There's also a small web UI:

• GitHub OAuth
• Multi-tenant (cross-tenant access returns 404, not 403 — never leak existence)
• YAML builder
• Live log via WebSocket while a run streams

Next.js 14 + FastAPI + Postgres. No NextAuth — backend handles OAuth, Next.js rewrites cookies.

---

**6/7**
BYOK — you bring your own LLM API key.
Flux never stores keys in the database.

That's why my cost line is $1.26/month: I'm spending claude-haiku money,
not "platform mark-up" money.

Self-hosted, Apache-2.0, 113 tests.

---

**7/7**
docker compose up postgres
alembic upgrade head
flux serve
cd web && pnpm dev

→ http://localhost:3000

Repo + 10-min setup: https://github.com/jeromwolf/flux
Show HN: (fill after HN submission)

Roast it, fork it, run it 🌶

— Kelly

---

## Korean adaptation (single follow-up thread or replies)

> KR 1/3
> AI 에이전트, 만들었으면 돌려야죠. 월 $0.01부터.
> 1년간 개인 에이전트 6개를 월 $1.26로 돌렸습니다. 그 인프라를 오늘 OSS로 공개합니다.
>
> KR 2/3
> 핵심 3가지:
> · 비용 한도 (재시작에도 살아남는 디스크 카운터)
> · 와치독 (60초 안에 죽은 에이전트 살림)
> · 비상 정지 (`flux halt`)
> 호스팅 없음, BYOK, Apache-2.0.
>
> KR 3/3
> docker compose up postgres / flux serve / pnpm dev → 끝.
> https://github.com/jeromwolf/flux

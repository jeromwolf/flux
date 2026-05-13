# How I run 6 AI agents 24/7 for $1.26 a month — draft

> Long-form companion to the Show HN / ProductHunt launch.
> Target length: 1,500–2,000 words. Target platform: Substack or Medium under
> Kelly's name. Tone: matter-of-fact, numbers-first, no hype.

> **Review before posting:** the cost screenshots in §4 quote Kelly's
> personal Korbit / Korean ETF / US equities accounts. Decide per-screenshot
> whether to redact the dollar amount or only show the relative P&L.

---

## The line that started it

> "How are you spending so little on these agents?"

A friend asked me this in March. I pulled up my Anthropic console:

```
Last 30 days: $1.26
```

Six agents. One a day for some, a few per day for others. Total LLM spend:
about the price of a single coffee shop espresso, monthly.

He didn't believe me. Honestly, neither did I the first time I saw the number
— I'd budgeted ten times that.

So I wrote up exactly how I got there. This post is the writeup; the runtime
that makes it possible is now open-source: **[Flux](https://github.com/jeromwolf/flux)**.

---

## What the 6 agents actually do

None of them are clever. That's the point.

| Agent | Schedule | Job | Avg. cost / run |
|---|---|---|---|
| news-summary | daily 08:00 | Top-5 AI news, 2-line summaries | ~$0.014 |
| github-trending | daily 08:30 | GitHub Trending Top-5, one line each | ~$0.008 |
| weather-digest | weekdays 07:00 | 3-line Seoul weather + outfit | ~$0.003 |
| tweet-summary | manual | Long X thread → one Korean paragraph | ~$0.009 |
| portfolio-watch | hourly (market hours) | US equities + Korean ETF P&L scan | ~$0.005 |
| coin-watch | every 4h | Korbit BTC/ETH spread vs cost basis | ~$0.005 |

> A seventh agent — a private CRM follow-up reminder — runs on the same
> infra. It's not in this list because it touches contacts I can't share.

If you average that out: ~10 runs/day × ~$0.008 = **$0.08/day = ~$2.40/month**
at the upper bound. The reason my actual bill is closer to $1.26 is that I
don't run them every day, and several skip when the page they fetch hasn't
changed.

---

## The actual cost trick: tiny prompts, small model, no chains

Most people overspend because they reach for the biggest model on a habit, or
they hand the agent more context than it needs.

My defaults:
- **Model**: `claude-haiku-4-5` ($0.80 / $4.00 per 1M tokens in/out).
  For two-line summaries this is plenty.
- **Context budget per run**: 2K tokens in, 1K tokens out, hard. I prune the
  system prompt to fit and never grow the conversation across runs.
- **No chains**. Each agent does *one thing*. If it needs another tool, it's
  a different agent.

That's it. No prompt-engineering deep magic, no model routing, no Mixture-of-Experts.
Just narrow tasks on a small model with a hard ceiling.

---

## What kept burning me before the runtime existed

Here's the embarrassing part. I wrote the first agent in a weekend. The
second one took two weekends — because the first one had crashed silently and
nobody noticed for four days. The third took a month, because I'd written
half a "framework" by then that didn't quite work.

I kept hitting the same three walls:

### Wall 1: cost counters that reset on a daemon restart

The first agent I built had a daily cap of $0.50. Felt safe. What I missed
was that the daily counter lived in process memory — if the daemon restarted
(say, after a system update), the counter went to zero and the cap effectively
became "$0.50 *per restart*".

I have a Slack message in my history that just says
> oh.

next to a screenshot of my Anthropic console.

It wasn't a $47K disaster. Closer to $4.20. But it was real.

The fix is so simple that I'm angry I didn't do it first: write the counter
to disk. Use `tmp → rename` so a crash mid-write doesn't corrupt it. Load it
back on next boot.

Flux's `SafetyShield` does exactly that.

### Wall 2: cron is not a recovery strategy

The second time something broke at scale, it was an LLM provider 502 for ~90
seconds. The cron-fired agent that hit it during those seconds didn't retry —
cron isn't a retry policy. The agent just lost that run. Nobody noticed for
two days because the "daily summary" emails I was getting were still
arriving, just from the *other* agents.

A real watchdog has to be a separate process. It has to poll three signals:
- is the PID still alive
- is the heartbeat file fresh enough for the cron interval
- is the consecutive-failure counter under threshold

Flux's watchdog is ~250 lines. The backoff schedule (30s → 60s → 5m → 15m →
30m) is what landed after I tried several extremes — slower curves let
problems linger, faster curves DDOS the upstream while it's actually down.

### Wall 3: emergency stops you can hit from your phone

The third lesson is the one I learned during a model-quality regression. I
woke up to my portfolio-watch agent posting nonsense to a private channel.
The fix should have been: open the dashboard on my phone, hit *Halt*. The
reality was: SSH from my phone, find the PID, `kill -TERM`, then re-edit a
YAML.

So the runtime needs a way to halt an agent *and have the next run respect
that halt*, without going near the process. Flux does this with an
`emergency_stop` sentinel file the SafetyShield pre-check checks for. The web
UI is just a button that touches that file. Two clicks from a phone browser.

`flux halt news-bot` from a laptop terminal does the same thing.

---

## Why I'm releasing this now, and what's *not* in it

I sat on the runtime for a year because I wasn't sure it generalised. I had
my agents, my prompts, my budget numbers — the same setup wouldn't be the
same number for someone else.

What changed my mind: every conversation with a friend who'd tried building
an agent ended at one of those three walls. Different stacks, different
prompts, same walls.

What's **in** Flux v0.1:
- Safety Shield (per-run / daily / monthly, disk-persisted, soft warnings,
  hard cutoff, halt switch)
- Watchdog (PID + heartbeat + failure-streak with backoff)
- Multi-tenant web UI (GitHub OAuth, isolation, live WS logs)
- CLI + FastAPI + Next.js 14
- BYOK (your LLM key, never stored)
- Apache-2.0, 113 tests

What's **not** in v0.1, and won't be soon:
- A hosted version. I want to live with everyone else's deployment bugs
  first. Hosted is on the roadmap for late 2026.
- An agent marketplace. Different product. It depends on a hosted version
  existing first.
- LangChain compatibility. Flux is provider-agnostic on purpose — you can
  wrap any agent in it.

---

## What you can copy without using Flux

In case you don't want a new dependency, here are the three patterns that
matter most. Use them in whatever framework you already have:

1. **Persist your cost counter atomically.** `tmp → rename` is enough.
   Reset on date change, not on process start.
2. **Run your watchdog in a different process from the agent.**
   The watchdog has to survive the very crash it's supposed to recover from.
3. **An "emergency stop" is a file, not a HTTP call.**
   File semantics survive your service being down.

If you do those three things, you have most of what kept me from spending
$47,000 at 3am.

---

## The setup (10 minutes)

If you want the whole thing:

```bash
git clone https://github.com/jeromwolf/flux && cd flux

# 1. Register a GitHub OAuth App
#    callback http://localhost:3000/auth/github/callback
# 2. Fill .env (copy .env.example)

# 3. Backend
pip install -e '.[api]'
docker compose up -d postgres
alembic upgrade head
flux serve

# 4. Frontend (other terminal)
cd web && pnpm install && pnpm dev

# 5. open http://localhost:3000
```

Sign in with GitHub, click *New agent*, paste this YAML:

```yaml
name: news-summary-bot
description: "매일 아침 AI 뉴스를 요약해서 정리"
schedule: "0 8 * * *"
model: claude-haiku
budget:
  per_run: 0.10
  daily: 1.00
  monthly: 10.00
tools: [web_search, web_fetch]
system_prompt: |
  당신은 AI/테크 뉴스 큐레이터입니다.
user_prompt: |
  오늘의 AI 뉴스 Top 5를 검색하고 각 뉴스를 2~3문장으로 요약해주세요.
```

Click *Run now*, watch the Live log panel fill up. Your first run is
~$0.014.

---

## I'd love your feedback

The fastest way to make this better is to have someone else hit it. If
you try it and it breaks, file an issue. If you try it and it works,
star the repo so other people can find it:

→ **[github.com/jeromwolf/flux](https://github.com/jeromwolf/flux)**

I'll be on HN and X today answering anything — especially the cost
questions. They're the questions I asked too.

— Kelly

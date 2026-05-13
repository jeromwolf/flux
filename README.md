# Flux — AI Agent Runtime Platform

> Deploy AI agents that don't bankrupt you at 3am.

Flux is an open-source AI agent runtime that lets you create, deploy, and manage AI agents 24/7 with built-in safety controls.

**AI 에이전트, 만들었으면 돌려야죠. 월 $0.01부터.**

<!-- TODO(launch): replace with real 30-45s demo GIF before v0.1.0 -->
<p align="center">
  <img src="docs/assets/demo.gif" alt="Flux — agent dashboard, run-now, and live log via WebSocket" width="820" />
</p>

## Quick Start

```bash
# Install
pip install flux-agent

# Set your API key
export ANTHROPIC_API_KEY=sk-ant-...

# Create an agent
flux init news-bot

# Validate config
flux validate agents/news-bot.yaml

# Run it
flux start agents/news-bot.yaml

# Run as daemon (scheduled)
flux start agents/news-bot.yaml -d

# Check costs
flux cost news-bot
```

## Example agents

| File | Schedule | Budget (run/day/mo) | Use case |
|---|---|---|---|
| [`news-summary.yaml`](agents/examples/news-summary.yaml) | `0 8 * * *` | $0.10 / $1.00 / $10.00 | Top-5 AI news, summarised in Korean |
| [`github-trending.yaml`](agents/examples/github-trending.yaml) | `30 8 * * *` | $0.05 / $0.30 / $3.00 | GitHub Trending Top-5, one line each |
| [`weather-digest.yaml`](agents/examples/weather-digest.yaml) | `0 7 * * 1-5` | $0.02 / $0.10 / $1.00 | 3-line Seoul weather + outfit (weekdays) |
| [`tweet-summary.yaml`](agents/examples/tweet-summary.yaml) | manual | $0.05 / $0.50 / $5.00 | Paste an X thread URL → Korean paragraph |

All four together cost roughly **$1/month** if you run them every day.

## Agent YAML

Define agents in simple YAML:

```yaml
name: news-summary-bot
description: "Daily AI news curator"

schedule: "0 8 * * *"        # cron: daily at 08:00
model: claude-haiku
max_tokens: 4096

budget:
  per_run: 0.10              # max $0.10 per run
  daily: 1.00
  monthly: 10.00

tools:
  - web_search
  - web_fetch

system_prompt: |
  You are an AI/tech news curator.
  Find top 5 AI news and summarize in Korean.

user_prompt: |
  Search for today's AI news Top 5 and summarize each in 2-3 sentences.
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `flux init <name>` | Create agent YAML template |
| `flux validate <file>` | Validate agent config |
| `flux start <file>` | Run agent (foreground) |
| `flux start <file> -d` | Run agent (daemon with cron) |
| `flux stop <name>` | Stop running agent |
| `flux list` | List running agents |
| `flux logs <name>` | View agent logs |
| `flux cost <name>` | View cost summary |
| `flux watch <file>` | Watchdog: auto-restart on failure |
| `flux watch <file> -d` | Watchdog (background daemon) |
| `flux unwatch <name>` | Stop watchdog |
| `flux status <name>` | Agent + watchdog health summary |
| `flux halt <name>` | Emergency stop (blocks next pre-check) |
| `flux resume <name>` | Resume a halted agent |

## Features

- **Safety Shield** — Per-run, daily, monthly budget limits with automatic circuit breaker.
  Budget state is **disk-persisted** so daily/monthly counters survive daemon restarts.
- **Soft Threshold Warnings** — Surfaces at 80% and 95% of daily/monthly budget before hard cutoff
- **Emergency Stop** — `flux halt <name>` immediately blocks every pre-check; `flux resume` clears it
- **Watchdog Runtime** — Independent supervisor monitors PID + heartbeat freshness + consecutive
  failures; auto-restarts the agent with exponential backoff (30s → 60s → 5m → 15m → 30m).
  Recovery is logged to `~/.flux/agents/<name>/events.jsonl`.
- **Multi-LLM** — Anthropic, OpenAI, Google, Ollama (BYOK: bring your own key)
- **Built-in Tools** — Web search, web fetch, file I/O, memory, scheduling
- **Security** — AST-based tool scanning, SSRF protection, path traversal prevention, secret masking
- **Hardened Scheduler** — `misfire_grace_time=300s`, `max_instances=1`, `coalesce=True`
  so missed runs catch up safely without overlap
- **Rich CLI** — Beautiful terminal output with Rich panels and tables
- **Cost Tracking** — Per-run cost recording with JSONL history + persistent budget state
- **Web UI (Week 3)** — Next.js 14 dashboard with GitHub OAuth, agent builder, live run logs via WebSocket
- **Multi-tenant API** — FastAPI + PostgreSQL + Alembic; per-user data dirs under `~/.flux/users/<id>/`
- **Tested** — 113 tests covering config, safety + persistence, watchdog, scheduler, runner, CLI, resilience, DB, OAuth, agents API, WebSocket

## 24/7 Operation Recipe

```bash
# Terminal 1: start the agent as a daemon
flux start agents/news-bot.yaml -d --now

# Terminal 2: start the watchdog (separate process, survives agent crashes)
flux watch agents/news-bot.yaml -d

# Any time
flux status news-bot       # health summary
flux halt news-bot         # emergency stop
flux resume news-bot       # back online
flux unwatch news-bot      # stop the supervisor
flux stop news-bot         # stop the agent daemon
```

## Web UI Quick Start (Week 3)

The browser dashboard lets you (or other GitHub users) create and operate agents
without touching the CLI.

```bash
# 1. Register a GitHub OAuth App
#    Settings -> Developer settings -> OAuth Apps -> New
#    Callback URL: http://localhost:3000/auth/github/callback
# 2. Copy .env.example -> .env and fill in GITHUB_CLIENT_ID/GITHUB_CLIENT_SECRET + JWT_SECRET

# 3. Boot Postgres
docker compose up -d postgres

# 4. Apply migrations + start the API
pip install -e '.[api]'
alembic upgrade head
flux serve --port 8000     # uvicorn on :8000

# 5. Start the web app (in a second terminal)
cd web
pnpm install
pnpm dev                   # Next.js on :3000

# 6. Open http://localhost:3000 -> "Sign in with GitHub"
```

All requests from the browser are same-origin (Next.js rewrites
`/auth/*` and `/api/*` to the API on `:8000`), so cookies stay HttpOnly+SameSite=Lax
and there's no CORS to configure.

**Full-stack via docker compose** (production-style):

```bash
docker compose --profile full up        # postgres + api containers
```

### API surface

```
/healthz                         GET   meta
/auth/github/{login,callback}    GET   OAuth flow
/auth/{me,logout}                GET/POST
/agents                          GET/POST   list + create
/agents/{id}                     GET/PUT/DELETE
/agents/{id}/runs                GET   execution history
/agents/{id}/run                 POST  trigger now (queued -> background)
/agents/{id}/{halt,resume,status} POST/POST/GET
/ws/agents/{id}                  WS    snapshot + log + heartbeat + run_complete
```

### Multi-tenant isolation

- Every router filters by `Agent.user_id == current_user.id`.
- Cross-tenant access returns **404 (not 403)** so existence isn't leaked.
- On-disk data is partitioned: `~/.flux/users/<user_id>/agents/<name>/`.

## Architecture

```
flux start agent.yaml
    |
    v
AgentRunner (runner.py)
    |-- loads AgentConfig (config.py + pydantic)
    |-- creates LLM Provider (llm.py)
    |-- creates ToolManager (tools/manager.py)
    |-- creates SafetyShield (safety/shield.py)
    |-- creates AgentEngine (engine.py)
    v
AgentEngine.run_turn()
    |-- LLM call (with retry + timeout)
    |-- Tool execution loop
    |-- Budget tracking
    v
Result (text + tokens + cost)
```

## Tech Stack

- Python 3.11+
- Click + Rich (CLI)
- Anthropic/OpenAI/Google SDK (LLM)
- APScheduler (cron)
- Pydantic (config validation)

## License

Apache 2.0

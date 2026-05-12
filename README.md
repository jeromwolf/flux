# Flux — AI Agent Runtime Platform

> Deploy AI agents that don't bankrupt you at 3am.

Flux is an open-source AI agent runtime that lets you create, deploy, and manage AI agents 24/7 with built-in safety controls.

**AI 에이전트, 만들었으면 돌려야죠. 월 $0.01부터.**

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
- **Tested** — 81 tests covering config, safety + persistence, watchdog, scheduler, runner, CLI, resilience

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

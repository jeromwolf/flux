# Changelog

All notable changes to Flux are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Flux uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-05-13
### Added — Week 1: Runtime Core
- `AgentEngine` LLM/tool loop with retry, timeout, streaming, and budget guard
- Multi-LLM provider abstraction (Anthropic, OpenAI, Google, Ollama; BYOK)
- `ToolManager` with AST-based security scanning + hot reload
- 7 builtin tools: `web_search`, `web_fetch`, `read_text_file`, `save_text_file`,
  `list_files`, `memory_manage`, `schedule_task`
- `AgentRunner` orchestration + `flux` CLI (`init`/`validate`/`start`/`stop`/`list`/`logs`/`cost`)
- pydantic-based `agent.yaml` schema with strict validation
- Example agent: `agents/examples/news-summary.yaml`

### Added — Week 2: 24/7 Safety Net
- `SafetyShield` with **disk-persisted** daily/monthly budget counters
  (`budget_state.json`, atomic write) — daemon restarts no longer reset usage
- Soft threshold warnings at 80% and 95% of daily/monthly budget
- Emergency stop kill switch (`flux halt` / `flux resume`) via `emergency_stop` file
- `AgentWatchdog` (new module): PID + heartbeat-freshness + consecutive-failure
  health checks; exponential backoff restart (30s → 60s → 5m → 15m → 30m)
- Per-agent `heartbeat.json` + `events.jsonl` for observability
- Hardened APScheduler: `misfire_grace_time=300s`, `max_instances=1`, `coalesce=True`
- CLI additions: `flux watch`, `flux unwatch`, `flux status`, `flux halt`, `flux resume`

### Added — Week 3: Web Control Plane
- FastAPI + SQLAlchemy 2.x async + Alembic, dual-driver
  (asyncpg in prod, aiosqlite in tests)
- 14-route API: `/healthz`, GitHub OAuth (`/auth/github/{login,callback}`,
  `/auth/{me,logout}`), agents CRUD, `/agents/{id}/{run,halt,resume,status,runs}`
- WebSocket `/ws/agents/{id}` streaming `snapshot` / `log` /
  `heartbeat` / `run_complete` events
- HttpOnly JWT cookie auth + `itsdangerous` CSRF state token for OAuth
- Per-tenant on-disk isolation: `~/.flux/users/<user_id>/agents/<name>/`
- Cross-tenant access returns **404** (not 403) to avoid leaking existence
- Run trigger via `BackgroundTasks` + `asyncio.to_thread`, with `queued` Run
  rows returned immediately
- Next.js 14 App Router web UI (landing / login / dashboard / agent builder /
  agent detail with live log panel), TanStack Query, Tailwind 3, Linear/Vercel tone
- `flux serve` CLI command, `docker-compose.yml` (postgres + opt-in `api`),
  `Dockerfile` for the API container
- 113 tests (config, safety + persistence, watchdog, scheduler, runner, CLI,
  resilience, DB, OAuth, agents API, WebSocket)

### Notes
- **BYOK** — you bring your own LLM API key. Flux never stores keys in the database.
- License: Apache-2.0.

[Unreleased]: https://github.com/jeromwolf/flux/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/jeromwolf/flux/releases/tag/v0.1.0

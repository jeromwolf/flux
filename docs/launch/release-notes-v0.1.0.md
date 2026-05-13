# Flux v0.1.0 — first public release 🚀

**The runtime layer agents have been missing.**

<!-- Replace with docs/assets/demo.gif when ready -->
<p align="center">
  <img src="https://raw.githubusercontent.com/jeromwolf/flux/main/docs/assets/demo.gif" alt="Flux demo" width="820" />
</p>

Flux is an open-source runtime for AI agents — built around three things that
keep agents from quietly burning your bill or going silent in the night:

- **Safety Shield** — per-run / daily / monthly hard budget caps, persisted to
  disk so daemon restarts can't reset the meter. 80% / 95% soft warnings.
  `flux halt` kill switch.
- **Watchdog** — independent process that monitors PID + heartbeat freshness +
  consecutive-failure count, and restarts a dead agent with exponential
  backoff (30s → 60s → 5m → 15m → 30m).
- **Multi-tenant web UI** — GitHub OAuth, per-user isolation (cross-tenant
  reads return 404, not 403), live WebSocket logs.

BYOK — you bring your own LLM API key. Flux never stores keys in the database.

## What's in this release

### Runtime
- `AgentEngine` LLM/tool loop with retry, timeout, streaming, budget guard
- Multi-LLM (Anthropic / OpenAI / Google / Ollama)
- `ToolManager` with AST-based security scanning
- 7 built-in tools: `web_search`, `web_fetch`, `read_text_file`, `save_text_file`,
  `list_files`, `memory_manage`, `schedule_task`

### Safety + reliability
- `SafetyShield` with atomic on-disk budget state
- `AgentWatchdog` module (PID, heartbeat, failure-streak, backoff)
- Hardened APScheduler: `misfire_grace_time=300s`, `max_instances=1`, `coalesce=True`

### Web control plane
- FastAPI + SQLAlchemy 2.x async + Alembic; Postgres 16 in prod, SQLite in tests
- 12 REST routes (`/healthz`, OAuth flow, agents CRUD, `/agents/{id}/{run,halt,resume,status,runs}`)
- WebSocket `/ws/agents/{id}` — snapshot / log / heartbeat / run_complete
- Next.js 14 App Router web UI — landing / login / dashboard / agent builder /
  agent detail with Live log
- `docker compose up postgres` + `flux serve` + `pnpm dev`

### Tooling
- 14 CLI commands (`flux init / validate / start / stop / list / logs / cost /
  watch / unwatch / status / halt / resume / serve / --version`)
- 4 example agents in `agents/examples/`
- 113 tests (Python) + `pnpm typecheck` (TypeScript) gate

## Getting started

```bash
git clone https://github.com/jeromwolf/flux && cd flux
pip install -e '.[api]'
docker compose up -d postgres
alembic upgrade head
flux serve                 # API on :8000
cd web && pnpm install && pnpm dev   # Web on :3000
```

`README.md` has the 10-minute walkthrough including how to register a GitHub
OAuth App for local dev.

## License

[Apache-2.0](./LICENSE).

## Thanks

To the small group who looked at this before launch and pointed out the
places where it wasn't obvious enough — you know who you are.

Roast it, fork it, run it.

— Kelly

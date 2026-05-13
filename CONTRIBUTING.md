# Contributing to Flux

Thanks for considering a contribution! Flux is a small project with a clear
philosophy — please read this once before opening a PR so we're aligned.

## Project philosophy

1. **Necessary things only.** If a feature isn't critical for the runtime,
   keep it out of core. Tools and integrations go in `tools/builtins/` or a
   separate package.
2. **Reference, then design.** When something new is needed, look at how Linear,
   Vercel, Anthropic SDK, and APScheduler do it before inventing.
3. **Design for the goal.** A safety shield is meaningful because real bills
   exist. A watchdog is meaningful because real outages happen. Optimize for
   the user who *runs* an agent, not the one who only builds one.

## Before opening a PR

- For changes **> 50 lines** or anything that touches public API/schema/CLI flags,
  please open an issue or discussion first so we can agree on the approach.
- For typos, doc fixes, and small bug fixes — go straight to a PR.

## Dev setup

### Backend (Python 3.11+)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[api,dev]'
docker compose up -d postgres
alembic upgrade head
pytest -q                 # full suite (uses SQLite for speed)
ruff check src tests      # lint
flux serve --reload       # uvicorn on :8000
```

### Frontend (Node 20+, pnpm 10)

```bash
cd web
pnpm install
pnpm typecheck
pnpm dev                  # Next.js on :3000
```

### Environment variables

Copy `.env.example` to `.env`. For OAuth-touching work, register a
"Flux (dev)" GitHub OAuth App with callback
`http://localhost:3000/auth/github/callback`.

## Test policy

- **Add a test for every bug fix.** It locks the regression.
- Backend tests use SQLite in-memory; no Docker required to run them.
- Don't add real LLM calls in tests — stub `flux.api.services.runner_proxy.execute_agent`
  and friends. The runtime already has solid coverage for the LLM path.
- Frontend has `tsc --noEmit` as the minimum gate. Component tests welcome but
  not required for the MVP.

## Commit + PR style

- Commit messages use a `feat:` / `fix:` / `docs:` / `refactor:` / `test:` /
  `chore:` prefix and a short, present-tense summary.
- Korean is welcome in commits/issues/PRs; English is fine too.
- One logical change per PR. Splits make review much easier.

PR template will prompt for the basics — please fill it in.

## What we'd love help on

- New built-in tools in `src/flux/tools/builtins/` (keep them under 150 lines,
  no extra deps if possible).
- Additional example agents in `agents/examples/`.
- LLM provider integrations beyond Anthropic/OpenAI/Google.
- Translations of `README.md` and launch docs.
- Bug reports with a minimal reproduction.

## Code of conduct

By participating you agree to the [Code of Conduct](./CODE_OF_CONDUCT.md).

## License

By contributing you agree your contributions will be licensed under the
[Apache 2.0 License](./LICENSE).

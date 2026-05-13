# v0.1.0 release checklist

Use this the day Kelly tags `v0.1.0`. Anything `[?]` is a manual check; anything
`[ ]` should be re-run from a clean shell.

## Code gates (re-run from a clean shell)

- [ ] `pytest -q` — 113+ green
- [ ] `ruff check src tests` — clean
- [ ] `cd web && pnpm typecheck` — clean
- [ ] `cd web && pnpm build` — 7 routes built, ≤120 kB First Load JS on heaviest route
- [ ] `flux --version` prints `0.1.0`
- [ ] `flux init test-bot && flux validate agents/test-bot.yaml` — Valid ✓

## Live stack smoke (3 terminals)

```bash
# t1
docker compose up -d postgres
alembic upgrade head
flux serve --port 8000

# t2
cd web && pnpm dev

# t3
curl -sS http://localhost:8000/healthz   # status=ok, database=ok
open http://localhost:3000               # landing renders, no console errors
```

- [ ] `/healthz` returns `database=ok` against Postgres
- [ ] OpenAPI lists **12 REST routes** + WebSocket route (`/ws/agents/{id}`) is reachable from browser DevTools
- [ ] Sign in with the dev GitHub OAuth App → dashboard loads (empty)
- [ ] New agent → save → detail → Run now → Live log fills
- [ ] Second GitHub account on a different browser profile → empty dashboard (tenant isolation)

## Versioning

- [?] `pyproject.toml` version = `"0.1.0"`
- [?] `web/package.json` version = `"0.1.0"`
- [?] `CHANGELOG.md` `[0.1.0]` section is the top entry under `[Unreleased]`

## Visual assets

- [?] `docs/assets/demo.gif` exists (≤5 MB, 30–45 s, no leaked secrets)
- [?] `docs/assets/{landing,dashboard,detail}.png` exist (each ≤400 KB)
- [?] README renders correctly on GitHub (preview before tagging)

## Repo metadata

- [?] Description: "Deploy AI agents that don't bankrupt you at 3am — runtime + safety + scheduling."
- [?] Homepage: `https://flux.ai.kr`
- [?] Topics: 10 keywords applied
- [?] LICENSE present, SPDX = Apache-2.0
- [?] CONTRIBUTING.md and CODE_OF_CONDUCT.md present
- [?] Issue + PR templates present (`.github/ISSUE_TEMPLATE/`, `.github/PULL_REQUEST_TEMPLATE.md`)
- [?] `test.yml` workflow has a green run on `main`
- [?] Discussions: **not yet enabled** — flip on right before HN post

## Secrets & accidents

- [ ] `git grep -nE 'sk-ant|GITHUB_CLIENT_SECRET|JWT_SECRET=' -- ':!.env.example' ':!docs/'`
      returns **no hits**
- [ ] `.env` is NOT staged (`git status` should not list it)
- [ ] `~/.flux/` is not part of the working tree

## Tag + release

```bash
git tag -a v0.1.0 -m "Flux v0.1.0 — first public release"
git push origin v0.1.0

gh release create v0.1.0 \
  --title "Flux v0.1.0 — first public release" \
  --notes-file docs/launch/release-notes-v0.1.0.md
```

- [ ] Tag exists on GitHub
- [ ] Release page has the GIF + the CHANGELOG link
- [ ] HN submission can now point at `github.com/jeromwolf/flux/releases/tag/v0.1.0`

## After publishing

- [ ] Enable Discussions
- [ ] Add 3–5 `good first issue` issues from the post-launch wishlist
- [ ] Post Show HN; immediately reply with the pre-written self-comment
- [ ] Start filling `docs/launch/metrics.md`

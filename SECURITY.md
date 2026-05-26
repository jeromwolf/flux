# Security Policy

Flux is the runtime that keeps AI agents alive 24/7 — which means security
incidents in Flux can translate directly into runaway costs, leaked
credentials, or compromised agents in production. We take that seriously and
welcome responsible disclosure from anyone who finds an issue.

## Supported Versions

Only the latest minor line of Flux receives security fixes. Once `0.2.x` is
released, `0.1.x` will move to community support only.

| Version  | Supported          |
| -------- | ------------------ |
| `0.1.x`  | Yes (active)       |
| `< 0.1`  | No                 |

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security problems.** Public
disclosure before a patch ships puts every Flux operator at risk.

Use one of these channels instead:

1. **Email**: `jeromwolf@gmail.com` with subject line prefix `[Flux Security]`.
   PGP is optional — encrypt against the key listed on the maintainer's GitHub
   profile if you need it.
2. **GitHub Security Advisories**: open a private report at
   <https://github.com/jeromwolf/flux/security/advisories/new>. This is the
   preferred channel because it keeps the disclosure timeline auditable.

Include as much of the following as you can:

- Affected version / commit SHA.
- Reproduction steps or proof-of-concept.
- Impact assessment (what an attacker gains).
- Suggested mitigation, if any.

## Response Timeline

We commit to the following targets, measured from the time the report is
received via one of the channels above:

| Stage                          | Target           |
| ------------------------------ | ---------------- |
| Acknowledgment of report       | within 48 hours  |
| Initial severity assessment    | within 7 days    |
| Patch released or status update | within 30 days  |

If the issue requires more than 30 days, we will share progress notes with the
reporter at least every two weeks until resolution.

## Scope

**In scope** — please report issues in any of these areas:

- `src/flux/**` — agent engine, runner, tool manager, safety shield, scheduler,
  watchdog.
- `src/flux/api/**` — FastAPI control plane, authentication, multi-tenant data
  paths, request validation.
- `web/**` — Next.js frontend, session handling, CSRF / cookie security.
- Authentication / authorization flows (GitHub OAuth, JWT issuance, cookie
  scoping).
- Multi-tenant data isolation (one user observing or affecting another user's
  agents, runs, logs, costs, files on disk).
- AST scanner bypasses or sandbox escapes in `flux.tools.manager`.
- SSRF / path-traversal bugs in builtin tools (`web_fetch`, `read_text_file`,
  `save_text_file`, `list_files`).
- Dependency vulnerabilities that materially affect Flux's threat model.

**Out of scope** — we will likely not treat these as security issues:

- Transient rate-limit bypass that requires valid authentication.
- Denial of service through legitimate, authenticated API calls.
- Findings exclusively against `dev-only-insecure-jwt-secret-change-me` (this
  is the documented dev fallback; production refuses to boot with it).
- Vulnerabilities in third-party services Flux integrates with (file those
  upstream).
- Social engineering of maintainers or users.
- Best-practice deviations without a demonstrable exploit (e.g. missing
  hardening headers that have no impact in our threat model).

## Safe Harbor

We support good-faith security research. If you make a reasonable effort to
follow this policy — in particular by privately reporting, avoiding data
destruction, and not exfiltrating more data than necessary to demonstrate the
vulnerability — we will:

- Not pursue legal action or law enforcement complaints against you.
- Treat your report confidentially.
- Work with you on coordinated disclosure timing.

## Recognition

With your consent we will credit you in the release notes of the patched
version (typically as `Reported by <handle> via <channel>`). If you would
prefer to remain anonymous, just say so in the report and we will respect that.

Thank you for helping keep Flux operators safe.

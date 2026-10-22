# Working on Alexa

This repository is a deterministic MCP server for Alexa+. The model interprets
the user. The server validates the parameters, applies versioned rules, executes
a simulated action, and returns structured speech and a trace. See
`TECHNICAL.md`, `STANDARD.md`, `BUILD_PLAN.md`, and `DECISIONS.md` before changing
a contract.

The project name is **Alexa**. Use `Alexa`, `alexa`, or `ALEXA_` in code, docs,
environment variables, logger names, and client ids.

## First commands

Run from `backend/`:

```bash
uv sync --dev
uv run uvicorn app.main:app --reload --port 8000
```

In another terminal:

```bash
cd backend
uv run python -m app.cli tools
uv run python -m app.cli call timer_set '{"duration_seconds": 600}'
uv run python -m app.cli bench --n 100
uv run python -m app.cli audit verify
```

Checks:

```bash
cd backend
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
python3 ../scripts/check_leaks.py --self-test
```

Console (React, pnpm, from the repository root):

```bash
pnpm install
pnpm dev       # http://localhost:5173/console/, proxies /api to port 8000
pnpm typecheck
pnpm build
```

The console scaffold is in place; the four screens are Day 4 work. See
`docs/FRONTEND.md`.

Enable the pre-commit leak scan once per clone:

```bash
git config core.hooksPath .githooks
```

Do not commit unless the user asks. The working tree is often intentionally
uncommitted while a build day is in progress.

## Layout

| Path | Owns |
|---|---|
| `backend/app/main.py` | FastAPI app, `/mcp` mount, existing console routes, health, metadata, startup warnings, API router inclusion |
| `backend/app/api/` | Console REST routers: config, state, privacy, the single call endpoint, assistant, voice, journeys |
| `backend/app/assistant/` | Deterministic parser, per-subject pending confirmations, reply envelope |
| `backend/app/voice/` | ElevenLabs proxy, bounded cache, typed fallback reasons |
| `backend/app/journeys/` | Journey schema, YAML loader, isolated runner, fixtures |
| `backend/app/mcp_server.py` | `MCPServer`, tool registration, MCP annotations, per-request principal |
| `backend/app/router.py` | The only execution path: auth, scope, rules, privacy, confirmation, adapter, audit, trace, log |
| `backend/app/rules/` | Versioned `rules.yaml`, loader, validation, defaults, display labels |
| `backend/app/audit.py` | Hash-chained append-only log, verify, retention tombstones |
| `backend/app/audit_seed.json` | Deterministic startup chain, rebuilt at boot |
| `backend/app/privacy.py` | Per-user privacy and concise settings |
| `backend/app/memory.py` | Last action details for `tell_me_more` |
| `backend/app/tools/` | Tool manifests (`specs.py`) and handlers |
| `backend/app/adapters/` | Simulated device and booking state |
| `backend/app/confirm.py` | Single-use confirmation tokens |
| `backend/app/auth.py` | Static and session bearer verification, scopes, 401 challenge, REST dependency |
| `backend/app/accounts/` | Google OAuth with PKCE, account/session store, session verifier |
| `backend/app/api/auth.py` | Browser auth routes: start, callback, exchange, account, logout |
| `backend/app/models.py` | Wire contract and error taxonomy |
| `backend/tests/` | Unit, HTTP, auth, voice, journey, and live uvicorn MCP tests |
| Repository root (`src/`, `package.json`, `vite.config.ts`) | React operator console: theme tokens, typed API client, screens. Settings in `pnpm-workspace.yaml`, design in `docs/FRONTEND.md` |

## Invariants

- Keep `Router.execute` as the only path from a tool call to an adapter. MCP and
  REST are thin wrappers. Tests call the router directly.
- Auth comes before validation. Do not let an unauthenticated caller learn the
  schema from error messages.
- Scope check comes before execution. A confirmation token never bypasses it.
  `undo` resolves the target row first and then checks the scopes that row
  recorded, before any adapter runs.
- Rules own value constraints. `ToolSpec` owns identity, risk, scopes, and the
  confirmation template. `RULES.check_tools(TOOLS)` fails at startup on drift.
- Every decision writes one audit row from `Router._finish`, including previews
  and refusals. The row holds a parameter hash, never raw parameters, plus the
  minimal inverse state undo needs. `verify()` must stay green after any change.
- Business errors are tool results with `status: "error"`, not protocol errors.
  Preserve `code`, `field`, `allowed`, and `follow_up`.
- Speech is server-composed and deterministic. Do not add a model call to the
  request path.
- Confirmation tokens are single-use, bound to subject, tool, and parameter
  hash, and consumed only after the adapter succeeds.
- The trace stores a parameter hash, never raw parameters or tokens.
- Subjects are pseudonymous. A raw `amzn1.` id is refused at token parsing.
- `app.mount("/", mcp_app)` stays last so `/health`, `/api`, `/docs`, and the
  metadata route win.
- The console renders decisions; it never makes them. Any write it needs goes
  through `POST /api/call/{tool}`, which calls `Router.execute`, never a second
  path. `PUT /api/privacy` is the same rule for the privacy toggles.
- The assistant is deterministic. The parser returns parameters only, never
  calls a model, and every action still goes through `Router.execute`. A
  clarification is not a tool call and writes no audit row.
- A pending assistant confirmation is keyed by subject and holds the token in
  memory. The next yes or no goes through the same single-use token check.
  `/api/assistant/confirm` is a button for that flow, not a bypass.
- Voice synthesis is optional and never in the decision path. It speaks the
  server's `speech` string, keeps the ElevenLabs key server-side, and honors
  `third_party_sharing`. A missing key is a structured fallback, not an error
  that changes the transcript.
- Journeys run against a fresh `AppState`. A journey run must never change live
  timers, bookings, sessions, or audit rows.
- Tool titles and hints come from `ToolSpec`. Do not duplicate them in the
  decorator.
- `book_room` is marked external. The privacy gate refuses it, and cancelling
  it, when `third_party_sharing` is off.
- Concise mode is the default: `detail` is withheld and `detail_available` is
  set. `tell_me_more` returns the withheld text from memory, so any new handler
  detail must flow through `HandlerResult`, not a literal in `_finish`.

## Style

- No em dashes and no en dashes in prose. Use a colon, a comma, or a full stop.
  This is a hard house rule, not a preference.
- Comments explain intent, tradeoffs, and failure modes, not syntax.
- Keep line length at 120. Ruff selects `E`, `F`, `I`, `UP`, `B`, `ASYNC`, `RUF`.
- Prefer small, typed functions and Pydantic models at boundaries.
- New behavior needs a test. A live MCP path needs an HTTP test; a rule needs a
  rules test.

## Security and privacy

- Never commit a real token, deployment URL, AWS account id, Alexa skill id, or
  key. `.env` is ignored; `.env.example` is the shape only.
- The development token `dev-token` is public on purpose. It must be replaced
  before a public deployment. Startup warns when it is not.
- Do not log tokens, raw parameters, or full request bodies. The subject,
  parameter hash, decision, and trace id are enough to debug.
- `book_room` is marked external. The privacy gate refuses it, and cancelling
  it, when third-party sharing is off.
- The container runs as UID 10001. Do not add root-only files or writable paths
  without a reason.

## Current state

Days 1 to 4 are complete. The eight tools (`timer_set`, `lights_set`,
`thermostat_set`, `book_room`, `undo`, `tell_me_more`, `privacy_get`,
`privacy_set`) run through versioned YAML rules, confirmation tokens, a
hash-chained audit log with a seeded startup fixture and `alexa audit verify`,
undo linked through the log, concise mode, and server-enforced privacy settings.

The Day 4 backend is in place: a deterministic assistant with per-subject
pending confirmations, an optional ElevenLabs voice proxy with a browser
fallback, the console REST surface (`/api/config`, `/api/state`, `/api/privacy`,
`/api/call/{tool}`, `/api/assistant/*`, `/api/voice/*`, `/api/journeys/*`), and
four YAML journeys with an isolated runner. Google sign-in is in the backend:
persistent users and sessions, OAuth state and PKCE, single-use exchange codes,
a session verifier that resolves to the same `Principal` as a static token,
explicit CORS for Vercel, and SQLite locally or Render Postgres in production.
The suite is 216 tests and includes parser, confirmation, privacy-gate, voice,
journey, auth, CORS, and account persistence coverage.

The React app is at the repository root with pnpm, React 19, TypeScript, Vite,
Amazon theme tokens, a typed client, a landing page, and the operator console.
The sign-in, callback, and account screens are the next frontend work. The
backend auth contract is `/api/auth/config`, `/api/auth/google/start`,
`/api/auth/callback/google`, `POST /api/auth/exchange`, `GET` and `PATCH
/api/auth/me`, `POST /api/auth/logout`, and a local-only
`POST /api/auth/dev-login`.

Known gaps: no Alexa+ registration, Local Inspector device run, or physical
device test; no MCP authorization server for Alexa+ (browser Google sign-in is a
separate flow); the console sign-in screens are not wired yet; the `/console`
static mount and root-context Docker change are pending; no real device
integrations; no license chosen. The voice is disabled until a key is set,
and the voice endpoint has no per-token rate limit; the bearer token is the
control for live use. Render free instances spin down, which resets the
in-memory house and audit chain.

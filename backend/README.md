# Alexa backend

A rules-driven MCP server with confirmation tokens, a hash-chained audit log,
undo, concise mode, privacy toggles, and Google-backed browser accounts.

What runs today:

- MCP Streamable HTTP endpoint at `/mcp` (spec 2025-11-25, via `mcp` 2.3).
- Bearer auth on every MCP and console request. Unauthenticated calls get a
  `401` with an RFC 9728 `WWW-Authenticate` challenge and protected-resource
  metadata.
- Eight tools: `timer_set`, `lights_set`, and `thermostat_set` (low risk),
  `book_room` (medium risk, preview and confirmation), `undo`, `tell_me_more`,
  `privacy_get`, and `privacy_set`.
- Versioned YAML rules in `app/rules/rules.yaml`: types, bounds, enums, date and
  time formats, labels, and defaults. The rules version is published with every
  manifest and recorded in every audit row.
- Single-use confirmation tokens bound to the subject, tool, and canonical
  parameter hash, with a 300-second TTL. Replay, expiry, and changed parameters
  are refused.
- A hash-chained audit row for every decision: executed, previewed, refused, and
  no_change. Rows hold a parameter hash and the minimal inverse state, never the
  raw request.
- `alexa audit verify` walks the chain and reports the first broken link.
- Undo for timers, lights, climate, and bookings, linked back with
  `compensator_of`.
- Concise mode on by default, with `tell_me_more` returning the withheld detail.
- Privacy settings enforced server-side. `third_party_sharing=false` refuses
  `book_room` (the `external=true` tool) with `PRIVACY_BLOCKED`.
- Google sign-in for the console: authorization code with PKCE, a callback on
  the API origin, a single-use exchange code, and an opaque `sess_...` bearer.
  The SPA never receives a Google token.
- Persistent users and sessions in SQLite locally and Render Postgres in
  production. Only hashes of session tokens, OAuth states, and exchange codes
  are stored. Accounts are keyed by Google `sub`, not email, and the audit
  subject stays `user_<uuid>`.
- Static bearer tokens remain for Alexa+, the inspector, and the CLI. Both
  token kinds resolve to the same `Principal`, so there is still one execution
  path.

## Run

```bash
cd backend
uv sync --dev
uv run uvicorn app.main:app --reload --port 8000
```

Or with a plain virtualenv:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Copy `.env.example` to `.env` before deploying. The development token is:

```
dev-token
```

with scopes `home:timers:write home:lights:write home:climate:write
booking:rooms:write privacy:settings:write`. Replace
`ALEXA_TOKENS_JSON` before deploying.

> **Auth note.** MCP clients still use a static bearer token from
> `ALEXA_TOKENS_JSON`. This server does not run an OAuth 2.1 authorization
> server for MCP, though the 401 challenge and RFC 9728 metadata are
> spec-correct. Browser sign-in is a separate Google OAuth flow for the console.
> If Alexa+ registration requires authorization-server metadata, add one before
> the device test. The Local Inspector works by sending
> `Authorization: Bearer dev-token`.

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST/GET/DELETE | `/mcp` | Bearer | MCP Streamable HTTP |
| GET | `/health` | none | Platform health check |
| GET | `/api/auth/config` | none | Google availability, start URL, frontend URL, TTL, dev login |
| GET | `/api/auth/google/start` | none | Create state and PKCE, redirect to Google |
| GET | `/api/auth/callback/google` | none | Consume state, exchange the Google code, redirect to the SPA |
| POST | `/api/auth/exchange` | none | Trade a single-use code for an opaque session bearer |
| GET | `/api/auth/me` | Bearer | Account and session expiry for the current bearer |
| PATCH | `/api/auth/me` | Bearer | Change the display name on a session |
| POST | `/api/auth/logout` | Bearer | Revoke the current session |
| POST | `/api/auth/dev-login` | none | Local-only session without Google |
| GET | `/api/config` | none | Versions, tool count, rules version, voice availability, persistence marker |
| GET | `/api/whoami` | Bearer | Subject, client, and scopes for a token |
| GET | `/api/tools` | Bearer | Tool manifests, per-field rules, rules version, confirmation TTL |
| GET | `/api/trace?limit=50` | Bearer | Newest-first in-memory trace |
| GET | `/api/audit?limit=50` | Bearer | The caller's audit rows and the seed marker |
| GET | `/api/audit/verify` | Bearer | Chain status, row count, and the first broken link |
| GET | `/api/state` | Bearer | Timers, lights, climate, bookings, privacy, and pending confirmation for the caller |
| GET | `/api/privacy` | Bearer | The caller's privacy settings |
| PUT/PATCH | `/api/privacy` | Bearer | Partial update through `privacy_set` and `Router.execute` |
| POST | `/api/call/{tool}` | Bearer | The console's single write path: one tool call through `Router.execute` |
| POST | `/api/assistant/turn` | Bearer | Deterministic parse, then `Router.execute` |
| GET | `/api/assistant/session` | Bearer | The pending confirmation, without the token |
| POST | `/api/assistant/confirm` | Bearer | Complete the pending action, same path as a spoken "yes" |
| POST | `/api/assistant/cancel` | Bearer | Drop the pending action, same path as a spoken "no" |
| POST | `/api/assistant/reset` | Bearer | Clear the pending action without auditing a tool call |
| GET | `/api/voice/config` | Bearer | Whether ElevenLabs is configured and the browser fallback |
| POST | `/api/voice/speak` | Bearer | Audio for one `speech` string, or a structured fallback |
| GET | `/api/journeys` | Bearer | Journey names, titles, descriptions, and step counts |
| POST | `/api/journeys/{name}/run` | Bearer | Run one journey against an isolated app state |
| GET | `/.well-known/oauth-protected-resource/mcp` | none | RFC 9728 metadata |

### The assistant brain and the voice proxy

`POST /api/assistant/turn` is not a second decision path. It is a deterministic
parser that maps the spoken phrases to the same `Router.execute` call an
MCP client makes. It never calls a model, never writes adapter state, and never
composes tool speech. When a preview is issued, the server holds the single-use
token for the next turn; `confirm`, `cancel`, and the words "yes" and "no" all
reach the same token check.

`POST /api/voice/speak` is optional. With `ALEXA_ELEVENLABS_API_KEY` unset, the
server reports `voice.enabled: false` and the console uses browser speech. When
configured, the key stays server-side, the text is capped, repeated phrases are
cached in memory, and the endpoint refuses with `PRIVACY_BLOCKED` when the
caller's `third_party_sharing` is off. The tool response's `speech` is always
present, so a voice failure never changes what the transcript says.

### Journeys

`backend/app/journeys/fixtures/` holds four reviewed YAML journeys: timer and
details, lights plus a refused thermostat plus undo, the booking preview and
confirm flow, and the privacy gate. `POST /api/journeys/{name}/run` runs one
against a fresh `AppState`, so it cannot change live timers, bookings, or audit
rows. The CLI path remains available for a terminal-only rehearsal.

## Try it

```bash
curl -s localhost:8000/health
curl -s -H 'Authorization: Bearer dev-token' localhost:8000/api/tools

curl -s -X POST localhost:8000/mcp \
  -H 'Authorization: Bearer dev-token' \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
```

The assistant and the console write path, both through the same router:

```bash
curl -s -X POST localhost:8000/api/assistant/turn \
  -H 'Authorization: Bearer dev-token' \
  -H 'Content-Type: application/json' \
  -d '{"utterance":"set a ten minute timer"}'

curl -s -X POST localhost:8000/api/call/lights_set \
  -H 'Authorization: Bearer dev-token' \
  -H 'Content-Type: application/json' \
  -d '{"params":{"room":"office","brightness":40}}'

curl -s localhost:8000/api/state -H 'Authorization: Bearer dev-token'
curl -s localhost:8000/api/journeys -H 'Authorization: Bearer dev-token'
curl -s -X POST localhost:8000/api/journeys/timer/run -H 'Authorization: Bearer dev-token'
```

For the MCP Inspector (or the Alexa+ Local Inspector): transport
**Streamable HTTP**, URL `http://localhost:8000/mcp`, header
`Authorization: Bearer dev-token`.

## Local CLI

`uv run python -m app.cli` is a thin client over the official MCP SDK. It is useful for
checking the exact `tools/list` and `tools/call` path Alexa+ uses without opening
the inspector.

```bash
cd backend
uv run python -m app.cli tools
uv run python -m app.cli call timer_set '{"duration_seconds": 600}'
uv run python -m app.cli call book_room '{"date": "2026-10-23", "guests": 4}'
uv run python -m app.cli call undo '{}'
uv run python -m app.cli bench --n 100
uv run python -m app.cli audit verify
uv run python -m app.cli audit list --limit 20
```

`call` prints the structured response and exits non-zero on a business error.
`bench` reports p50, p95, p99, and max over one MCP session. `audit verify` exits
non-zero on a broken chain, so a script can gate on it. Point the CLI at a
deployment with `ALEXA_MCP_URL` and `ALEXA_TOKEN`.

## Responses
```json
{
  "status": "ok",
  "speech": "Timer set for 10 minutes.",
  "detail": null,
  "detail_available": true,
  "trace": [{"tool": "timer_set", "service": "timers", "ok": true, "ms": 0, "...": "..."}],
  "audit_id": "a_000004",
  "error": null,
  "preview": null,
  "confirmation_token": null
}
```

Concise mode is on by default, so `detail` is `null` and `detail_available` says
a longer explanation exists. Alexa+ offers it and calls `tell_me_more`, which
returns the same text as `speech`. Setting `concise_mode` to false puts `detail`
back in every response.

A failed rule returns `status: "error"` with `error.code`, `error.message`,
`error.follow_up`, and `allowed` where a range or enumeration applies. Business
errors are structured tool results, not MCP protocol errors, so Alexa+ can read
the follow-up.

## Confirmation flow

`book_room` is medium risk, so it takes two calls:

1. Call with the business parameters only. The server validates them, issues a
   token, and returns `status: "confirmation_required"` with a `preview`
   (`service`, `tool`, `params`, `effect`, `irreversible`) and a
   `confirmation_token`. Nothing is booked.
2. After the user confirms, call again with exactly the same parameters plus
   `confirmation_token`. The server re-checks the scope, recomputes the
   parameter hash, and executes once.

```json
{
  "status": "confirmation_required",
  "speech": "Book the Oak room on Friday, October 23 at 9 AM for 60 minutes, party of 4. Should I go ahead?",
  "preview": {
    "service": "booking",
    "tool": "book_room",
    "params": {"date": "2026-10-23", "guests": 4, "room": "oak", "start_time": "09:00", "duration_minutes": 60},
    "effect": "Book the Oak room on Friday, October 23 at 9 AM for 60 minutes, party of 4",
    "irreversible": false
  },
  "confirmation_token": "…",
  "audit_id": "a_000012",
  "error": null
}
```

Optional parameters are defaulted before hashing, so the preview and the
confirmation describe the same action. Replay returns `TOKEN_CONSUMED`, expiry
returns `TOKEN_EXPIRED`, and changed parameters return `INVALID_PARAM` with the
message "The request changed since it was previewed." A failed execution does
not consume the token, so a retry is possible.

## Audit chain

Every call appends one row, including a preview and a refusal. The row stores the
subject, tool, tool version, rules version, scopes used, parameter hash,
decision, status, error code, and the minimal inverse state an undo needs. It
never stores the raw parameters or the token.

```
row_hash(n) = SHA-256(canonical_json(row_fields) + row_hash(n-1))
```

The first row links to 64 zeroes. `GET /api/audit/verify` and
`alexa audit verify` rebuild the chain and report the first row whose link or
hash does not hold. `GET /api/audit` returns only the caller's rows: the chain is
global, but reading another subject's actions is not part of verifying it.

At startup the server seeds three fixed rows from `app/audit_seed.json` and
reports `audit_seeded: true` in `/health`. A Render redeploy clears the
container, so the seeded chain makes the reset read as intentional.

Retention is enforced when `retention_days` changes: older rows for that subject
are replaced by tombstones that keep the id, timestamp, tool, decision, and both
hashes. A tombstone cannot be recomputed from its contents, so verification
checks its link to the previous row and continues from its stored hash.

## Undo

`undo` with no parameters reverses the newest executed action, using the inverse
state stored in that action's audit row. It skips reads, previews, refusals, and
no-op changes, so "undo that" always means the last real change. Pass `audit_id`
to target a specific action from the console.

The undo row records `compensator_of` and `result_ref` pointing at the original
audit id, which is the link the console and the house screen show. Undo declares no
scopes of its own: the handler resolves the target row and checks the scopes that
row recorded before any adapter runs. Cancelling a booking is gated by
`third_party_sharing` because it reaches a service outside the household.

## Privacy and personalization

| Setting | Default | Effect |
|---|---|---|
| `retention_days` | 30 | 0, 7, 30, or 90. Enforced on change by tombstoning older rows |
| `personalization` | on | Off clears the detail history and ignores the stored concise preference |
| `microphone_mode` | `wake_word` | Declared in the manifest; the device enforces it, not this server |
| `third_party_sharing` | on | Off refuses `external=true` tools with `PRIVACY_BLOCKED` |
| `concise_mode` | on | On withholds `detail` and sets `detail_available` |

Every change is a `privacy_set` call, so it is validated by the rules and
written to the audit chain. `privacy_get` reports the current values.

## Data and state

There is no model, training data, or external dataset in this path. Alexa
is deterministic code, so the data it needs is small and explicit:

| Data | Where it lives now | Needed for the walkthrough |
|---|---|---|
| Static bearer tokens and their scopes | `ALEXA_TOKENS_JSON`, parsed at startup | Yes, one dev token |
| Users, sessions, OAuth states, exchange codes | SQLite locally, Render Postgres in production | Yes, created by sign-in |
| Tool manifests (scopes, risk, confirmation text) | `app/tools/*.py` | Yes |
| Value rules (types, bounds, enums, formats, defaults) | `app/rules/rules.yaml`, version `3` | Yes |
| Confirmation tokens | `app/confirm.py`, in memory, 300-second TTL | Yes, created by booking |
| Per-user timer, light, climate, and booking state | In-memory adapters | Yes, created by calls |
| Audit chain | `app/audit.py`, in memory, seeded at startup from `audit_seed.json` | Yes, one row per call |
| Privacy and concise settings | `app/privacy.py`, in memory, defaults per subject | Yes, changed by `privacy_set` |
| Last action details for `tell_me_more` | `app/memory.py`, 20 per subject | Yes, filled by every executed call |

Accounts and sessions persist. Everything else is in process memory: a
redeploy or restart clears timers, lights, climate, bookings, traces, privacy
settings, pending confirmations, and the audit chain. `BUILD_PLAN.md` accepts
that tradeoff for now, so the server rebuilds a known seeded chain at boot
and reports the marker. A lost confirmation is safe: the user is asked again.

### How Alexa+ uses the data

1. Alexa+ turns speech into a tool call, for example `lights_set` with
   `{"room": "living_room", "brightness": 30}`.
2. The server checks the token's scopes, validates the values against the
   versioned rules, and reads the caller's current state.
3. The adapter changes state for that `subject` only. Another subject never sees
   or changes it. A medium-risk action first returns a preview and a
   single-use token; nothing changes until the token is presented.
4. The response carries `speech` (what Alexa+ says), optional `detail` (offered
   as a follow-up), `trace` (what the console shows), and `audit_id` (the row
   that records the decision).
5. Alexa+ never receives device credentials and never writes state directly.

So the only data input you need to prepare is a token (already in `.env.example`).
Everything else is created by assistant calls. If you later attach real devices,
the adapter boundary is where a device API or a Postgres state store plugs in,
and `subject` becomes the household key for both state and audit rows.

## Tests and lint

```bash
uv run pytest -q                 # 130 passed
uv run ruff check .
uv run ruff format --check .

cd ..
python3 scripts/check_leaks.py --self-test
python3 scripts/check_leaks.py --all
```

The suite includes a live MCP round trip over uvicorn: initialize, `tools/list`,
`tools/call`, a refused out-of-bounds call, a booking preview, confirmation, and
replay refusal, the trace on `/api/trace`, an undo linked in `/api/audit`, a
green `/api/audit/verify`, and the privacy gate refusing a booking. It also
covers chain tampering and row removal, tombstones, seeded determinism, undo for
every reversible tool, scope refusal on undo, concise mode, and per-user privacy
isolation.

CI runs the same checks, verifies that `requirements.txt` matches `uv.lock`, and
builds the image with a live `/health` check. Enable the pre-commit leak scan
once per clone:

```bash
git config core.hooksPath .githooks
```

## Docker

```bash
docker build -t alexa .
docker run --rm -p 8000:8000 \
  -e ALEXA_PUBLIC_URL=https://your-service.example.com \
  -e ALEXA_TOKENS_JSON='{"...":"..."}' \
  alexa
```

Set `ALEXA_PUBLIC_URL` to the Render HTTPS origin. Set
`ALEXA_ALLOWED_HOSTS` to the Render hostname (without `https://`) to re-enable
the DNS-rebinding guard; `*` disables it. Set `DATABASE_URL` to the Render
Postgres internal URL and set `ALEXA_CORS_ORIGINS` to the Vercel and local
frontend origins.

`requirements.txt` is generated from `uv.lock`, not edited by hand:

```bash
uv export --frozen --no-dev --no-hashes --no-header -o requirements.txt
```

The image runs as UID 10001, installs the pinned transitive set, and has a
Docker health check against `/health`. Render uses its own health check against
the same path.

## Layout

```
backend/
├── app/
│   ├── main.py            # FastAPI, mounts /mcp and the /api routers
│   ├── cli.py             # local MCP client: tools, call, whoami, bench, audit
│   ├── mcp_server.py      # MCPServer, tool registration, auth context
│   ├── router.py          # auth -> rules -> privacy -> confirmation -> adapter -> audit
│   ├── api/               # console REST: auth, config, state, privacy, call, assistant, voice, journeys
│   ├── accounts/          # Google OAuth, account store, session verifier
│   ├── assistant/         # deterministic parser, pending confirmation, reply envelope
│   ├── voice/             # ElevenLabs proxy, bounded cache, typed fallback
│   ├── journeys/          # YAML schema, loader, isolated runner, fixtures
│   ├── rules/             # engine.py, rules.yaml (versioned value rules)
│   ├── confirm.py         # single-use confirmation tokens
│   ├── audit.py           # hash-chained log, verify, retention tombstones
│   ├── audit_seed.json    # deterministic startup fixture
│   ├── privacy.py         # per-user settings and the concise preference
│   ├── memory.py          # last action details for tell_me_more
│   ├── auth.py            # Principal, static bearer tokens, 401 challenge
│   ├── models.py          # response, preview, and error contract
│   ├── trace.py           # in-memory ring buffer
│   ├── adapters/          # simulated timers, lights, climate, booking
│   └── tools/             # manifests and handlers, including undo and privacy
└── tests/                 # unit, HTTP, auth, voice, journey, and live MCP integration tests
```

## Next

- Wire the sign-in, callback, and account screens to the auth routes.
- Finish the React console screens: Trace, Audit, Privacy, Journeys, and the
  assistant bar.
- Set `ALEXA_ELEVENLABS_API_KEY` for the voice, or rely on browser speech.
- Deploy the API to Render with Postgres, the console to Vercel, and rehearse
  against the deployed origins.

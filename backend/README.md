# Alexa backend

Day 2 of the build plan: a rules-driven MCP server with confirmation tokens and
a simulated booking flow.

What runs today:

- MCP Streamable HTTP endpoint at `/mcp` (spec 2025-11-25, via `mcp` 2.3).
- Bearer auth on every MCP and console request. Unauthenticated calls get a
  `401` with an RFC 9728 `WWW-Authenticate` challenge and protected-resource
  metadata.
- Four tools: `timer_set`, `lights_set`, and `thermostat_set` (low risk), plus
  `book_room` (medium risk, preview and confirmation).
- Versioned YAML rules in `app/rules/rules.yaml`: types, bounds, enums, date and
  time formats, labels, and defaults. The rules version is published with every
  manifest.
- Single-use confirmation tokens bound to the subject, tool, and canonical
  parameter hash, with a 300-second TTL. Replay, expiry, and changed parameters
  are refused.
- Deterministic validation of required fields, rooms, zones, dates, times, and
  numeric bounds, with the full error taxonomy from `STANDARD.md`.
- In-memory simulated adapters, per-user state, a trace ring buffer, and
  structured JSON logs.

The hash-chained audit log, undo, privacy toggles, and `tell_me_more` land on
Day 3. `audit_id` is intentionally `null` until then.

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

> **Auth note.** This is a resource server with a static token table, not a full
> OAuth 2.1 authorization server. The 401 challenge and RFC 9728 metadata are
> spec-correct, but the advertised issuer (`ALEXA_PUBLIC_URL`) does not yet
> serve authorization-server metadata. Alexa+ registration may require an OAuth
> flow; if it does, add an authorization server before Day 4. Day 1 verification
> with the Local Inspector works by sending `Authorization: Bearer dev-token`.

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST/GET/DELETE | `/mcp` | Bearer | MCP Streamable HTTP |
| GET | `/health` | none | App Runner health check |
| GET | `/api/whoami` | Bearer | Subject, client, and scopes for a token |
| GET | `/api/tools` | Bearer | Tool manifests, per-field rules, rules version, confirmation TTL |
| GET | `/api/trace?limit=50` | Bearer | Newest-first in-memory trace |
| GET | `/.well-known/oauth-protected-resource/mcp` | none | RFC 9728 metadata |

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
uv run python -m app.cli bench --n 100
```

`call` prints the structured response and exits non-zero on a business error.
`bench` reports p50, p95, p99, and max over one MCP session. Point it at a
deployment with `ALEXA_MCP_URL` and `ALEXA_TOKEN`.

## Responses
```json
{
  "status": "ok",
  "speech": "Timer set for 10 minutes.",
  "detail": "Timer 'pasta' set for 10:00, ending at 18:42:07 UTC. Stored as timer_7f3a.",
  "trace": [{"tool": "timer_set", "service": "timers", "ok": true, "ms": 0, "...": "..."}],
  "audit_id": null,
  "error": null,
  "preview": null,
  "confirmation_token": null
}
```

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
  "audit_id": null,
  "error": null
}
```

Optional parameters are defaulted before hashing, so the preview and the
confirmation describe the same action. Replay returns `TOKEN_CONSUMED`, expiry
returns `TOKEN_EXPIRED`, and changed parameters return `INVALID_PARAM` with the
message "The request changed since it was previewed." A failed execution does
not consume the token, so a retry is possible.

## Data and state

There is no model, training data, or external dataset in this path. Alexa
is deterministic code, so the data it needs is small and explicit:

| Data | Where it lives now | Needed for the demo |
|---|---|---|
| Bearer tokens and their scopes | `ALEXA_TOKENS_JSON`, parsed at startup | Yes, one dev token |
| Tool manifests (scopes, risk, confirmation text) | `app/tools/*.py` | Yes |
| Value rules (types, bounds, enums, formats, defaults) | `app/rules/rules.yaml`, version `2` | Yes |
| Confirmation tokens | `app/confirm.py`, in memory, 300-second TTL | Yes, created by booking |
| Per-user timer, light, climate, and booking state | In-memory adapters | Yes, created by calls |
| Privacy settings | Not built yet (Day 3) | Not yet |
| Audit entries | Not built yet (Day 3), seeded fixture then | Not yet |

Nothing is persisted across restarts yet. On App Runner a redeploy clears timers,
lights, climate, bookings, traces, and pending confirmations. `BUILD_PLAN.md`
accepts that tradeoff for the demo and adds a seeded audit fixture on Day 3 so a
reset is visible rather than silent. A lost confirmation is safe: the user is
asked again.

### How Alexa+ uses the data

1. Alexa+ turns speech into a tool call, for example `lights_set` with
   `{"room": "living_room", "brightness": 30}`.
2. The server checks the token's scopes, validates the values against the
   versioned rules, and reads the caller's current state.
3. The adapter changes state for that `subject` only. Another subject never sees
   or changes it. A medium-risk action first returns a preview and a
   single-use token; nothing changes until the token is presented.
4. The response carries `speech` (what Alexa+ says), optional `detail` (offered
   as a follow-up), and `trace` (what the console shows).
5. Alexa+ never receives device credentials and never writes state directly.

So the only data input you need to prepare is a token (already in `.env.example`).
Everything else is created by the demo calls. If you later attach real devices,
the adapter boundary is where a device API or a Postgres state store plugs in,
and `subject` becomes the household key for both state and audit rows.

## Tests and lint

```bash
uv run pytest -q                 # 76 passed
uv run ruff check .
uv run ruff format --check .

cd ..
python3 scripts/check_leaks.py --self-test
python3 scripts/check_leaks.py --all
```

The suite includes a live MCP round trip over uvicorn: initialize, `tools/list`,
`tools/call`, a refused out-of-bounds call, a booking preview, confirmation, and
replay refusal, and the trace appearing on `/api/trace`. It also covers tool
annotations and output schemas, the CLI, per-user isolation, confirmation
expiry and cross-user use, and a latency guard on the in-memory hot path.

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

Set `ALEXA_PUBLIC_URL` to the App Runner HTTPS origin. Set
`ALEXA_ALLOWED_HOSTS` to the App Runner hostname (without `https://`) to
re-enable the DNS-rebinding guard; `*` disables it.

`requirements.txt` is generated from `uv.lock`, not edited by hand:

```bash
uv export --frozen --no-dev --no-hashes --no-header -o requirements.txt
```

The image runs as UID 10001, installs the pinned transitive set, and has a
Docker health check against `/health`. App Runner uses its own health check
against the same path.

## Layout

```
backend/
├── app/
│   ├── main.py            # FastAPI, mounts /mcp, REST console API
│   ├── cli.py             # local MCP client: tools, call, whoami, bench
│   ├── mcp_server.py      # MCPServer, tool registration, auth context
│   ├── router.py          # auth -> rules -> confirmation -> adapter -> trace
│   ├── rules/             # engine.py, rules.yaml (versioned value rules)
│   ├── confirm.py         # single-use confirmation tokens
│   ├── auth.py            # static bearer tokens, scopes, 401 challenge
│   ├── models.py          # response, preview, and error contract
│   ├── trace.py           # in-memory ring buffer
│   ├── adapters/          # simulated timers, lights, climate, booking
│   └── tools/             # manifests and handlers
└── tests/                 # unit and live MCP integration tests
```

## Next (Day 3)

- Hash-chained audit log with a seeded startup fixture and `alexa audit verify`.
- Undo tools for timers, lights, climate, and bookings, linked to the original.
- `tell_me_more`, concise mode, and privacy toggles (`third_party_sharing` blocks
  the already-marked `external=true` booking tool).

# Alexa backend

Day 1 of the build plan: the MCP server skeleton that Alexa+ can connect to.

What runs today:

- MCP Streamable HTTP endpoint at `/mcp` (spec 2025-11-25, via `mcp` 2.3).
- Bearer auth on every MCP and console request. Unauthenticated calls get a
  `401` with an RFC 9728 `WWW-Authenticate` challenge and protected-resource
  metadata.
- Two tools, both low risk: `timer_set` and `lights_set`.
- Deterministic validation of required fields, rooms, and numeric bounds.
- The shared response contract (`status`, `speech`, `detail`, `trace`, `error`)
  and the full error taxonomy from `STANDARD.md`.
- In-memory simulated adapters, per-user state, a trace ring buffer, and
  structured JSON logs.

Audit chain, confirmation tokens, privacy toggles, undo, and the booking tool
are Days 2 and 3. `audit_id` is intentionally `null` until the audit log lands.

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
| GET | `/api/tools` | Bearer | Tool manifests for the console |
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

## Responses
```json
{
  "status": "ok",
  "speech": "Timer set for 10 minutes.",
  "detail": "Timer 'pasta' set for 10:00, ending at 18:42:07 UTC. Stored as timer_7f3a.",
  "trace": [{"tool": "timer_set", "service": "timers", "ok": true, "ms": 0, "...": "..."}],
  "audit_id": null,
  "error": null
}
```

A failed rule returns `status: "error"` with `error.code`, `error.message`,
`error.follow_up`, and `allowed` where a range or enumeration applies. Business
errors are structured tool results, not MCP protocol errors, so Alexa+ can read
the follow-up.

## Data and state

There is no model, training data, or external dataset in this path. Alexa
is deterministic code, so the data it needs is small and explicit:

| Data | Where it lives now | Needed for the demo |
|---|---|---|
| Bearer tokens and their scopes | `ALEXA_TOKENS_JSON`, parsed at startup | Yes, one dev token |
| Tool manifests (scopes, risk, bounds) | `app/tools/*.py` | Yes |
| Room list and numeric bounds | Tool specs | Yes |
| Per-user timer and light state | In-memory adapters | Yes, created by calls |
| Privacy settings | Not built yet (Day 3) | Not yet |
| Audit entries | Not built yet (Day 3), seeded fixture then | Not yet |

Nothing is persisted across restarts yet. On App Runner a redeploy clears timers,
lights, and traces. `BUILD_PLAN.md` accepts that tradeoff for the demo and adds a
seeded audit fixture on Day 3 so a reset is visible rather than silent.

### How Alexa+ uses the data

1. Alexa+ turns speech into a tool call, for example `lights_set` with
   `{"room": "living_room", "brightness": 30}`.
2. The server checks the token's scopes, validates the values against the
   manifest, and reads the caller's current state.
3. The adapter changes state for that `subject` only. Another subject never sees
   or changes it.
4. The response carries `speech` (what Alexa+ says), optional `detail` (offered
   as a follow-up), and `trace` (what the console shows).
5. Alexa+ never receives device credentials and never writes state directly.

So the only data input you need to prepare is a token (already in `.env.example`).
Everything else is created by the demo calls. If you later attach real devices,
the adapter boundary is where a device API or a Postgres state store plugs in,
and `subject` becomes the household key for both state and audit rows.

## Tests and lint

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

The suite includes a live MCP round trip over uvicorn: initialize, `tools/list`,
`tools/call`, a refused out-of-bounds call, and the trace appearing on
`/api/trace`.

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

## Layout

```
backend/
├── app/
│   ├── main.py            # FastAPI, mounts /mcp, REST console API
│   ├── mcp_server.py      # MCPServer, tool registration, auth context
│   ├── router.py          # auth -> rules -> adapter -> response -> trace
│   ├── rules.py           # deterministic validation (becomes YAML on Day 2)
│   ├── auth.py            # static bearer tokens, scopes, 401 challenge
│   ├── models.py          # response and error contract
│   ├── trace.py           # in-memory ring buffer
│   ├── adapters/          # simulated timers and lights
│   └── tools/             # manifests and handlers
└── tests/                 # unit and live MCP integration tests
```

## Next (Day 2)

- Versioned YAML rules and conflict checks (`NO_CHANGE`).
- Confirmation tokens bound to the canonical parameter hash.
- Booking tool (medium risk) with preview, confirm, and replay refusal.
- `OUT_OF_BOUNDS` / `CONFIRMATION_REQUIRED` journeys.

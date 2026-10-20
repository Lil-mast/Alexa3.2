# Build log

A running record of what is implemented, what was verified, and what is still
open. The plan is in `BUILD_PLAN.md`; the contracts are in `TECHNICAL.md` and
`STANDARD.md`.

## 2026-10-20: Day 1, server skeleton

Status: complete for the local scope. Alexa+ registration and the App Runner
deployment are still blocked on external access.

### Delivered

The `backend/` tree now contains a working MCP server:

| Area | Files | What it does |
|---|---|---|
| App entry | `app/main.py` | FastAPI app, mounts the MCP app at `/mcp`, serves the console API and health check |
| MCP wiring | `app/mcp_server.py` | `MCPServer` from `mcp` 2.3.0, tool registration, auth settings, per-request principal |
| Decision path | `app/router.py` | auth, scope check, validation, adapter call, response, trace, JSON log |
| Rules | `app/rules.py` | required fields, types, enums, numeric bounds, spoken error labels |
| Manifests | `app/tools/specs.py`, `app/tools/timers.py`, `app/tools/lights.py` | tool contracts and handlers |
| Auth | `app/auth.py` | static bearer table, scopes, expiry, 401 challenge, REST dependency |
| Adapters | `app/adapters/timers.py`, `app/adapters/lights.py` | simulated per-user device state |
| Contract | `app/models.py`, `app/canonical.py` | response shape, error taxonomy, canonical hashes |
| Observability | `app/trace.py`, `app/logging_config.py` | in-memory console trace and one-line JSON logs |
| Tests | `tests/` | 35 unit and integration tests, including a live MCP round trip |
| Packaging | `Dockerfile`, `requirements.txt`, `pyproject.toml`, `uv.lock`, `.env.example`, `.dockerignore` | local run and App Runner image |

### Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST/GET/DELETE | `/mcp` | Bearer | MCP Streamable HTTP |
| GET | `/health` | none | App Runner health check |
| GET | `/api/whoami` | Bearer | subject, client, scopes for a token |
| GET | `/api/tools` | Bearer | tool manifests for the console |
| GET | `/api/trace?limit=50` | Bearer | newest-first in-memory trace |
| GET | `/.well-known/oauth-protected-resource/mcp` | none | RFC 9728 metadata |

Unauthenticated MCP calls return `401` with a `WWW-Authenticate` header that
points at the metadata URL. The console API uses the same verifier and the same
challenge.

### Tools and rules

| Tool | Risk | Scope | Parameters | Bounds |
|---|---|---|---|---|
| `timer_set` | low | `home:timers:write` | `duration_seconds`, optional `label` | 1 to 86400 seconds, label at most 64 characters |
| `lights_set` | low | `home:lights:write` | `room`, optional `on`, optional `brightness` | room is one of four values, brightness 0 to 100, at least one of `on` and `brightness` required |

Both tools execute immediately, write a trace event, and return a short `speech`
sentence plus optional `detail`. The response shape is:

```json
{
  "status": "ok | confirmation_required | error",
  "speech": "Timer set for 10 minutes.",
  "detail": "Timer 'pasta' set for 10:00, ending at 18:42:07 UTC. Stored as timer_7f3a.",
  "trace": [{"tool": "timer_set", "service": "timers", "ok": true, "ms": 0}],
  "audit_id": null,
  "error": null
}
```

Business errors are structured tool results, not MCP protocol errors, so Alexa+
can read `error.follow_up` and ask a specific question. `audit_id` is null until
the audit log lands.

### Decisions and gotchas

- `mcp` 2.3.0 renamed `FastMCP` to `MCPServer`. The server uses the 2.x API and
  supports the 2025-11-25 and 2026-07-28 protocol versions.
- The MCP app is mounted at `/` with its own route at `/mcp`. Mounting it at
  `/mcp` with an inner route of `/` produced a 307 under Starlette 1.x, which
  broke the streamable client. The mount order keeps `/health`, `/api`, `/docs`,
  and the metadata route outside the MCP session code.
- A mounted app's lifespan does not run automatically, so `create_app()` starts
  the streamable session manager in the FastAPI lifespan.
- Tool handlers re-verify the bearer token from the current request headers
  instead of trusting a session context variable. A revoked or expired token
  stops working inside an open session.
- The server is a resource server with a static token table, not a full OAuth
  2.1 authorization server. The 401 challenge and metadata are correct, but the
  advertised issuer does not serve authorization-server metadata yet.
- All device state is in memory and is per `subject`. A redeploy clears timers,
  lights, and traces. The Day 3 audit seed makes that reset visible.
- The adapter timeout setting exists but is unused until Day 2 adds real timeout
  handling.

### Naming

The project name is Alexa. The package, MCP server name, env prefix, logger
names, client IDs, Docker image, and docs all use `Alexa`, `alexa`, or `ALEXA_`.
The old working name no longer appears anywhere in the repository.

### Verification

Commands run from `backend/`:

```bash
uv run pytest -q                 # 35 passed
uv run ruff check .              # clean
uv run ruff format --check .     # clean
```

The suite covers parameter validation, per-user isolation, scope refusal without
side effects, token expiry, the 401 challenge, the metadata document, and a live
MCP client that initializes, lists tools, calls `timer_set` and `lights_set`,
receives a structured `OUT_OF_BOUNDS` result, and reads the trace back over
`/api/trace`.

Manual smoke test against a running server:

```text
timer_set {"duration_seconds": 600, "label": "pasta"}
  -> ok, "Timer set for 10 minutes."
lights_set {"room": "living_room", "brightness": 30}
  -> ok, "Living room lights set to 30 percent."
lights_set {"room": "garage", "on": true}
  -> error OUT_OF_BOUNDS, "Room must be one of: living room, bedroom, kitchen, office."
```

### Open items

- Register the server with Alexa+ and run the Alexa+ Local Inspector against the
  live URL. Needs developer access, so it was not possible here.
- Deploy the image to App Runner and set `ALEXA_PUBLIC_URL` and
  `ALEXA_TOKENS_JSON`.
- Add an OAuth authorization server if Alexa+ registration requires an OAuth
  flow instead of a static bearer token.
- Day 2: versioned YAML rules, `NO_CHANGE`, confirmation tokens bound to the
  parameter hash, and the booking tool with preview, confirm, and replay refusal.
- Day 3: hash-chained audit log and seeded fixture, `alexa audit verify` CLI,
  undo for timers and lights, `tell_me_more`, concise mode, and privacy toggles.
- Day 4: React console (Trace and Audit), ElevenLabs voice proxy, journeys,
  final deploy, and demo rehearsal.
- Persistence: SQLite or Postgres for audit, settings, and tokens. In-memory
  device state is acceptable for the demo and documented as such.
- Real device integrations remain out of scope. The adapter boundary is the
  integration point.

### Next step

Start Day 2 by moving bounds out of `ToolSpec` and into a versioned YAML rules
file, then add the confirmation token service and the booking tool. Keep the
existing `Router.execute` flow so MCP, REST, and tests continue to share it.

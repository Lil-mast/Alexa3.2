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
- The adapter timeout setting exists but is unused: the simulated adapters are
  synchronous and instant. Real adapters need the timeout wrapper before they
  replace these.

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
- Day 2 is complete; see the next section for the rules engine, confirmation
  tokens, and the booking tool.
- Day 3: hash-chained audit log and seeded fixture, `alexa audit verify` CLI,
  undo for timers, lights, climate, and bookings, `tell_me_more`, concise mode,
  and privacy toggles.
- Day 4: React console (Trace and Audit), ElevenLabs voice proxy, journeys,
  final deploy, and demo rehearsal.
- Persistence: SQLite or Postgres for audit, settings, and tokens. In-memory
  device state is acceptable for the demo and documented as such.
- Real device integrations remain out of scope. The adapter boundary is the
  integration point.

### Next step

Day 2 is complete. Start Day 3 by putting the audit table behind the router's
`_finish` decision, so an executed, previewed, or refused call writes one row
with `rules_version` and the parameter hash. Keep `Router.execute` as the single
decision path.


## 2026-10-21: Day 2, rules, confirmations, booking

Status: complete for the local scope. Alexa+ registration and the App Runner
deployment are still blocked on external access.

### Delivered

| Area | Files | What it does |
|---|---|---|
| Rules data | `app/rules/rules.yaml` | Versioned (`version: "2"`) bounds, enums, formats, labels, and defaults for every tool |
| Rules engine | `app/rules/engine.py`, `app/rules/__init__.py` | Loads and validates the YAML once, applies defaults, and returns structured violations |
| Confirmation service | `app/confirm.py` | Single-use tokens bound to subject, tool, and canonical parameter hash; 300-second TTL |
| Booking | `app/tools/booking.py`, `app/adapters/booking.py` | Medium-risk room booking with preview, confirm, replay refusal, and conflict detection |
| Climate | `app/tools/thermostat.py`, `app/adapters/climate.py` | Low-risk thermostat setpoint, the demo's `OUT_OF_BOUNDS` example |
| Router | `app/router.py` | Auth, scope, rules, preview/token, execute, consume, response, trace |
| Contract | `app/models.py` | `preview`, `confirmation_token`, and the `no_change` handler decision |
| Registry | `app/tools/__init__.py`, `app/main.py` | Four tools; `/api/tools` publishes the rules version, TTL, and per-field rules |
| Tests | `tests/test_booking.py`, `tests/test_confirmation.py`, updated suites | 65 Day 2 tests; 76 in the suite at the time of writing, including a live MCP preview/confirm/replay journey |

### Tools and rules

| Tool | Risk | Scope | Parameters | Rules |
|---|---|---|---|---|
| `timer_set` | low | `home:timers:write` | `duration_seconds`, optional `label` | 1 to 86400 seconds, label at most 64 characters |
| `lights_set` | low | `home:lights:write` | `room`, optional `on`, optional `brightness` | Four rooms, brightness 0 to 100, at least one of `on` and `brightness` |
| `thermostat_set` | low | `home:climate:write` | `zone`, `target_c` | Four zones, 16 to 28 degrees Celsius |
| `book_room` | medium | `booking:rooms:write` | `date`, optional `room`, `start_time`, `duration_minutes`, `guests`, `title`, `confirmation_token` | Date at or after today, 15 to 480 minutes, 1 to 12 guests, three rooms; defaults oak, 09:00, 60, 1 |

Bounds are no longer code in `ToolSpec`. `ToolSpec` declares identity, risk,
scopes, required and optional fields, and the confirmation template; the YAML
declares every value rule. `RULES.check_tools(TOOLS)` runs at startup and fails
if a tool and its rules drift apart. `RuleSet.display_params` turns enum values,
dates, and times into speakable text for the preview.

Defaults are applied inside `validate_params`, before the parameter hash. A
preview and its confirmation therefore describe the same effective action even
when the client omits optional fields on one call and sends them on the other.

### Confirmation flow

1. A medium-risk call without a token validates the parameters, issues a token,
   and returns `status: confirmation_required` with `preview` and
   `confirmation_token`. No adapter runs and the trace decision is `previewed`.
2. A second call with the same parameters and the token re-checks the scope,
   recomputes the hash, and compares subject, tool, hash, expiry, and use.
3. A valid token executes the adapter, then is consumed. A failed execution
   (for example a booking conflict) does not consume it, so a retry is possible.
4. Replay returns `TOKEN_CONSUMED`. Expired or unknown tokens return
   `TOKEN_EXPIRED`. Another user's token reads as `TOKEN_EXPIRED`, not as a
   valid token owned by someone else.
5. Changed parameters return `INVALID_PARAM` with the message "The request
   changed since it was previewed." The original token stays valid for the
   action the user actually saw.

Example preview:

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

### Decisions and gotchas

- PyYAML uses YAML 1.1, where an unquoted `on:` mapping key becomes `True`. The
  lights `"on"` field is quoted, and `rules.yaml` says why.
- The rules package types against `ToolSpec` under `TYPE_CHECKING` only. A
  runtime import would close the `app.tools -> app.state -> app.rules ->
  app.tools` cycle.
- `manifests()` imports the rules lazily for the same reason.
- A past booking date is a YAML rule (`not_past: true`), not a handler check, so
  it is refused at preview time before a token is issued.
- Room keys are duplicated between the YAML and the adapters on purpose: the
  YAML is the reviewed data, the adapter is the integration point. A test
  asserts the two lists match, so drift fails CI.
- `thermostat_set` at its current setpoint returns `status: ok` with trace
  decision `no_change`, not a fake success and not an error.
- MCP annotations are derived from the same manifest the console reads
  (`annotations_for`): title, `idempotent_hint`, and `open_world_hint`. Lights
  and climate are marked idempotent because repeating the same setpoint is
  harmless; booking is `open_world_hint` because it is the `external` tool.
- Booking availability is checked at execution, not preview. The preview
  describes the requested action; a slot taken between preview and confirmation
  fails at confirm and leaves the token usable. A preflight hook is a possible
  Day 3 improvement.
- The adapter timeout setting is still unused: all adapters are synchronous and
  instant. Real adapters need the timeout wrapper before they replace these.
- `audit_id` is still null. Day 3 adds the audit table behind the same decision
  point in `Router._finish`.

### Verification

Commands run from `backend/`:

```bash
uv run pytest -q              # 76 passed at the time of writing (65 Day 2 tests)
uv run ruff check .            # clean
uv run ruff format --check .   # clean
uv lock                        # pyyaml added
```

The suite now covers YAML loading and drift checks, thermostat bounds and
`NO_CHANGE`, booking defaults and formats, preview side-effect freedom, confirm,
replay, expiry, parameter mismatch, cross-user token use, conflict handling, and
a live MCP client that previews, confirms, replays, and reads the previewed /
executed / refused decisions back from `/api/trace`.

Manual smoke test:

```text
thermostat_set {"zone": "office", "target_c": 35}
  -> error OUT_OF_BOUNDS, "Temperature must be between 16 and 28 degrees Celsius."
book_room {"date": "2026-10-23", "guests": 4}
  -> confirmation_required, "Book the Oak room on Friday, October 23 at 9 AM for 60 minutes, party of 4. Should I go ahead?"
book_room {same params, confirmation_token}
  -> ok, "Booked the Oak room on Friday, October 23 at 9 AM for 1 hour."
book_room {same params, same token}
  -> error TOKEN_CONSUMED, "That confirmation was already used. Start a new request."
```

### Open items

- Register the server with Alexa+ and run the Local Inspector against the live
  URL. Still blocked on developer access.
- Deploy the image to App Runner and set `ALEXA_PUBLIC_URL` and
  `ALEXA_TOKENS_JSON`.
- Day 3: hash-chained audit log and seeded fixture, `alexa audit verify` CLI,
  undo tools for timers, lights, climate, and booking, `tell_me_more`, concise
  mode, and privacy toggles.
- The privacy gate is not wired yet. `book_room` is already marked
  `external=true`, so Day 3 only needs the setting check in the router.
- No high-risk tool exists yet, so the certification gate is not implemented.
- Tokens and device state reset on restart. Pending confirmations become invalid,
  which is safe; the user is asked again.

### Next step

Day 3: add the hash-chained audit table and write a row from `_finish` for every
decision, including previews and refusals. Record `rules_version`, the parameter
hash, the decision, and the compensator link. Then add undo through the existing
router so it gets the same auth, rules, and audit path.


## 2026-10-21: Competitor review and hardening

Reviewed [KayLerch/alexa-skill-mcp-bridge](https://github.com/KayLerch/alexa-skill-mcp-bridge)
at commit `ca2c2ef` (2026-09-05, Apache-2.0). It is a strong project, but it is a
different product: an Alexa Skill, a Lambda, and an AgentCore Runtime that
emulate the Alexa+ MCP client with a Strands agent on Nova 2 Lite. It lets a
developer test any MCP server on a physical Alexa+ device. Alexa is the server
that runs after Alexa+ chooses a tool: deterministic rules, confirmation tokens,
and an audit path. The two are complementary. Their bridge could test this
server; it cannot replace it.

### What the competitor does better

- CI runs lint, build, tests, a leak scan, and a CDK synth. The leak scan also
  runs in a pre-commit hook.
- `docs/decisions.md` records every decision with a rationale and the condition
  that would reverse it, plus a dated verification log.
- `docs/troubleshooting.md` turns real failures into a diagnosis path.
- `docs/cost.md` explains the cost model and what to tear down.
- A local `chat` harness gives a fast loop without a device.
- Latency is measured, not assumed: roughly 1.4 to 2.5 seconds per model turn in
  their recorded runs, with a budget for the Alexa request.
- Raw Alexa ids are hashed at the edge, and logs carry hashed ids only.
- The README has an explicit trust-boundary and "what not to commit" section.
- Protocol versions are checked and a mismatch is surfaced to the developer.

### What we adopted

- **CI** in `.github/workflows/ci.yml`: ruff, format, pytest, a requirements
  drift check, the leak scan, and a Docker build with a live `/health` check.
- **Leak scan and hook** in `scripts/check_leaks.py` and `.githooks/pre-commit`.
  It scans staged files by default and the whole tree with `--all`. It has a
  `--self-test` so a broken regex fails before it hides a secret.
- **Decision log** in `DECISIONS.md`, with reasons and revisit conditions.
- **Troubleshooting** in `TROUBLESHOOTING.md`, based on the failures we actually
  hit: 401, 421, the 307 mount issue, confirmation errors, Docker, and the leak
  scan.
- **Agent guide** in `AGENTS.md`: commands, layout, invariants, style, and the
  current state.
- **Local MCP CLI** in `backend/app/cli.py`: `tools`, `call`, `whoami`, and
  `bench`. It is a thin SDK client, not an Alexa+ simulator, so it exercises the
  same contract without a model in the loop.
- **Latency evidence**: a p95 guard in `tests/test_latency.py` and a real
  measurement from the CLI.
- **Tool annotations from the manifest**: `title`, `idempotentHint`, and
  `openWorldHint` now come from `ToolSpec`, so the MCP surface and the console
  cannot disagree.
- **Security defaults**: startup warnings for the development token, `*` host
  protection, and a non-HTTPS public URL; raw `amzn1.` subjects are refused at
  token parsing; the image runs as UID 10001 with pinned transitive dependencies.
- **README sections** for connecting Alexa+ and for security and privacy.

### What we did not adopt

- **A model in the request path.** Their agent chooses tools and composes
  answers, which is the point of a bridge. Our thesis is the opposite: Alexa+
  owns interpretation, and the server owns deterministic execution and speech.
- **AgentCore, Strands, Bedrock, and CDK.** They are the right infrastructure for
  a model-hosted bridge. Our public surface is one App Runner container.
- **Custom Alexa Skill interaction model generation.** We are an Alexa+ add-on,
  not a custom Skill. Generating intents and utterances would test a client we do
  not ship.
- **Elicitation parking.** Their bridge can hold a `tools/call` open while the
  user answers a question. Our confirmation flow uses a single-use token bound
  to the parameter hash, which survives reconnects and is replay-safe. See
  `DECISIONS.md` D11.
- **Their chat UI and memory layer.** We do not store utterances or preferences
  yet, and the Day 3 privacy design should decide that explicitly.

### Measured result

On 2026-10-21, locally, against uvicorn over Streamable HTTP, using the local MCP
CLI and 100 `lights_set` calls on one session:

```text
lights_set n=100 p50=6.84ms p95=9.20ms p99=13.88ms max=13.97ms
```

That number includes the MCP client, JSON-RPC, auth, validation, the adapter, the
trace, and the response. It is not a cloud measurement and not a comparison of
the same workload: their recorded 1.4 to 2.5 seconds covers two model calls.
It does show that removing the model from the action path leaves a wide latency
margin for App Runner and the Alexa request budget.

### Verification after the hardening pass

```bash
cd backend
uv run pytest -q                 # 76 passed
uv run ruff check .              # clean
uv run ruff format --check .     # clean

cd ..
python3 scripts/check_leaks.py --self-test   # 16 cases passed
python3 scripts/check_leaks.py --all         # clean
```

The Docker build and smoke test are in CI. Docker is not installed on this
machine, so the image itself was not built locally. `requirements.txt` was
regenerated from `uv.lock` and the CI drift check keeps it current.

### Remaining gaps

- Alexa+ registration and a physical device or Local Inspector run. Still needs
  developer access.
- App Runner deployment and a real `ALEXA_TOKENS_JSON`.
- An OAuth 2.1 authorization server if registration requires one.
- Day 3 audit, undo, `tell_me_more`, concise mode, and privacy toggles.
- Day 4 console, voice proxy, journeys, and certification.
- A license for this repository. That is an owner decision, not something to
  copy from a competitor.

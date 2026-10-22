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


## 2026-10-22: Day 3, audit chain, undo, concise mode, privacy

Status: complete for the local scope. All four Day 3 exit conditions hold:
`audit verify` is green, undo is logged and linked through the chain, a
third-party booking is refused when sharing is off, and concise mode returns the
detail through `tell_me_more`.

### Delivered

| Area | Files | What it does |
|---|---|---|
| Audit chain | `app/audit.py`, `app/audit_seed.json` | Append-only rows, SHA-256 chain, `verify()`, retention tombstones, deterministic startup fixture |
| Router | `app/router.py` | One row from `_finish` for every decision, `audit_id` on the response, privacy gate, concise filtering, detail memory |
| Undo | `app/tools/undo.py`, `app/adapters/lights.py` | Compensators for timers, lights, climate, and bookings, with the target resolved from the log |
| Detail lookup | `app/tools/details.py`, `app/memory.py` | `tell_me_more`, per-subject detail history, personalization off clears it |
| Privacy | `app/privacy.py`, `app/tools/privacy.py` | `privacy_get`, `privacy_set`, five settings, retention enforced on change |
| Contract | `app/models.py` | `detail_available`, plus `result_ref`, `compensation`, `compensator_of`, `scopes_used` on `HandlerResult` |
| Rules | `app/rules/rules.yaml` | Version `"3"`: integer enum for retention, rules for the four new tools |
| Console API | `app/main.py` | `/api/audit`, `/api/audit/verify`, audit counts and seed marker on `/health` |
| CLI | `app/cli.py` | `audit verify` and `audit list` against a running server |
| Tests | `tests/test_audit.py`, `test_undo.py`, `test_privacy.py`, `test_concise.py`, updated HTTP and CLI suites | 54 Day 3 tests; 130 in the suite at the time of writing |

### Tools after Day 3

| Tool | Risk | Scope | Notes |
|---|---|---|---|
| `timer_set` | low | `home:timers:write` | Unchanged, now records `result_ref` and its compensation |
| `lights_set` | low | `home:lights:write` | Compensation stores the previous on/off and brightness |
| `thermostat_set` | low | `home:climate:write` | Compensation stores the previous setpoint |
| `book_room` | medium | `booking:rooms:write` | External, preview and confirmation, compensation cancels the booking |
| `undo` | low | none declared | Resolves the target row, then checks the scopes that row recorded |
| `tell_me_more` | low | none declared | Reads the detail memory keyed by the token subject |
| `privacy_get` | low | `privacy:settings:write` | Read-only, reports the five settings |
| `privacy_set` | low | `privacy:settings:write` | Validates through the rules, audits the change, prunes on retention change |

`undo` and `tell_me_more` declare no scopes because the scope that matters is on
the original row, and the history is already keyed by the authenticated subject.
The handler still refuses an undo whose original row used a scope the caller does
not hold, before any adapter runs.

### Audit chain

```
row_hash(n) = SHA-256(canonical_json(row_fields) + row_hash(n-1))
```

`row_fields` is a fixed tuple: id, seq, ts, subject, tool, tool_version,
rules_version, service, scopes_used, params_hash, decision, status, error_code,
compensator_of, result_ref, compensation, tombstone. The first row links to 64
zeroes. Editing a row breaks its own hash; removing or reordering a row breaks
the link of the row that follows. `verify()` reports the first bad id and the
reason.

Every decision writes a row: executed, previewed, refused, and no_change,
including an unauthenticated refusal, which is recorded as `anonymous`. An
unknown tool is the one call that cannot be audited, because there is no
manifest to record a tool version or service from.

The row never stores the raw request. It stores the parameter hash, and for a
reversible action the minimal inverse state: a light snapshot, a thermostat
setpoint, a timer id, a booking id. That inverse is device state, which is what
makes undo work after a restart, and it is the only reason `compensation` is
allowed in the audit and not in the trace.

`audit_id` is now set on every response, including previews and refusals, and the
id is in the structured log line and in the trace.

### Seeded startup chain

`app/audit_seed.json` holds three rows for `demo-user` with fixed timestamps: an
executed timer, a refused thermostat, and a previewed booking. The hashes are
computed at boot from the fixture, so two boots rebuild the same chain and the
head is reproducible. Seeded rows carry no compensation, so they can never be the
target of "undo that".

`/health` reports `audit_rows` and `audit_seeded`. The lifespan writes one
`audit_seeded` log line. A redeploy therefore reads as an intentional reset
rather than as lost data.

### Undo

`undo` with no parameters reverses the newest executed row for the subject. The
newest executed row decides: if it is not reversible or was already reversed, the
answer is no, rather than silently reaching back to an older action. Reads report
`no_change` and are skipped, and so are previews and refusals.

The compensators are explicit:

| Target | Compensation | Spoken result |
|---|---|---|
| `timer_set` | `timer_id` | "Timer cancelled." |
| `lights_set` | `room`, `on`, `brightness` | "Kitchen lights back to 45 percent." or "Kitchen lights off again." |
| `thermostat_set` | `zone`, `target_c` | "Office thermostat back to 23 degrees." |
| `book_room` | `booking_id` | "Cancelled the Oak room booking on Saturday, October 24 at 9 AM." |

`lights_set` needed a new `LightAdapter.restore()`: `set(on=False)` keeps whatever
brightness the room remembers, which is not necessarily the value before the
action being undone, so undo writes the snapshot back verbatim.

The undo row records `compensator_of` and `result_ref` pointing at the original
audit id. Because the original row is never edited, "already undone" is derived
from the log itself: the set of ids that some undo row points at.

Cancelling a booking reaches a service outside the household, so undo checks the
`external` flag of the target tool and refuses with `PRIVACY_BLOCKED` when
third-party sharing is off.

### Concise mode and details

Concise mode is the default and is enforced by the server. A handler result with
a detail and concise mode on returns `detail: null` and
`detail_available: true`. The same text is stored in `DetailMemory`, keyed by
subject and audit id, and `tell_me_more` returns it as `speech`. With concise
mode off, `detail` is present and the flag stays false.

A preview keeps its detail. That text says nothing has happened yet, and it is
part of the confirmation rather than an extra, so withholding it would break the
confirmation contract and point the client at a memory entry that does not exist.

`personalization=false` clears the history and stops new entries, so
`tell_me_more` returns `NOT_FOUND` with a message that says personalization is
off. It also ignores a stored verbose preference, so turning personalization off
cannot be used to keep more text than the default.

### Privacy

| Setting | Default | Enforcement |
|---|---|---|
| `retention_days` | 30 | 0, 7, 30, or 90 from the rules; pruning runs in the same `privacy_set` call |
| `personalization` | on | Off clears detail memory and ignores the stored concise preference |
| `microphone_mode` | `wake_word` | Declared in the manifest; the server does not claim to control a microphone |
| `third_party_sharing` | on | Off refuses `external=true` tools with `PRIVACY_BLOCKED` before a preview is issued |
| `concise_mode` | on | On withholds `detail` and sets `detail_available` |

Retention tombstones keep the id, timestamp, tool, decision, and both hashes, and
blank the subject, service, versions, scopes, parameter hash, error code, and
compensation. A tombstone cannot be recomputed from its contents, so `verify()`
checks its link to the previous row and continues from its stored hash. That is
the honest tradeoff: the chain still proves sequence and that nothing was
inserted, but a tombstone no longer proves its own contents.

Changes are audited because they go through the router like any other tool. The
demo order matters: sharing defaults to on so step 6 can turn it off and show the
refusal.

### Decisions and gotchas

- Concise mode is a server decision, not a client hint. If the server merely
  labelled the text and always sent it, the preference would have no observable
  effect and `tell_me_more` would be pointless. The cost is that a client which
  ignores `detail_available` sees a shorter answer.
- `detail_available` exists because withholding `detail` without a flag would
  leave Alexa+ with no way to know a follow-up is possible.
- `privacy_get` uses `privacy:settings:write`, the only privacy grant in the
  token table. Splitting a read grant is a one-line change once a real
  authorization server exists.
- `read_only` moved into `ToolSpec` so the MCP `readOnlyHint` and the console
  manifest cannot disagree. `tell_me_more` and `privacy_get` set it, plus
  `idempotent`.
- A read reports decision `no_change`. It is a valid call that changes no state,
  which is the same meaning as a thermostat already at its setpoint, and it keeps
  reads out of the undo candidates without a second decision vocabulary.
- The audit row's `scopes_used` comes from the handler when it narrows them (undo
  reports the original row's scopes) and from the manifest otherwise.
- `compensated_ids()` is recomputed from the log on every call. At demo scale
  that is free; a table would index `compensator_of`.
- Retention runs on change, not on a timer. A demo setting is enforced
  immediately and visibly, and there is no background task to trust.
- Undo is not previewed. It only reverses an action the user already confirmed,
  and the alternative, a medium-risk `undo` that previews every light restore,
  would make "undo that" a two-turn conversation. The scope check and the audit
  link still hold. Recorded in `DECISIONS.md` with its revisit condition.
- The chain is global; `/api/audit` filters to the caller's subject and
  `/api/audit/verify` returns counts and the first bad id only. Verifying the
  chain is a global safety property; reading another subject's rows is not part
  of it.
- The audit log is unbounded in memory. Retention bounds it per subject on
  request; a production table would add an index and a hard cap.

### Verification

Commands run from `backend/`:

```bash
uv run pytest -q                 # 130 passed
uv run ruff check .              # clean
uv run ruff format --check .     # clean
```

The suite now also covers chain tampering, row removal, seeded determinism,
retention tombstones and link continuity, audit rows for previews and refusals,
the absence of raw parameters in a row, undo for all four reversible tools, undo
scope refusal, undo of an already cancelled booking, the privacy gate, per-user
privacy isolation, retention pruning, concise mode, `tell_me_more`, and a live
MCP undo whose row links back to the action it reversed.

Manual smoke test, against a local uvicorn on port 8000:

```text
GET /health
  -> rules_version 3, tools 8, audit_rows 3, audit_seeded true
lights_set {"room": "living_room", "brightness": 30}
  -> ok, detail null, detail_available true, audit_id a_000004
tell_me_more {}
  -> ok, "Living room lights are now on at 30 percent (previously off). Stored as lights_living_room."
undo {}
  -> ok, "Living room lights off again."
privacy_set {"third_party_sharing": false}
  -> ok, "Third-party sharing is off."
book_room {"date": "2026-10-24"}
  -> error PRIVACY_BLOCKED, "That action needs third-party sharing, which is off."
privacy_set {"third_party_sharing": true}
  -> ok
book_room {"date": "2026-10-24", "guests": 4}
  -> confirmation_required, preview, token
book_room {same params, confirmation_token}
  -> ok, "Booked the Oak room on Saturday, October 24 at 9 AM for 1 hour."
undo {}
  -> ok, "Cancelled the Oak room booking on Saturday, October 24 at 9 AM."
audit verify
  -> "audit chain ok: 12 rows, head 28b292e471db"
```

### Open items

- Register with Alexa+ and run the Local Inspector. Blocked on developer access.
- App Runner deployment, a real `ALEXA_TOKENS_JSON`, and a public URL.
- The booking conflict is still detected at execution, not preview. A preflight
  hook would turn a confirm-time failure into a preview-time refusal.
- The adapter timeout setting is still unused; every adapter is synchronous.
- No high-risk tool exists, so the certification gate is not implemented.
- No separate privacy read grant yet.
- Day 4: console Trace and Audit screens, voice proxy, YAML journeys, deploy, and
  demo rehearsal.

### Next step

Day 4: build the React console against `/api/trace`, `/api/audit`, and
`/api/audit/verify`, with a chain-status badge and an undo button that calls the
same tool. Then the ElevenLabs proxy and the YAML journeys, then App Runner.

## 2026-10-22: Day 4 setup, console scaffold

The paths below are the layout at the time. The console moved from `frontend/`
to the repository root later the same day; see the final entry.

### Delivered

- `FRONTEND.md`: console purpose, stack decisions, Amazon theme tokens with
  contrast ratios, runtime and auth diagrams, component tree, screen
  wireframes, API contract, the planned write path, accessibility, testing, and
  deployment.
- `frontend/` at the repository root: pnpm, React 19.2.7, TypeScript 5.9.3,
  Vite 7.3.7, and `@vitejs/plugin-react` 5.2.0, with a generated
  `pnpm-lock.yaml` ready to commit.
- Theme tokens in `src/styles/theme.css`: squid ink, orange, link blue, canvas,
  border, text, success, danger, and attention, plus a system font stack.
- Typed wire types and a read client for `/health`, `/api/whoami`,
  `/api/tools`, `/api/trace`, `/api/audit`, and `/api/audit/verify`.
- Shell with the ink header, orange active underline, status pill, token bar,
  identity row, and hash navigation between the four placeholder screens.
- Vite serves the app at `/console/` in dev and production, and proxies `/api`,
  `/health`, `/docs`, and `/openapi.json` to port 8000.

### Verification

```text
pnpm install --offline  -> 69 packages, lockfile written
pnpm typecheck          -> clean
pnpm build              -> dist 198.75 kB JS, 62.86 kB gzip
headless Chrome         -> shell renders, health pill "8 tools · 3 rows"
curl :5173/console/     -> 200
curl :5173/health       -> backend JSON through the proxy
curl :5173/api/trace    -> 401 without a token
VITE_CONSOLE_TOKEN      -> identity row "signed in as demo-user"
```

### Gotchas

- pnpm 12 no longer reads the `pnpm` field in `package.json`. Build approvals
  and overrides live in `frontend/pnpm-workspace.yaml`.
- pnpm 12 blocks install scripts by default. esbuild needs
  `allowBuilds: { esbuild: true }`.
- The npm registry was unreachable here. Four browser data packages were pinned
  to versions already in the local store, and the versions in `package.json` are
  exact. Remove the overrides after an online install.
- `@vitejs/plugin-react` 6 requires Vite 8, and that pair was not available
  offline. Vite 7.3.7 plus plugin 5.2.0 is the installed pair; upgrade both
  together.
- `base: "/console/"` applies in dev too, so the dev URL carries the same path
  and asset base as production. The proxy keeps the origin at 5173.

### Open items

- The four screens are placeholders.
- `POST /api/call/{tool}` is designed but not built, so the console cannot yet
  undo, toggle privacy, or run a journey.
- No static mount in FastAPI, no Dockerfile copy, no CI job, no browser test.

### Next step

Build the Trace screen against `/api/trace` with filters, pause, and the empty
state, then the Audit screen with the chain badge and the undo button.

## 2026-10-22: Day 4 backend, assistant, voice, console API, journeys

### Delivered

- `app/assistant/`: a deterministic parser for the demo phrases, a per-subject
  pending confirmation store, a service that resolves yes/no before parsing a new
  request, and a typed `AssistantReply` envelope. The parser returns parameters
  only; `Router.execute` still validates, authorizes, confirms, audits, and
  traces every action.
- `app/voice/`: an async ElevenLabs client with a bounded text-keyed LRU cache,
  typed `VoiceUnavailable` reasons, and no upstream error body in the exception.
  The key stays server-side and the voice id is fixed by configuration.
- `app/api/`: `GET /api/config`, `GET /api/state`, `GET` and `PUT/PATCH
  /api/privacy`, `POST /api/call/{tool}`, the five assistant routes, the two
  voice routes, and the two journey routes. Every write goes through
  `Router.execute`; the state and config reads do not write audit rows.
- `app/journeys/`: schema, YAML loader with `extra="forbid"`, an isolated runner,
  and four fixtures: timer and details, lights plus a refused thermostat plus
  undo, booking preview and confirm, and the privacy gate.
- `main.py` includes the new routers before the `/` MCP mount, exposes the
  assistant and voice on `app.state`, and keeps the API builders dependency
  explicit.
- `.env.example` documents the optional `ALEXA_ELEVENLABS_*` settings and
  `ALEXA_VOICE_MAX_CHARS`.
- Docs updated: `README.md`, `backend/README.md`, `TECHNICAL.md`, `FRONTEND.md`,
  and `AGENTS.md`.

### Verification

```text
uv run ruff check .              -> All checks passed
uv run ruff format --check .     -> 72 files already formatted
uv run pytest -q                 -> 188 passed
```

Manual smoke test against a local app state:

```text
"set a ten minute timer"                 -> ok, 600 seconds, audit executed
"dim the living room lights to 30%"      -> ok, brightness 30, audit executed
"set the thermostat to 35"               -> OUT_OF_BOUNDS, audit refused
"book the cedar room tomorrow at 1pm"    -> preview, audit previewed
"yes"                                    -> booked, audit executed
"undo that"                              -> cancelled, audit executed
audit chain                              -> ok, 9 rows
```

Journey results:

```text
booking           passed  audit_ok  rows 6
lights-and-rules  passed  audit_ok  rows 6
privacy           passed  audit_ok  rows 6
timer             passed  audit_ok  rows 5
```

### Decisions

- The demo brain is a parser, not a model. Alexa+ owns intent in production. A
  local stand-in keeps the demo deterministic and means the journeys can assert
  exact tool choices.
- One pending confirmation per subject. A new request while a preview is open
  repeats the question instead of replacing it or guessing. This makes "yes" and
  "no" unambiguous.
- A clarification writes no audit row because no tool ran. The preview, the
  execution, and the refusal each still write exactly one row from
  `Router._finish`.
- Confirming from the console button and saying "yes" call the same service
  method. Neither can bypass the token check or the scope check in the router.
- Journeys use a fresh `AppState`. The live audit chain is untouched, which is
  why the console can offer a run button without a confirmation.
- Voice is optional and outside the decision path. `POST /api/voice/speak`
  refuses with `PRIVACY_BLOCKED` when third-party sharing is off, because the
  text leaves the household for ElevenLabs.
- `POST /api/call/{tool}` returns the same `ToolResponse` as MCP, including
  business errors with HTTP 200. An unknown tool is a real 404.

### Gotchas

- The parser defaults an unnamed light room and thermostat zone to the living
  room so "turn on the lights" and "set the thermostat to 35" reach the rule
  engine. The default is a demo convenience, not a rule.
- A bare clock hour from 1 to 6 is read as afternoon. "book at two" is 14:00.
  This is documented in `_assume_meridiem`.
- Pending confirmations are in memory. A restart drops them and the token, which
  is safe: the user is asked again.
- `mcp` depends on `httpx2`, so the voice client uses the same runtime client
  rather than adding a second HTTP dependency.
- The voice cache is keyed by exact text and never by subject. It is bounded and
  cleared on restart.

### Open items

- The four console screens and the assistant bar are next.
- `src/api/types.ts` needs the new assistant, state, journey, and voice
  types before the screens can call them.
- Set `ALEXA_ELEVENLABS_API_KEY` for the demo voice, or rely on browser speech.
- No per-token rate limit on voice yet. The bearer token is the control for the
  demo.
- App Runner deployment and demo rehearsal are still pending.

### Next step

Build the Trace and Audit screens against the existing read endpoints, then add
the assistant bar against `/api/assistant/turn` and the privacy and journey
screens against the new routes.

## 2026-10-22: Console moved to the repository root

### Delivered

- `index.html`, `package.json`, `pnpm-lock.yaml`, `pnpm-workspace.yaml`,
  `tsconfig.json`, `vite.config.ts`, `src/`, and `.env.example` now sit at the
  repository root. The `frontend/` directory is gone.
- `vite.config.ts` ignores `backend/`, `docs/`, `scripts/`, and `.git/` in the
  watcher, because Vite's root is now the whole checkout.
- Root `.gitignore` covers `dist/`, `node_modules/`, and `*.tsbuildinfo`.
- `docs/FRONTEND.md` uses Mermaid for the runtime, read, write, and component
  diagrams.

### Verification

```text
pnpm install --offline  -> lockfile reused, 69 packages
pnpm typecheck          -> clean
pnpm build              -> dist 198.74 kB JS, 62.84 kB gzip
curl :5173/console/     -> 200
curl :5173/health       -> backend JSON through the proxy
curl :5173/api/trace    -> 401 without a token
headless Chrome         -> shell renders, health pill "8 tools · 3 rows"
```

### Gotchas

- Running Vite from the repository root means the dev server sees the Python
  tree, so the watcher ignores it explicitly. Without that, a backend edit can
  trigger a reload.
- The image build still uses `backend/` as its context. Serving `dist/` from the
  image needs the build to move to the repository root and the Dockerfile paths
  to change; that is still open.

### Next step

Trace and Audit screens, then the assistant bar and the privacy and journey
screens.

## 2026-10-22: Google accounts, persisted sessions, and Render Postgres

### Delivered

- `backend/app/accounts/` now owns browser identity and persistence:
  `google.py` (authorization code plus PKCE, injectable transport),
  `store.py` (SQLAlchemy Core tables and queries), `service.py` (policy and the
  one-time handoff), `verifier.py` (session bearer to `Principal`), and
  `models.py` (frozen records).
- Four tables: `auth_users`, `auth_sessions`, `auth_oauth_states`, and
  `auth_exchange_codes`. Sessions and exchange codes store hashes only.
  `auth_sessions` carries `last_seen_at` and `revoked_at`; exchange codes are
  bound to a pending session.
- Google flow: `/api/auth/google/start` (also `/api/auth/login/google`),
  `/api/auth/callback/google`, `POST /api/auth/exchange`, `GET` and `PATCH
  /api/auth/me`, `POST /api/auth/logout`, and a local-only
  `POST /api/auth/dev-login`.
- `app/auth.py` resolves a static token or a session to the same `Principal`.
  Session claims carry the account id, session id, email, display name, and
  provider; `subject` remains `user_<uuid>`, so audit and adapters do not branch
  on the auth method.
- `backend/app/api/auth.py` keeps the auth routes synchronous, so the blocking
  SQLAlchemy driver runs in FastAPI's threadpool. The MCP and REST verifiers
  hop into the threadpool only for the session lookup.
- CORS is explicit for Vercel and Vite: origins
  `https://alexa.vercel.app` and `http://localhost:5173`, no credentials,
  `Authorization` and `Content-Type` allowed, all methods allowed.
- `DATABASE_URL` accepts Render's `postgres://` and `postgresql://` forms and
  maps them to `psycopg`. `sqlalchemy` and `psycopg[binary]` are in
  `pyproject.toml` and `requirements.txt`; `create_all` runs at startup.
- `backend/.env.example` documents Google, database, frontend, session, exchange
  code, dev login, and CORS settings. The account payload carries the demo
  notice: accounts persist, the simulated house resets after inactivity or a
  redeploy.

### Verification

```text
uv run pytest -q      -> 207 passed
uv run ruff check .   -> clean
uv run pytest -q tests/test_google_auth.py -> 18 passed
```

The auth suite uses a mocked Google transport, so it exercises the real state,
PKCE, callback, exchange, session, audit subject, CORS, and persistence paths
without network access. It covers identity by Google `sub`, email refresh,
unverified email refusal, state replay, exchange replay, logout, expiry, the
local-only dev login, and sessions surviving a new app against the same database.

### Gotchas

- A developer `.env` with a real `ALEXA_ELEVENLABS_API_KEY` made the voice tests
  expect a provider. `tests/conftest.py` now pins the key to `None` and pins the
  CORS origins, so local secrets cannot change the suite.
- Render free instances spin down. Accounts survive because they are in
  Postgres, but the in-memory house and audit chain reset. Use a paid instance or
  a keep-alive ping on demo day.
- The Google Cloud client needs both callback URIs registered:
  `http://localhost:8000/api/auth/callback/google` and
  `https://alexa-api.onrender.com/api/auth/callback/google`.
- Vercel preview URLs are different origins. Add one temporarily to
  `ALEXA_CORS_ORIGINS`, or use the local dev login while working on a preview.

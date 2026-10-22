# Alexa: Technical Design

## 1. Architecture

```
Customer voice
     │
     ▼
Alexa+ (LLM: intent interpretation, response generation, UI rendering)
     │  MCP over Streamable HTTP, spec 2025-11-25
     ▼
Alexa MCP server (FastAPI, Python)                 ← Render (API + MCP)
     ├── Auth & scope check
     ├── Tool router
     ├── Rules engine (deterministic validation and execution)
     ├── Confirmation service (single-use tokens)
     ├── Audit log (append-only, hash-chained)
     ├── Privacy policy enforcer
     └── Device / service adapters (simulated)
     │
     ▼
SQLite (dev) / Postgres (Render) for accounts and sessions
(the house, audit, trace, and confirmations stay in process memory; see D12, D29, and D37)
     ▲
     │  REST (JSON)
React console (Vite + TypeScript): trace viewer, audit browser, privacy panel, journey runner
```

**Division of responsibility.** The model never receives device credentials and never calls adapters directly. It produces a tool call with parameters. The router validates the call against the tool's schema, then the rules engine validates the values against declared bounds, and only then does an adapter run.

**Hosting boundary.** Render hosts one API container for the REST surface, the MCP endpoint, and Google OAuth callbacks. Vercel serves the static console. Accounts and sessions use Render Postgres; every other piece of state stays in the container. App Runner remains an alternative host for the MCP container because the contract is only port 8000, TLS termination, and forwarded headers, but it is not the planned path.

## 2. Latency budget

Alexa+ requires a round trip under 500 ms for MCP calls. Budget:

| Step | Target |
|---|---|
| TLS + routing | 30 ms |
| Auth and scope check | 10 ms |
| Schema and rules validation | 5 ms |
| Adapter call (simulated: 0 ms; real: capped at 300 ms with timeout) | ≤ 300 ms |
| Audit write (in-process append, before the response) | < 1 ms on path |
| Serialization | 10 ms |

Rules: no LLM call anywhere in the server's request path. Keep the process warm (no cold start on the request path). Set adapter timeouts so a slow upstream returns a structured `TIMEOUT` error, not a hang.

## 3. Tool contract

Every tool is declared in a manifest with these fields:

```python
ToolSpec(
    name="thermostat_set",
    description="Set the target temperature for one thermostat zone. Use when the user asks to change heating or cooling.",
    scopes=["home:climate:write"],
    risk="low",            # low | medium | high
    reversible=True,
    compensator="thermostat_restore",   # tool that undoes this one
    params_schema=ThermostatSetParams.model_json_schema(),
    bounds={"target_c": (16, 28)},
    confirmation_template="Set {zone} to {target_c} °C",
)
```

Descriptions are part of the product. Alexa+ uses them to choose tools, so each description states when to use the tool and when not to.

### Risk tiers

| Tier | Examples | Behavior |
|---|---|---|
| low | timers, alarms, lights, media | executes immediately; logged |
| medium | thermostat changes outside a schedule, booking a reversible reservation | returns preview; confirmation token required |
| high | payments, deletions, unlocking doors, changing security settings | returns preview; confirmation token required; server refuses unless the tool is certified (see §8) |

### Confirmation flow

1. Client calls a medium or high tool without a token.
2. Server returns `status: "confirmation_required"`, a preview object (`service`, `tool`, `params`, `effect`, `irreversible: bool`), and a token.
3. Token is valid for 300 seconds and is bound to the exact parameter hash.
4. Client calls the same tool with the token. The server recomputes the hash. If anything changed, the token is rejected.
5. Token is consumed on use. Replay fails with `TOKEN_CONSUMED`.

### Response shape

```json
{
  "status": "ok | confirmation_required | error",
  "speech": "Timer set for ten minutes.",
  "detail": null,
  "detail_available": true,
  "trace": [{"tool": "timer_set", "service": "timers", "ok": true, "ms": 4}],
  "audit_id": "a_000004",
  "error": null
}
```

`speech` is always present and short. This is the concise mode default. With
concise mode on, `detail` is null and `detail_available` says a longer
explanation exists; `tell_me_more` returns it. With concise mode off, `detail`
carries that text and `detail_available` is false. `audit_id` points at the row
for this decision, including a preview and a refusal.

## 4. Rules engine

The rules engine is a pure function of (tool spec, current state, parameters) → (decision, effect). It contains no model calls and no I/O except the adapter invocation after a decision.

Responsibilities:

- Bounds checks against the spec (ranges, enums, required fields).
- Conflict checks (for example, two alarms at the same minute, or a thermostat setpoint already at the requested value, which returns `NO_CHANGE` rather than an error).
- Policy checks (scope, privacy toggles, certification status).
- Compensator lookup for reversible actions.

Rules are data, not code, where possible (YAML files loaded at startup, versioned, and included in every audit entry as `rules_version`). This lets reviewers see exactly which rule approved an action.

## 5. Audit log

Append-only table with a hash chain:

| Column | Type | Notes |
|---|---|---|
| id | text | `a_` plus a zero-padded sequence, stable across retention |
| seq | int | position in the chain |
| ts | timestamptz | server time |
| subject | text | pseudonymous household id |
| tool | text | tool name |
| tool_version | text | from manifest |
| rules_version | text | rule set that approved the call |
| service | text | adapter group |
| scopes_used | text[] | scopes the call relied on |
| params_hash | text | SHA-256 of canonical JSON params |
| decision | text | executed, previewed, refused, no_change |
| status | text | ok, confirmation_required, error |
| error_code | text | taxonomy code when status is error |
| result_ref | text | adapter reference such as `timer_7f3a` |
| compensation | json | minimal inverse state for undo, never the request |
| compensator_of | text | audit id of the action an undo reversed |
| prev_hash | text | hash of previous row |
| row_hash | text | SHA-256 of the row fields plus prev_hash |

Raw parameters are never stored. The parameter hash binds the row to the request
without keeping what the user said, which is why `D13` holds for the audit too.

**Verification.** A CLI command (`alexa audit verify`) recomputes the chain and
reports the first broken link. The console shows a green or red chain status.

**Retention.** Changing `retention_days` replaces older rows for that subject
with tombstones (id, ts, tool, decision, both hashes) so the chain stays
verifiable. A scheduled sweep would replace the on-change call in production.

## 6. Rollback

- Each reversible tool declares a `compensator`. Undo calls the compensator with the pre-state stored in the original audit row.
- "Undo that" resolves to the most recent executed action. The response names what was undone, and the new row links back with `compensator_of`.
- Undo inherits the original action's authorization: it is refused when the caller lacks the scopes the original call used. It is not previewed again, because it only reverses an action the user already confirmed. Cancelling a booking is still gated by `third_party_sharing`.
- Irreversible tools are flagged `reversible=False`. Their preview states this clearly, and the confirmation text includes "This cannot be undone." Undo cannot itself be undone.

## 7. Privacy model

Stored per user, enforced server-side:

```python
class PrivacySettings(BaseModel):
    retention_days: Literal[0, 7, 30, 90] = 30   # 0 = keep only tombstones
    personalization: bool = True
    microphone_mode: Literal["wake_word", "continuous"] = "wake_word"  # declared, enforced by client
    third_party_sharing: bool = True
    concise_mode: bool = True
```

- `personalization=False`: the server ignores the stored concise preference and keeps no per-action detail history.
- `third_party_sharing=False`: tools with `external=True` in their manifest are refused with `PRIVACY_BLOCKED`. It defaults to on so a user can turn it off and see the refusal.
- `microphone_mode` is declared in the server's privacy manifest so Alexa+ can surface it. The server does not control the microphone.
- `concise_mode=True`: responses omit `detail` and set `detail_available`.

Every privacy change is itself an audit entry, and a retention change is enforced
by the same call.

## 8. Developer standard

Published as `STANDARD.md` in the repo. Four parts:

**Permission scopes.** Named as `domain:resource:action` (for example, `home:lights:write`). Scopes are granted per user, and each tool declares the minimum it needs. Tokens never carry broad scopes by default.

**Error taxonomy.** A small, stable set of codes so every developer's tool fails the same way:

| Code | Meaning | Alexa+ follow-up |
|---|---|---|
| `INVALID_PARAM` | a value failed validation | ask for the specific field |
| `OUT_OF_BOUNDS` | a value is outside declared bounds | state the allowed range |
| `NOT_FOUND` | a referenced item does not exist | ask which item |
| `AUTH_REQUIRED` | scope missing or token expired | prompt re-link |
| `PRIVACY_BLOCKED` | a privacy setting forbids the action | explain the setting |
| `CONFIRMATION_REQUIRED` | preview needs confirmation | present preview |
| `TOKEN_CONSUMED` / `TOKEN_EXPIRED` | confirmation token unusable | restart the action |
| `UPSTREAM_TIMEOUT` | adapter exceeded its budget | offer to retry |
| `UPSTREAM_ERROR` | adapter failed | say so, do not guess |

**Simulated user journeys.** A journey is a YAML file: a sequence of utterances (or tool calls), expected tool choices, expected status codes, and expected audit entries. The runner executes journeys against a local server and fails on any mismatch. Journeys include happy paths, ambiguous requests, out-of-bounds requests, replayed tokens, and undo flows.

**Certification for high-risk actions.** A tool with `risk="high"` must pass a checklist before the server will enable it in production:

1. Preview names the service and tool exactly.
2. Confirmation token binds to the parameter hash and expires.
3. Refusal path tested with a bad token and a changed parameter.
4. Audit entry written for execution and for refusal.
5. Irreversible status stated in the preview.
6. A journey covering the full flow passes in CI.

The certification runner produces a report; the server reads a `certified: true` flag from the manifest only when the report is present and current.

## 9. Frontend console

React + TypeScript at the repository root (`src/`, `index.html`,
`vite.config.ts`), built by Vite, installed with pnpm, served by the backend at
`/console`. The scaffold is in place; the screens are next. Four screens:

- **Trace:** live list of tool calls with service, decision, latency, and audit id.
- **Audit:** searchable log with chain status and an "undo" action where a compensator exists.
- **Privacy:** the toggles, each with a one-line explanation of its effect.
- **Journeys:** run the simulated journeys and see pass or fail per step.

It reads `/health`, `/api/config`, `/api/whoami`, `/api/tools`, `/api/trace`,
`/api/audit`, `/api/audit/verify`, and `/api/state`. The account page uses
`/api/auth/me`, `/api/auth/exchange`, and `/api/auth/logout`. Writes (undo,
privacy toggles) go through one `POST /api/call/{tool}` endpoint that calls
`Router.execute`. The assistant bar uses `/api/assistant/turn` and the session
routes; the voice button uses `/api/voice/speak` and falls back to browser
speech. Journeys are listed from `/api/journeys` and run through
`/api/journeys/{name}/run` against an isolated app state. The console never
duplicates a rule, and it renders decisions rather than making them. It is an
operator and developer tool, not the customer experience: customer-facing
confirmations are rendered by Alexa+.

### Assistant and voice

The backend ships a deterministic parser for the example phrases. It is a stand-in
for Alexa+'s intent layer, not a replacement: it returns parameters to
`Router.execute`, which validates, authorizes, confirms, audits, and traces them
exactly as it does for an MCP call. A preview is held per subject so the next
"yes" completes the same single-use token. A clarification writes no audit row
because no tool ran.

The ElevenLabs proxy is optional and never in the decision path. It speaks the
`speech` string the server already composed, keeps the API key server-side,
caps the text, caches repeated phrases, and refuses with `PRIVACY_BLOCKED` when
third-party sharing is off. A missing key returns a structured 503 so the
console can use browser speech without changing the transcript.

`FRONTEND.md` owns the design: theme tokens and contrast, diagrams, screen
specs, the API contract, accessibility, testing, and the build plan.

## 10. Accounts, Google sign-in, and persistence

The MCP endpoint and the browser console authenticate differently but resolve to
the same `Principal`:

- **Static bearer tokens** from `ALEXA_TOKENS_JSON` remain the Alexa+, inspector,
  and CLI path. They are capabilities with a subject, a scope set, and an
  optional expiry. A public deployment replaces the shipped `dev-token`.
- **Google sessions** are opaque `sess_...` bearer tokens created after the
  browser OAuth flow. They carry the account profile and the same scopes,
  and `Router.execute` cannot tell the two kinds apart.

### Identity and tables

Google identity is `(provider, provider_account_id)`, where the account id is
Google's stable `sub`. Email is refreshed on every login but is not the key: an
address change must not transfer a household. The audit subject is
`user_<uuid>`, generated at first login and never derived from an email or a
Google id.

| Table | Columns | Purpose |
|---|---|---|
| `auth_users` | `id`, `subject`, `email`, `display_name`, `email_verified`, `provider`, `provider_account_id`, `created_at`, `last_login_at` | One row per Google account. Unique on `(provider, provider_account_id)` and on `subject`. |
| `auth_sessions` | `id`, `user_id`, `token_hash`, `created_at`, `expires_at`, `last_seen_at`, `revoked_at` | Browser sessions. Only the SHA-256 hash of the bearer is stored. `last_seen_at` is refreshed at most once a minute. |
| `auth_oauth_states` | `state_hash`, `provider`, `code_verifier`, `redirect_after`, `created_at`, `expires_at`, `consumed_at` | Short-lived OAuth state and PKCE verifier. The row is consumed before Google is called. |
| `auth_exchange_codes` | `code_hash`, `session_id`, `created_at`, `expires_at`, `used_at` | One-time handoff from the callback to the SPA. Bound to the pending session. |

The state and code columns hold hashes, not the raw values. The raw session
token exists only in the browser that received it and in the `Authorization`
header; a database dump does not yield a usable credential.

### Flow

1. The browser navigates to `GET /api/auth/google/start?redirect_after=/console`.
2. The server creates a state, a PKCE verifier, and a challenge, stores the
   state and verifier, and redirects to Google with scopes
   `openid email profile`.
3. Google returns to `GET /api/auth/callback/google`. The server consumes the
   state before the network call, exchanges the code, and reads the userinfo
   endpoint over TLS. An unverified email is refused.
4. The server upserts the account, creates a session with a throwaway token, and
   creates a single-use exchange code bound to that session.
5. The browser lands on `/#/auth/callback?code=...&next=...`. It removes the
   code from the hash with `history.replaceState` and posts it to
   `POST /api/auth/exchange`.
6. The exchange consumes the code, rotates the session token, and returns the
   bearer once. The code is never a bearer and cannot be replayed. Codes expire
   after 60 seconds; sessions after seven days by default.

Other routes: `GET /api/auth/me` returns the account, `PATCH /api/auth/me`
changes the display name, `POST /api/auth/logout` revokes the session, and
`POST /api/auth/dev-login` is a local-only shortcut gated by
`ALEXA_AUTH_DEV_LOGIN` and a local `ALEXA_PUBLIC_URL`.

### CORS, URLs, and environment

The production browser origin is Vercel and the API origin is Render. CORS is
explicit and credential-free because auth is a bearer header, not a cookie:

```python
allow_origins = ["https://alexa.vercel.app", "http://localhost:5173"]
allow_credentials = False
allow_headers = ["Authorization", "Content-Type"]
allow_methods = ["*"]
```

| Variable | Local | Production |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./data/alexa.db` | Render Postgres connection string (`postgres://` or `postgresql://`) |
| `ALEXA_GOOGLE_CLIENT_ID` | Google OAuth client id | Same client, production redirect URI registered |
| `ALEXA_GOOGLE_CLIENT_SECRET` | secret, never committed | Render secret |
| `ALEXA_OAUTH_REDIRECT_URI` | `http://localhost:8000/api/auth/callback/google` | `https://alexa-api.onrender.com/api/auth/callback/google` |
| `ALEXA_FRONTEND_URL` | `http://localhost:5173` | `https://alexa.vercel.app` |
| `ALEXA_SESSION_TTL_SECONDS` | `604800` | `604800` |
| `ALEXA_EXCHANGE_CODE_TTL_SECONDS` | `60` | `60` |
| `ALEXA_AUTH_DEV_LOGIN` | `true` or `false` | leave `false`; the service also requires a local public URL |

`ALEXA_PUBLIC_URL` remains the API origin. When `ALEXA_OAUTH_REDIRECT_URI` is
unset, the callback derives from it.

### Persistence boundary

Accounts and sessions survive a Render redeploy. The simulated house, trace,
audit chain, confirmation tokens, and journey results do not: they are in
process memory by design (D12 and D29). The account page must show the exact
`house_notice` sentence: `Your house resets after inactivity or a redeploy. Your
account and sign-in stay.`

Tables are created with SQLAlchemy `create_all` at startup. A small
compatibility step adds `last_seen_at` to an older session table and recreates
the short-lived exchange-code table when its old `user_id` column is present, so
the first deployed database keeps working. Alembic is still the next step before
the schema changes again. The store uses SQLAlchemy Core and `psycopg[binary]`
on Postgres; the auth routes are plain `def` handlers so FastAPI runs their
blocking driver in a threadpool. The MCP and REST verifiers hop into the same
threadpool only for the session lookup.

### Render checklist

- Create a Render Postgres instance and copy its internal `DATABASE_URL`.
- Set the Google client id and secret, `ALEXA_OAUTH_REDIRECT_URI`,
  `ALEXA_FRONTEND_URL`, `ALEXA_PUBLIC_URL`, and `ALEXA_CORS_ORIGINS`.
- Add the exact production callback URI to the Google Cloud OAuth client.
- Use a paid instance or a keep-alive ping before a walkthrough: a free instance spins
  down, which clears the in-memory house and audit chain. Accounts and sessions
  still survive because they are in Postgres.

## 11. Repository layout

```
alexa/
├── README.md
├── index.html                # Vite entry
├── package.json
├── pnpm-workspace.yaml       # pnpm settings: build approvals, overrides
├── tsconfig.json
├── vite.config.ts
├── src/                      # screens, typed API client, theme tokens
├── docs/
│   ├── FRONTEND.md
│   ├── TECHNICAL.md
│   └── ...
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI app, mounts /mcp and the /api routers
│   │   ├── mcp_server.py     # MCP tool registration (Streamable HTTP)
│   │   ├── router.py         # schema validation, scope check
│   │   ├── api/              # console, assistant, voice, and journey REST routes
│   │   ├── assistant/        # deterministic parser, pending confirmation, replies
│   │   ├── voice/            # ElevenLabs proxy and browser fallback contract
│   │   ├── journeys/         # schema, loader, isolated runner, fixtures
│   │   ├── accounts/         # Google OAuth, account store, session verifier
│   │   ├── rules/            # engine.py, rules/*.yaml
│   │   ├── confirm.py        # tokens
│   │   ├── audit.py          # hash-chained log
│   │   ├── privacy.py
│   │   ├── adapters/         # timers.py, lights.py, climate.py, media.py, booking.py (simulated)
│   │   └── tools/            # ToolSpec manifests
│   ├── tests/                # unit, HTTP, auth, voice, journey, live MCP tests
│   └── requirements.txt
└── scripts/
    └── check_leaks.py
```

## 12. Build plan (hackathon)

| Block | Scope | Done when |
|---|---|---|
| 1 | MCP server, timers and lights, Streamable HTTP, 401 on unauthenticated calls | Local Inspector lists tools and calls them |
| 2 | Rules engine, bounds, error taxonomy | Out-of-bounds thermostat returns `OUT_OF_BOUNDS` |
| 3 | Confirmation tokens, booking tool (simulated) | Preview, confirm, replay refused |
| 4 | Audit log with hash chain, undo for lights and timers | `audit verify` passes; undo logged and linked |
| 5 | Privacy toggles enforced | Third-party tool refused when toggled off |
| 6 | Journeys and runner, console screens | Four journeys pass through the API and CLI; console screens render them |
| 7 | Polish, `STANDARD.md`, certification report for booking tool | Walkthrough script runs end to end |

Cut order if time runs short: certification runner first (keep the checklist as a document), then the console's journey screen, then the booking tool. Never cut the rules engine, confirmations, or the audit log, because those are the principles the project is judged on.

## 13. Risks

- **Latency on Alexa+ round trips.** Mitigation: no LLM in the request path, warm process, adapter timeouts. Measure with the Local Inspector before a walkthrough.
- **Alexa+ registration details.** The public docs describe the add-on flow through the `alexa-ai` CLI. Confirm the exact registration steps for a self-hosted server in the track resources before building the deployment.
- **Confirmation rendering is Alexa+'s.** Our preview object must be complete enough for Alexa+ to render. Validate the shape against the Alexa+ UX guidelines.
- **Scope creep.** Mitigation: the cut order above.
- **Device realism.** Adapters are simulated. Say so in a walkthrough and show the adapter boundary as the integration point.ss
# Decisions

Every entry records the choice, why it was made, and the condition that would
reverse it. Add a new entry instead of rewriting an old one. If a decision is
replaced, mark it superseded and link the new ID.

## D1. The server is deterministic; no model runs in the request path

**Decision:** Alexa+ interprets the user and chooses a tool. This server
validates the parameters, applies the rules, and performs the action. It never
calls a language model to decide what to do or what to say.

**Why:** A timer for ten minutes must be ten minutes every time. A model in the
path adds latency, cost, and a new failure mode without improving a bounded
action. Speech is composed from the validated result, so the same input produces
the same sentence.

**Revisit if:** a tool genuinely needs open-ended judgment, for example choosing
a restaurant from a free-form request. That tool should be a separate, clearly
marked service, not a change to this path.

## D2. Python, FastAPI, and the official MCP SDK

**Decision:** Use Python 3.13, FastAPI, Pydantic, and `mcp` 2.3.0.

**Why:** The MCP SDK ships the Streamable HTTP transport, bearer middleware, and
the 2025-11-25 protocol surface. Reimplementing those would create protocol
drift and hide security bugs in code that has no product value.

**Revisit if:** the SDK drops a capability we need, or a supported language has
a materially better MCP server implementation. The router and rules are the
parts worth porting; the transport is not.

## D3. Streamable HTTP at `/mcp`, mounted at the application root

**Decision:** The MCP endpoint is `POST/GET/DELETE /mcp`. The MCP app is mounted
at `/` and owns that path internally.

**Why:** Mounting the MCP app at `/mcp` with an inner route of `/` produced a
307 redirect under the Starlette version in use, which broke the streamable
client before the first request. Mounting at the root keeps the path stable and
still lets `/health`, `/api`, `/docs`, and the metadata route win because the
mount is registered last.

**Revisit if:** the SDK exposes a stable mount helper, or the redirect behavior
is fixed and a nested mount becomes simpler.

## D4. Resource server with a static token table for the demo

**Decision:** The server verifies bearer tokens from `ALEXA_TOKENS_JSON` and
publishes RFC 9728 protected-resource metadata. It does not run an OAuth 2.1
authorization server.

**Why:** The hackathon needs a working authenticated endpoint on day one. A
static table keeps the demo to one environment variable and exercises the same
401 challenge Alexa+ will see. The limitation is documented rather than hidden.

**Revisit if:** Alexa+ registration requires an authorization-server metadata
document or a full authorization code flow. At that point, add a real
authorization server and keep the resource server unchanged.

## D5. Re-verify the bearer token on every tool call

**Decision:** Each MCP tool call reads the current request headers and verifies
the token again, even though the transport middleware already rejected a bad
token at connect time.

**Why:** Tool handlers can run in a session task, so a context variable may carry
the identity from the `initialize` call rather than the call being served. A
revoked or expired token must stop working inside an open session.

**Revisit if:** the SDK provides a request-scoped principal that is guaranteed to
match the current tool call. Even then, keep the test that proves revocation
takes effect mid-session.

## D6. Speech is composed on the server

**Decision:** Every tool returns a short `speech` sentence written by the
handler. `detail` carries the longer explanation. The model does not paraphrase
the result.

**Why:** The spoken result is part of the product contract, not a creative act.
Server-composed speech is testable, repeatable, and cannot claim success when the
action failed. It also avoids a second model call, which keeps the turn well
under a second.

**Revisit if:** the product needs natural variation for a demo persona. Variation
should be a small deterministic template choice, not a generative rewrite.

## D7. Business errors are structured tool results

**Decision:** Invalid parameters, out-of-bounds values, auth failures, and
upstream failures return `status: "error"` inside a normal tool result. They do
not raise MCP protocol errors.

**Why:** Alexa+ needs to read `error.code`, `error.field`, `error.allowed`, and
`error.follow_up` to ask a specific question. A protocol error loses that
structure and often reads as a transport failure.

**Revisit if:** the MCP specification adds a structured error channel that
clients actually surface. Keep the same payload either way.

## D8. One `Router.execute` path for MCP, REST, and tests

**Decision:** MCP wrappers, console-facing REST handlers, and tests all call the
same router. The router owns auth, scope, validation, confirmation, execution,
trace, and logging.

**Why:** Two paths would drift, and the security checks would be the first thing
to diverge. The MCP wrapper contains no business logic; it only resolves the
caller and passes parameters.

**Revisit if:** a surface needs a genuinely different contract. Add a thin
adapter around the router, not a second decision path.

## D9. Rules are versioned YAML; identity and risk stay in code

**Decision:** `app/rules/rules.yaml` owns types, bounds, enums, formats, labels,
and defaults. `ToolSpec` owns the name, title, service, scopes, risk, and
compensator.

**Why:** A reviewer should be able to read the accepted values without reading
Python. A product owner can change a bound as a reviewed data change. The
startup drift check fails if a tool and its rules disagree.

**Revisit if:** the rules need behavior that cannot be expressed as data, such as
a cross-field dependency. Put that behavior in the handler and keep the
single-field constraints in YAML.

## D10. Confirmation tokens are single-use, hash-bound, and short-lived

**Decision:** A medium or high risk action returns a preview and a token bound to
the subject, tool, and canonical parameter hash. The token expires after 300
seconds, works once, and is consumed only after the adapter succeeds.

**Why:** The token authorizes exactly the action the user saw. Changing the date
or the room invalidates it. A failed execution leaves it usable for a retry, so
a transient conflict does not force the user through the preview again.

**Revisit if:** pending confirmations must survive a restart or span multiple
server instances. Then move the table to a shared store with the same
subject/tool/hash binding.

## D11. Confirmation is a second tool call, not MCP elicitation

**Decision:** The preview asks Alexa+ to call the same tool again with the token.
The server does not park an open `tools/call` stream and wait for an
`elicitation/create` answer.

**Why:** A parked call couples the confirmation lifetime to a transport session
and an idle proxy. The token flow is stateless between calls, survives a client
reconnect, and is naturally replay-safe. Elicitation is useful for collecting
missing arguments, not for authorizing a priced action with a durable token.

**Revisit if:** Alexa+ requires elicitation for confirmations, or a tool needs a
multi-field question that cannot be represented as a tool call. Do not replace
the token; add elicitation for the question and keep the token for execution.

## D12. Adapters and state are in memory for the demo

**Decision:** Timers, lights, climate, bookings, confirmation tokens, and the
trace live in one `AppState` per process. A restart clears them.

**Why:** Real integrations are out of scope and would slow the demo. The adapter
boundary is small and explicit, so replacing a simulated adapter with a real one
does not touch the router or the rules.

**Revisit if:** the audit log, privacy settings, or multiple App Runner instances
require shared state. Move durable data to Postgres and keep device state
per adapter.

## D13. Raw parameters never enter the trace or logs

**Decision:** A trace event stores the parameter hash, the tool, the service, the
decision, and the speech. Logs add identifiers and decisions, never the token or
the raw parameters.

**Why:** Parameters contain what the user said: names, dates, room numbers.
The console does not need a second copy, and a log is a poor place to discover a
privacy problem.

**Revisit if:** an authorized audit view needs the full record. Put it in the
access-controlled audit table with a retention rule, not in the trace ring.

## D14. Subjects are pseudonymous; raw Alexa ids are refused

**Decision:** `ALEXA_TOKENS_JSON` maps a token to a stable pseudonym. A subject
that starts with `amzn1.` fails at startup.

**Why:** The subject is the key for device state, traces, and the future audit
chain. If a raw Alexa id enters there, it spreads everywhere before anyone
notices. Hashing at the caller is cheaper than redacting at every sink.

**Revisit if:** Alexa+ supplies a verified, already-pseudonymous household id
with the token. Even then, keep the startup check as a guard.

## D15. The audit log is separate from the trace

**Decision:** The trace ring buffer is a debugging view. The audit log is a
separate append-only, hash-chained store, and every response carries the
`audit_id` of its row.

**Why:** A ring buffer drops old entries and is not tamper-evident. Calling it an
audit log would be dishonest. Keeping them separate also means the trace can be
truncated for display without weakening the record.

**Revisit if:** never. The trace can be replaced, but it should not become the
audit record.

## D16. MCP tests use a real uvicorn server

**Decision:** The HTTP suite starts uvicorn on a free port and connects with the
MCP SDK's streamable client. REST-only tests use `TestClient`.

**Why:** The streamable transport needs real streaming, session headers, and a
session manager lifespan. An in-process ASGI shortcut would test a path Alexa+
does not use.

**Revisit if:** the SDK adds a faithful in-memory transport. Keep at least one
test over TCP before trusting it.

## D17. The container runs unprivileged with a locked dependency set

**Decision:** The image installs `requirements.txt` generated from `uv.lock`,
runs as UID 10001, and has a health check against `/health`.

**Why:** The app never writes to its own image, so root buys nothing. Pinning
transitive dependencies makes the image match the tested environment. CI checks
that the export is current and builds the image.

**Revisit if:** a dependency needs a writable path. Add a specific writable
volume or directory owned by the app user, not root.

## D18. CI gates lint, format, tests, leaks, and the image

**Decision:** CI runs ruff, format checking, pytest, the leak scan, and a Docker
build with a live `/health` check.

**Why:** The local machine may not have Docker, and a secret can slip into a
commit that passes tests. The pipeline should catch both. The leak scan also runs
in a pre-commit hook for fast feedback.

**Revisit if:** the Docker job becomes too slow for the feedback loop. Move it to
a nightly job, but keep the image smoke test before a deploy.

## D19. App Runner is the only public host

**Decision:** The container listens on port 8000 and expects App Runner to
terminate TLS and add `X-Forwarded-*` headers. `ALEXA_PUBLIC_URL` is the HTTPS
origin Alexa+ calls.

**Why:** The build plan constrains public hosting to App Runner. The app does not
need a load balancer, a custom domain, or a sidecar for the demo. The metadata
URL and the 401 challenge are built from the configured origin, not from the
request Host header.

**Revisit if:** App Runner cannot meet the latency or streaming requirements, or
the deployment needs multiple regions. The container contract stays the same.

## D20. The local CLI calls MCP; it is not an Alexa+ simulator

**Decision:** `python -m app.cli` lists tools, calls one tool with JSON, checks
the token, and benchmarks latency. It does not choose tools or generate speech.

**Why:** A bridge that emulates Alexa+ with a model would test a different
product. The thing we need to verify is the server contract: the same initialize,
`tools/list`, and `tools/call` path Alexa+ uses. The CLI is a thin client over
the official SDK.

**Revisit if:** the demo needs a scripted conversation. Build it as a journey
runner with expected tool calls and outcomes, not as an unconstrained model.

## D21. Tool annotations come from the manifest

**Decision:** MCP `title`, `idempotentHint`, and `openWorldHint` are derived from
`ToolSpec`. The console manifest exposes the same fields.

**Why:** A client should be able to render a tool picker and decide whether a
retry is safe without guessing. Keeping one source prevents the MCP surface and
the console from disagreeing.

**Revisit if:** a tool needs a hint that has no manifest equivalent. Add the
field to `ToolSpec`, not a literal in the decorator.

## D22. Booking availability is checked at execution

**Decision:** The preview describes the requested booking. The adapter checks
for a conflict when the confirmed token is used. A conflict leaves the token
usable.

**Why:** A preview is a description of intent, not a reservation. Holding a slot
before confirmation would create a lock that must expire and could be abused.
The failure is specific (`start_time`) and the user can retry the same token
with a different time after a new preview.

**Revisit if:** the booking service offers a real hold. Then add a preflight at
preview time and record the hold in the audit log.

## D23. Audit, undo, privacy, and high-risk certification are deliberately later

**Decision:** Day 3 adds the hash-chained audit, undo tools, `tell_me_more`,
concise mode, and privacy toggles. Day 4 adds the console, voice proxy,
journeys, and certification.

**Why:** The response contract already reserves the fields and the router has one
decision point. Building the safety layer before the audit exists would produce
claims the code cannot support.

**Revisit if:** the demo date moves. Do not ship a high-risk tool without the
audit and confirmation path, even if the UI is ready.

## D24. The project name is Alexa, and the house style has no em dashes

**Decision:** Package, MCP server name, environment prefix, loggers, client ids,
Docker image, and docs use `Alexa`, `alexa`, or `ALEXA_`. Prose uses no em dash
or en dash.

**Why:** The name is part of the product. The dash rule keeps voice-facing text
easy to read and avoids copy-paste characters that some terminals and speech
tools render badly.

**Revisit if:** never for the name. For punctuation, follow the publisher's
style guide if one is adopted.

## D25. Concise mode withholds `detail` on the server

**Decision:** Concise mode defaults to on. When it is on, a response with a
longer explanation returns `detail: null`, sets `detail_available: true`, and
serves the text from per-subject memory through `tell_me_more`. With it off,
`detail` is returned and the flag stays false.

**Why:** The alternative, always sending `detail` and telling the client not to
speak it, makes the server-side preference unobservable and `tell_me_more`
pointless. Withholding also keeps the first response small, which is what
"concise" is supposed to mean. `detail_available` exists because a client cannot
offer a follow-up it does not know about.

A preview is the exception: its detail explains that nothing has happened yet and
is part of the confirmation, so it is never replaced by a flag that points at
memory holding nothing.

**Revisit if:** Alexa+ cannot branch on `detail_available`. Then return `detail`
always and let the client decide, and record the preference as a client hint
instead of a server rule.

## D26. One global hash chain, a subject-scoped read view

**Decision:** All rows form one chain, across users. `/api/audit` returns only the
authenticated subject's rows. `/api/audit/verify` returns the row count, the head
hash, and the first broken id, but no row contents.

**Why:** A per-subject chain would let a caller prove their own actions but not
that nothing was inserted into the store as a whole. Verification is a global
safety property. Reading another household's actions is not part of that
property, so the endpoint exposes the verdict without the contents.

**Revisit if:** an operator console needs cross-subject rows. Add an explicit
`audit:read` grant and a separate operator role rather than widening the user
token.

## D27. The audit row stores the inverse, never the request

**Decision:** Each row holds the parameter hash, plus the minimal device state an
undo needs: a light snapshot, a thermostat setpoint, a timer id, a booking id. It
never stores the validated parameters or the confirmation token.

**Why:** Undo must work after the handler code changes or the process restarts,
and recomputing the inverse from a hash is impossible. The inverse is device
state, not user speech, so it does not weaken D13. Storing the request would.

**Revisit if:** a compensator needs a value that is neither an adapter reference
nor prior device state. Add it as an explicit field with a new decision, not as a
raw parameter blob.

## D28. Undo targets the newest executed action and is not previewed

**Decision:** `undo` with no parameters reverses the newest executed row for the
subject. If that row is not reversible or was already reversed, the call is
refused instead of reaching further back. Undo is low risk and is not previewed.
The handler resolves the row, then checks the scopes the row recorded before the
compensator runs.

**Why:** "Undo that" refers to the last action, not to the last reversible one.
Quietly skipping back would reverse something the user was not thinking about.
Undo only reverses an action the user already confirmed, so a second confirmation
would make every light restore a two-turn conversation. The authorization check
still applies, and a booking cancellation is still gated by third-party sharing.

**Revisit if:** a demo shows that undoing a booking needs its own confirmation.
Then make `undo` risk depend on the target row and preview medium-risk targets
only.

## D29. Retention is enforced when the setting changes

**Decision:** `privacy_set` with a new `retention_days` tombstones that subject's
older rows in the same call. There is no background job.

**Why:** The demo has no scheduler and no persistence, so a promised cleanup that
never runs would be a false claim. A tombstone keeps the position, the hashes,
the tool, and the decision, so the chain still verifies; it blanks the subject,
the versions, the scopes, the parameter hash, and the compensation. The tradeoff
is explicit: a tombstone proves sequence, not its own contents.

**Revisit if:** rows are persisted. Then run a scheduled sweep and keep the
on-change call as an immediate guarantee.

## D30. The startup audit fixture is deterministic and not undoable

**Decision:** `app/audit_seed.json` holds three fixed rows for `demo-user`. Their
hashes are computed at boot, so the chain head is reproducible, and
`/health` reports `audit_seeded`. Seeded rows carry no compensation.

**Why:** App Runner clears the container on redeploy. Without a marker, an empty
audit log looks like data loss or tampering. Fixed rows make the reset visible and
reviewable, and the absence of compensation means "undo that" can never target
fixture history.

**Revisit if:** real persistence exists. Then seed only on an explicitly empty
store and keep the marker.

## D31. A read reports decision `no_change`

**Decision:** `privacy_get` and `tell_me_more` return `status: ok` with decision
`no_change`, and set `read_only` and `idempotent` on the manifest.

**Why:** The existing decision vocabulary already has the right word for a valid
call that changes no state. Reusing it avoids a fifth decision in a published
contract, keeps reads out of the undo candidates, and lets the MCP
`readOnlyHint` be derived from the manifest rather than hardcoded.

**Revisit if:** the console needs to distinguish a read from a no-op write. Then
add a `read` decision and bump the contract deliberately.

## D32. Third-party sharing defaults to on

**Decision:** `third_party_sharing` defaults to on, so `book_room` works out of
the box. The demo turns it off to show the refusal.

**Why:** Privacy-by-default would argue for off, but then the primary demo
journey fails on a fresh install and the toggle has nothing to demonstrate. The
tool is simulated and marked `external`, so the exposure during the demo is
nominal. A real deployment should revisit this with the privacy owner.

**Revisit if:** the server connects to a real booking service. Then default to
off and make enabling it an explicit, audited user action.

## D33. The console is the root package with no router or UI kit

**Decision:** The console lives at the repository root: `index.html`, `src/`,
`package.json`, `tsconfig.json`, and `vite.config.ts` sit beside `backend/` and
`docs/`. It is React 19 and TypeScript, built by Vite, installed with pnpm.
Navigation is a 20-line hash route hook, and styling is CSS custom properties
plus plain CSS. No router dependency and no component library.

**Why:** Vite's root is the repository root, so the console has no nested package
and one `pnpm install` serves the checkout. The backend stays a pure Python
package under `backend/`, so neither build owns the other. Four flat screens do
not need nested layouts or server-side routes, and a UI kit would fight a theme
that is already about 30 tokens. Hash routing keeps deep links working when the
bundle is served from a subpath, with no server rewrite rule.

**Revised 2026-10-22:** the scaffold first lived in `frontend/` and was moved to
the root at the user's request. The package manager, lockfile, and Vite base did
not change; only the paths did.

**Revisit if:** the console grows past roughly six screens, needs guarded routes
or server-side rendering. Then add a router deliberately and keep the theme
tokens.

## D34. The console uses the Amazon palette as tokens, not Amazon brand assets

**Decision:** Colours, spacing, and type follow Amazon's public storefront
palette, stored as tokens in `src/styles/theme.css`. No Amazon Ember font, no
smile logo, no wordmark. Orange is a fill with ink text, never small text on
white.

**Why:** Palette continuity makes an internal operator tool feel like the
product it supports, without implying that Amazon endorses or ships it. Amazon
Ember is proprietary and cannot be bundled. Orange on white is about 2.1:1 and
fails WCAG AA, while ink on orange is about 8.8:1; the token file and the
contrast table in `FRONTEND.md` make that rule reviewable.

**Revisit if:** a licensed brand kit arrives, or a designer supplies a distinct
palette. Then replace tokens only, not component styles.

## D35. The console writes through one REST endpoint that calls `Router.execute`

**Decision:** Undo, privacy toggles, and the journey runner will call
`POST /api/call/{tool}` with `{params, confirmation_token?}`. The endpoint builds
the same principal as the other REST routes and calls `Router.execute`. It is not
built yet.

**Why:** Reading is easy over REST, but writes need auth, scopes, rules, privacy,
confirmations, audit, and trace. Calling MCP from the browser would duplicate
policy and add streaming and session handling. A server-side proxy would need a
second credential. One thin endpoint keeps `Router.execute` the only execution
path and returns the same `ToolResponse` that Alexa+ sees.

**Revisit if:** the console needs batch calls or streaming progress. Then add a
second named endpoint, not a wider version of this one.

## D36. The console ships inside the backend image at `/console`

**Decision:** FastAPI serves `dist/` at `/console` with `StaticFiles`, mounted
before the catch-all MCP mount and only when the directory exists. The Dockerfile
copies the build into the image. The build output lives at the repository root,
so the image build moves to the repository root and adjusts its paths when the
mount lands.

**Why:** App Runner is the only public host (D19). A second service would double
the deploy, the certificate, and the auth surface for a demo console. Serving
from the same origin removes CORS in production and keeps the bearer token on one
origin. The conditional mount means a checkout without a frontend build still
starts.

**Revisit if:** the console needs an independent release cadence, or it must sit
behind an identity provider at the edge. Then host it separately and keep the
write endpoint behind the same auth.

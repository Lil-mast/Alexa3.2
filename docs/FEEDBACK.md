# Developer Feedback: Alexa 3.5

Items marked **Not observed** describe a risk we have not reproduced in a live device test. Items marked **Confirm** need the team to check a claim before submission.

## Feedback Question 1: Which developer tools, APIs, and SDKs did you use and for what?

| Tool, API, or SDK | Used for | Where in the code |
|---|---|---|
| Alexa+ (MCP client) | Calls the eight MCP tools at `/mcp` | `backend/app/mcp_server.py`, `backend/app/main.py` |
| MCP Python SDK 2.3.0 | Server (`MCPServer`), tool registration, `TokenVerifier`, Streamable HTTP | `backend/app/mcp_server.py`, `backend/app/auth.py` |
| FastAPI 0.150.0, Uvicorn 0.54.0 | HTTP app, console REST routes, ASGI server | `backend/app/main.py`, `backend/app/api/` |
| Pydantic 2.14.1, pydantic-settings 2.16.0 | Wire models, configuration from environment | `backend/app/models.py`, `backend/app/config.py` |
| PyYAML 6.0.3 | Loads the versioned `rules.yaml` | `backend/app/rules/engine.py` |
| SQLAlchemy 2.x, psycopg 3.x | Accounts and sessions, Postgres in production | `backend/app/accounts/store.py` |
| httpx2 2.15.1 | Outbound calls to Google and ElevenLabs | `backend/app/accounts/google.py`, `backend/app/voice/elevenlabs.py` |
| ElevenLabs text to speech API v1 | Optional voice output behind a server proxy | `backend/app/voice/elevenlabs.py`, `backend/app/api/voice.py` |
| Google OAuth 2.0 with PKCE | Browser sign-in for the operator console | `backend/app/accounts/google.py`, `backend/app/api/auth.py` |
| Render | Hosts the API and Postgres | `render.yaml` |
| Vercel | Hosts the React console | `vercel.json` |
| React 19.2.7, TypeScript 5.9.3, Vite 7.3.7 | Operator console | `src/`, `vite.config.ts` |
| uv, pnpm, pytest 9.1.1, ruff | Dependency management, tests, linting | `backend/pyproject.toml`, `package.json`, `backend/tests/` |
| GitHub Actions, Docker | CI, container image with `/health` check | `.github/workflows/ci.yml`, `backend/Dockerfile` |
| Mermaid | Architecture and sequence diagrams in the README | `README.md` |

**Not integrated:** Bee and Ring. No code in this repository calls either one yet.

## Feedback Question 2: For each tool, API, or SDK, what worked well?

- **MCP Python SDK 2.3.0:** Tool registration with annotations was direct. Each tool is a decorator with a title, description, and hints, and the handler is a thin wrapper around one router call. The streamable HTTP app mounts into FastAPI without a separate server process.
- **FastAPI and Pydantic:** Request and response models double as the console contract. The same `ToolResponse` model serves MCP and REST, so the two cannot drift.
- **SQLAlchemy and psycopg:** One code path runs against SQLite locally and Postgres in production, and tests use a real engine.
- **ElevenLabs API:** The request shape is simple. Keeping the key server-side and falling back to browser speech when the key is missing worked without special handling.
- **Render:** The blueprint creates the API and the database together, and the internal connection string arrives in the environment with no manual copy.
- **Vercel:** Static hosting with a build-time API origin was straightforward. Every screen is a hash route, so no rewrite rules are needed.
- **Vite and React 19:** Fast dev server and a clean type check. The `/api` proxy keeps the browser on one origin during development.
- **Mermaid on GitHub:** Diagrams render in the README with no build step.

## Feedback Question 3: For each tool, API, or SDK, what needs work?

### Alexa+ (MCP client)

- **Authorization metadata:** The server publishes RFC 9728 protected-resource metadata but does not run an RFC 8414 authorization server. **Not observed:** Alexa+ registration may reject this. This is the main blocker for the device test.
- **Preview rendering:** The two-step booking flow relies on the model returning `confirmation_token` unchanged. Alexa+ should be able to show the structured `status: "preview"` response itself.
- **Hint usage:** We set `readOnlyHint`, `idempotentHint`, and `destructiveHint`. Document which of these Alexa+ reads.

### MCP Python SDK 2.3.0

- **Missing header error:** A client that omits `Accept: application/json, text/event-stream` gets a 400 or 406 with no guidance. The message should name the required header.
- **Mount redirect:** Mounting at `/mcp` with an inner `/` route produced a 307 to `/mcp/`, which the streamable client did not follow. The supported mount pattern is not documented.
- **Host allow list:** A disallowed `Host` returns 421, which clients show as a connection failure. The response body should give the reason.

### FastAPI and Starlette

- **Silent route shadowing:** Routes added after a catch-all `app.mount("/", ...)` are swallowed without an error. A warning in the docs would have saved time.

### SQLAlchemy and psycopg

- **Connection scheme:** Render provides `postgres://` URLs. Our code rewrites them to `postgresql+psycopg://` before creating the engine. **Confirm:** the exact error text we hit before the rewrite was not recorded.

### ElevenLabs API

- **Rate limits:** **Not observed:** We have not checked whether responses include rate-limit headers. The proxy has no per-token limit of its own yet.
- **Privacy:** Synthesis sends the speech text to ElevenLabs. Our code gates this on the user's third-party sharing setting, which is correct, but the data flow should be clearer in the API docs.

### Render

- **Free instances spin down:** A spin-down clears in-memory state: device state, pending confirmations, trace, and audit chain. The seeded audit fixture makes the reset visible, but a demo can still fail. A small persistent store, or a documented keep-warm option, would help.

### Vercel

- **Build-time variables:** `VITE_API_BASE` is compiled into the bundle, so changing the API origin requires a rebuild and a redeploy. Document the preview environment behavior.

### Google OAuth

- **Callback registration:** Each environment needs its own exact callback URL in the same OAuth client. A mismatch shows a generic error page. Document the error.

## Feedback Question 4: For each tool, API, or SDK, how was your onboarding experience?

- **MCP Python SDK:** The first working tool call took a few tries. The cause was the `Accept` header and the mount path, both found in troubleshooting, not in the quick start.
- **FastAPI, Pydantic, SQLAlchemy:** Quick. The official docs covered the common cases.
- **Google OAuth:** Slow. Creating the client, adding two callbacks, and understanding the PKCE flow took the most time.
- **Render:** Fast with the blueprint. The dashboard values that must be entered manually are easy to miss.
- **Vercel:** Fast. Setting the build-time variable was the only step that needed a second deploy.
- **ElevenLabs:** Fast. The no-key fallback meant the app worked before the voice was configured.
- **Alexa+:** **Not yet completed.** We have not reached device registration, so onboarding is untested. This section will be updated after the registration attempt.

## Feedback Question 5: Would you build with these devices and services again?

- **Yes:** MCP Python SDK, FastAPI, Pydantic, SQLAlchemy, React, Vite, TypeScript, Render, Vercel, ElevenLabs.
- **Yes, after the registration path is confirmed:** Alexa+.
- **Undecided:** Bee and Ring. We have not built against either one, so we cannot judge them.

## Feedback Question 6: Which AI tools have you leveraged while working on this project?

- **opencode:** The coding agent for this build. It wrote and tested most of the backend, and the repository's `docs/AGENTS.md` is a working guide for that agent. **Confirm:** the exact share of code written with it.
- **Google Stitch:** Used for design exploration of the console screens. **Confirm:** which screens came from Stitch and how many iterations.
- **ElevenLabs:** The text to speech API is in code, behind a server proxy. **Confirm:** whether the ElevenLabs conversational agents product was also used. It is not in the code.

## Feature Requests

| # | Request | Why it matters | Priority |
|---|---|---|---|
| 1 | Document whether RFC 9728 metadata alone is enough for Alexa+ MCP registration, or whether an RFC 8414 authorization-server document is required | Without this answer, the device test cannot start | **Critical** |
| 2 | Let Alexa+ render the structured `status: "preview"` response for medium and high risk tools | Confirmation is the core safety feature, and paraphrasing by the model is a risk | **Critical** |
| 3 | Add a local dry run in the Alexa+ Local Inspector that shows which tool the model selects | Tool selection is the riskiest part of the flow, and it needs testing before a device run | **Important** |
| 4 | MCP SDK: a documented mount pattern and an error message that names the missing `Accept` header | Would have removed the two slowest setup problems | **Important** |
| 5 | Render: a small persistent store, or a documented keep-warm option for free instances | A spin-down during a demo resets device state and pending confirmations | **Important** |
| 6 | ElevenLabs: rate-limit headers in responses | Needed to add a per-user limit on the voice proxy | **Nice-to-have** |
| 7 | Vercel: a runtime config option for the API origin | Removes a rebuild when the backend URL changes | **Nice-to-have** |

## Friction Log

Each entry records what we did, what we expected, and what happened. Entries marked **Not observed** are risks we have not reproduced.

### F1: Initialize an MCP session over Streamable HTTP

- **Task:** Connect an MCP client to `/mcp`.
- **Steps:** Send `POST /mcp` with `Content-Type: application/json` and no `Accept` header.
- **Expected:** A session is created and `initialize` returns the server info.
- **Actual:** The server returns 400 or 406.
- **Severity:** Medium.
- **Workaround:** Send `Accept: application/json, text/event-stream`. The CLI in `backend/app/cli.py` does this.
- **Suggestion:** Name the required header in the error body.

### F2: Mount the MCP app under a path

- **Task:** Serve the MCP endpoint at `/mcp` alongside other routes.
- **Steps:** Mount the MCP app at `/mcp` with an inner route of `/`, under Starlette 1.x.
- **Expected:** `/mcp` responds directly.
- **Actual:** The server returns 307 to `/mcp/`, which the streamable client does not follow.
- **Severity:** High. It breaks the client connection.
- **Workaround:** Mount at `/` with the MCP route at `/mcp` (`backend/app/main.py`).
- **Suggestion:** Document the supported mount pattern in the SDK guide.

### F3: Connect from a deployed host

- **Task:** Connect a client to the Render URL.
- **Steps:** Deploy without setting the host allow list.
- **Expected:** The client connects.
- **Actual:** The server returns 421 Invalid Host. Clients show this as a connection failure.
- **Severity:** High on a public deployment.
- **Workaround:** Set `ALEXA_ALLOWED_HOSTS` to the hostname without the scheme. Startup logs a warning when the value is `*`.
- **Suggestion:** Return the reason in the 421 body.

### F4: Add a route next to the catch-all mount

- **Task:** Add `/health` after the MCP mount.
- **Steps:** Register the route after `app.mount("/", ...)`.
- **Expected:** The route responds.
- **Actual:** The request is handled by the mount. No error is raised.
- **Severity:** Medium. The failure is silent.
- **Workaround:** Register routes before the mount. The order is commented in `backend/app/main.py`.
- **Suggestion:** Warn at startup when a route is shadowed.

### F5: Use the Render Postgres connection string

- **Task:** Connect the API to Render Postgres.
- **Steps:** Pass the `postgres://` URL to SQLAlchemy.
- **Expected:** The engine uses psycopg.
- **Actual:** The URL needs the `postgresql+psycopg://` scheme. **Confirm:** the exact error text was not recorded.
- **Severity:** Medium.
- **Workaround:** `normalize_database_url` rewrites the scheme, and a test covers it (`backend/tests/test_account_store.py`).
- **Suggestion:** Accept the `postgres://` alias in SQLAlchemy, or document the rewrite.

### F6: Free instance spins down during a demo

- **Task:** Run the walkthrough on a deployed instance.
- **Steps:** Leave the service idle until Render spins it down, then call a tool.
- **Expected:** Device state and pending confirmations persist.
- **Actual:** Device state, trace, audit chain, and pending confirmations reset. Pending confirmations become invalid.
- **Severity:** Medium for the demo, low for correctness.
- **Workaround:** The audit log reseeds from a fixture at boot, and `/health` reports `audit_seeded: true`, so the reset is visible.
- **Suggestion:** A small persistent store, or a documented keep-warm option.

### F7: Change the API origin for the console

- **Task:** Point the Vercel console at a new Render URL.
- **Steps:** Change `VITE_API_BASE` in the Vercel project.
- **Expected:** The console uses the new origin without a rebuild.
- **Actual:** The value is compiled into the bundle, so a redeploy is required.
- **Severity:** Low.
- **Workaround:** Redeploy. The change is one line.
- **Suggestion:** Read the origin from runtime configuration.

### F8: Register the MCP server in Alexa+

- **Task:** Register `https://<service>/mcp` in the Alexa+ developer console.
- **Steps:** Not yet attempted.
- **Expected:** Registration succeeds with a bearer token.
- **Actual:** **Not observed.** We expect the authorization-server metadata question in Feature Request 1 to be the first failure.
- **Severity:** Critical if confirmed.
- **Workaround:** Add an RFC 8414 document before the device test, if required.
- **Suggestion:** Publish the exact registration requirements, including whether protected-resource metadata alone is enough.

# Friction Log: Alexa 3.5

Each entry has the task, steps, expected and actual results, severity, workaround, and suggestion. The status tells you how the result was obtained:

- **Reproduced 2026-10-23:** run locally against uvicorn with `mcp` 2.3.0 and Python 3.13. The actual result is the captured response.
- **From code notes:** described in the repository, not re-run today.
- **Not attempted:** the step has not been run yet.

Setup for every reproduction:

```bash
cd backend
export ALEXA_TOKENS_JSON="$(sed -n 14p .env.example | cut -d= -f2-)"   # override a malformed local .env
uv run uvicorn app.main:app --port 8011
```

## Links per entry

Code links point to the `main` branch of [Lil-mast/Alexa3.5](https://github.com/Lil-mast/Alexa3.5). They work once these docs are pushed.

| Entry | Code | Reference |
|---|---|---|
| F1 | [`backend/app/auth.py#L62`](https://github.com/Lil-mast/Alexa3.5/blob/main/backend/app/auth.py#L62) | [Pydantic settings docs](https://docs.pydantic.dev) |
| F2 | [`backend/app/mcp_server.py`](https://github.com/Lil-mast/Alexa3.5/blob/main/backend/app/mcp_server.py) | [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) |
| F3 | [`backend/app/main.py#L93`](https://github.com/Lil-mast/Alexa3.5/blob/main/backend/app/main.py#L93) | [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) |
| F4 | [`backend/app/main.py#L49`](https://github.com/Lil-mast/Alexa3.5/blob/main/backend/app/main.py#L49) | [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) |
| F5 | [`backend/app/auth.py#L159`](https://github.com/Lil-mast/Alexa3.5/blob/main/backend/app/auth.py#L159) | [RFC 9728, section 5.1](https://www.rfc-editor.org/rfc/rfc9728) |
| F6 | [`backend/app/mcp_server.py#L84`](https://github.com/Lil-mast/Alexa3.5/blob/main/backend/app/mcp_server.py#L84) | [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) |
| F7 | [`backend/app/main.py#L260`](https://github.com/Lil-mast/Alexa3.5/blob/main/backend/app/main.py#L260) | [FastAPI docs](https://fastapi.tiangolo.com) |
| F8 | [`backend/app/accounts/store.py#L114`](https://github.com/Lil-mast/Alexa3.5/blob/main/backend/app/accounts/store.py#L114) | [SQLAlchemy docs](https://docs.sqlalchemy.org), [psycopg](https://www.psycopg.org) |
| F9 | [`docs/TROUBLESHOOTING.md`](https://github.com/Lil-mast/Alexa3.5/blob/main/docs/TROUBLESHOOTING.md) | [Render docs](https://render.com/docs) |
| F10 | [`vercel.json`](https://github.com/Lil-mast/Alexa3.5/blob/main/vercel.json) | [Vercel docs](https://vercel.com/docs) |
| F11 | [`README.md`](https://github.com/Lil-mast/Alexa3.5/blob/main/README.md) | [Alexa+ developer console](TO-CONFIRM) |

## F1: Local startup with a malformed `.env` value

- **Status:** Reproduced 2026-10-23.
- **Task:** Start the backend with the local `backend/.env`.
- **Steps:** Run `uv run uvicorn app.main:app --port 8011` with `ALEXA_TOKENS_JSON` set to a bare token string instead of a JSON object.
- **Expected:** Startup fails with an error that names the variable and shows the expected shape.
- **Actual:** Startup fails with `ValueError: ALEXA_TOKENS_JSON is not valid JSON`. The variable is named, but the file it came from and the expected shape are not.
- **Severity:** Low.
- **Workaround:** Copy the single-line JSON from `.env.example` into `.env`, or override it in the shell as above.
- **Suggestion:** Include the source file and a one-line example of a valid value in the error.

## F2: MCP initialize without an `Accept` header

- **Status:** Reproduced 2026-10-23. **Not a failure in this build.**
- **Task:** Open an MCP session with a plain JSON request.
- **Steps:**
  ```bash
  curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8011/mcp \
    -H 'Authorization: Bearer dev-token' -H 'Content-Type: application/json' \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}'
  ```
- **Expected:** An error if the `Accept` header is required.
- **Actual:** `200`. The session starts with or without `Accept: application/json, text/event-stream`.
- **Severity:** None for this build. Some clients may still need the header, so we keep it in the troubleshooting notes.
- **Workaround:** Not needed here.
- **Suggestion:** Correct the troubleshooting note so it does not read as a current failure.

## F3: Trailing slash on the MCP path

- **Status:** Reproduced 2026-10-23.
- **Task:** Connect a client that appends a trailing slash to the endpoint.
- **Steps:** `POST http://localhost:8011/mcp/` with a valid token.
- **Expected:** The request reaches the MCP endpoint, or the client is told the canonical path.
- **Actual:** `307` with `Location: http://localhost:8011/mcp`. Clients that do not follow redirects for POST fail at this point.
- **Severity:** Medium.
- **Workaround:** Configure the client with `/mcp` exactly, with no trailing slash.
- **Suggestion:** Document the canonical path in the SDK guide, or accept both forms.

## F4: Host outside the allow list

- **Status:** Reproduced 2026-10-23.
- **Task:** Call the MCP endpoint from a host that is not on `ALEXA_ALLOWED_HOSTS`.
- **Steps:** Start with `ALEXA_ALLOWED_HOSTS=example.com`, then `POST /mcp` with `Host: localhost:8012`.
- **Expected:** An error that says the host is not allowed and names the setting.
- **Actual:** `421` with the body `Invalid Host header`. The body does not name the setting or the rejected host. Clients report this as a connection failure.
- **Severity:** High on a public deployment, because the fix is one environment variable that is easy to miss.
- **Workaround:** Set `ALEXA_ALLOWED_HOSTS` to the hostname without the scheme. Startup logs a warning when it is `*`.
- **Suggestion:** Include the rejected host and the setting name in the 421 body.

## F5: Challenge points to the wrong origin when the port differs

- **Status:** Reproduced 2026-10-23.
- **Task:** Read the 401 challenge from a server on a non-default port.
- **Steps:** Run on port 8011 with `ALEXA_PUBLIC_URL` left at its default, then `POST /mcp` with no token.
- **Expected:** The `resource_metadata` URL points to the origin the server is running on.
- **Actual:** `resource_metadata="http://localhost:8000/.well-known/oauth-protected-resource/mcp"`. The default public URL uses port 8000, so a client that follows the challenge goes to the wrong server.
- **Severity:** Medium for local testing, High if a deployed origin is misconfigured.
- **Workaround:** Set `ALEXA_PUBLIC_URL` to the running origin. The server builds the challenge from configuration, not the Host header, which is intentional because Host can be attacker-controlled.
- **Suggestion:** Warn at startup when `ALEXA_PUBLIC_URL` does not match the bound port, or derive the default from the port.

## F6: Capabilities advertised that the server does not provide

- **Status:** Reproduced 2026-10-23.
- **Task:** Read the `initialize` result.
- **Steps:** Send `initialize` as in F2.
- **Expected:** Only the capabilities the server provides, which are tools.
- **Actual:** The result advertises `prompts` and `resources` with `listChanged: false`, although the server publishes no prompts or resources. The server did not set these, so they come from the SDK defaults.
- **Severity:** Low. Clients may request empty lists.
- **Workaround:** None needed.
- **Suggestion:** Advertise only the capabilities that are registered, or let the server opt out.

## F7: Route shadowing after the catch-all mount

- **Status:** From code notes. The comments in `backend/app/main.py` describe the failure. Not re-run today.
- **Task:** Add a route such as `/health` after the MCP mount.
- **Steps:** Register the route after `app.mount("/", ...)`.
- **Expected:** The route responds.
- **Actual:** The mount handles the request, and no error is raised.
- **Severity:** Medium. The failure is silent.
- **Workaround:** Register routes before the mount. The order is commented in `backend/app/main.py`.
- **Suggestion:** Warn at startup when a route is unreachable behind a mount.

## F8: Postgres connection string scheme

- **Status:** From code notes. A test covers the rewrite (`backend/tests/test_account_store.py`). Not re-run against Render today.
- **Task:** Connect the API to Render Postgres.
- **Steps:** Pass the `postgres://` URL to SQLAlchemy.
- **Expected:** SQLAlchemy uses psycopg.
- **Actual:** The URL must use the `postgresql+psycopg://` scheme. The exact error text was not recorded.
- **Severity:** Medium.
- **Workaround:** `normalize_database_url` rewrites the scheme.
- **Suggestion:** Accept the `postgres://` alias, or document the rewrite.

## F9: Free instance spin-down resets state

- **Status:** From code notes (`docs/TROUBLESHOOTING.md`). Not re-run on Render today.
- **Task:** Run the walkthrough on a deployed instance after it has been idle.
- **Steps:** Leave the service idle until it spins down, then call a tool.
- **Expected:** Device state and pending confirmations persist.
- **Actual:** Device state, trace, audit chain, and pending confirmations reset. A pending confirmation becomes invalid.
- **Severity:** Medium for a demo, low for correctness.
- **Workaround:** The audit log reseeds from a fixture at boot, and `/health` reports `audit_seeded: true`.
- **Suggestion:** A small persistent store, or a documented keep-warm option.

## F10: Console API origin is fixed at build time

- **Status:** From code notes. Not re-run on Vercel today.
- **Task:** Point the Vercel console at a new Render URL.
- **Steps:** Change `VITE_API_BASE` in the Vercel project.
- **Expected:** The console uses the new origin without a rebuild.
- **Actual:** The value is compiled into the bundle, so a redeploy is required.
- **Severity:** Low.
- **Workaround:** Redeploy.
- **Suggestion:** Read the origin from runtime configuration.

## F11: Alexa+ registration

- **Status:** Not attempted.
- **Task:** Register `https://<service>/mcp` in the Alexa+ developer console.
- **Steps:** Not yet attempted.
- **Expected:** Registration succeeds with a bearer token.
- **Actual:** Unknown. The metadata question in the feedback document is the expected first failure.
- **Severity:** Critical if confirmed.
- **Workaround:** Add an RFC 8414 document before the device test, if required.
- **Suggestion:** Publish the exact registration requirements, including whether protected-resource metadata alone is sufficient.

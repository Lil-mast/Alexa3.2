# Troubleshooting

Start with the health check and the CLI. They separate a server problem from a
client problem faster than reading logs.

```bash
curl -s localhost:8000/health
cd backend
uv run python -m app.cli tools
```

## Every call returns 401

The MCP endpoint and the console API both require `Authorization: Bearer
<token>`. The development token is `dev-token`. A deployed server uses the token
table in `ALEXA_TOKENS_JSON`, not the development default.

Check the token the server actually loaded:

```bash
curl -s -H 'Authorization: Bearer dev-token' localhost:8000/api/whoami
```

If that returns 401, the token is wrong, expired, or the server was started with
a different `ALEXA_TOKENS_JSON`. The 401 response includes a `WWW-Authenticate`
header that points at the protected-resource metadata, so a conforming client
can discover the resource.

Common causes:

- The client sends `Authorization: dev-token` instead of `Bearer dev-token`.
- A shell expanded or split the JSON in `ALEXA_TOKENS_JSON`. Quote the whole
  value.
- The token record has `expires_at` in the past.
- The client cached a session from before a redeploy. Reconnect.

## 421 Invalid Host header, or the client cannot connect at all

The MCP transport has DNS-rebinding protection. Its allow list comes from
`ALEXA_ALLOWED_HOSTS`. A request whose `Host` header is not on the list gets a
421, which many clients report as a generic connection failure.

Locally the default is `*`, which disables the guard. On App Runner, set it to
the service hostname without the scheme:

```bash
ALEXA_ALLOWED_HOSTS=example.us-east-1.awsapprunner.com
```

Do not leave `*` on a public deployment. Startup logs a warning when you do.

## The MCP client gets a 307 redirect

The MCP app is mounted at `/` and owns `/mcp`. Do not change the mount to
`/mcp` with an inner route of `/`. Under the Starlette version in use that
combination redirects `/mcp` to `/mcp/`, and the streamable client does not
follow it.

If you see a redirect, check the mount order in `app/main.py`. `/health`, `/api`,
`/docs`, and the metadata route must be registered before the catch-all mount.

## initialize returns 400 or 406

The streamable transport needs an `Accept` header that includes both JSON and
server-sent events:

```text
Accept: application/json, text/event-stream
```

A plain `curl -H 'Content-Type: application/json'` without `Accept` is often
enough for the first POST, but a client that wants the stream must advertise it.
The included `python -m app.cli` sets the header for you.

## A tool call fails with TOOL_NOT_FOUND after a redeploy

The MCP session belongs to the old process. Reconnect the client. App Runner
replaces the instance, so an open session cannot survive. The CLI creates a new
session for every command.

## The confirmation token is rejected

The token is single-use and bound to the subject, the tool, and the canonical
parameter hash.

- `TOKEN_CONSUMED`: the action already ran. Start a new preview.
- `TOKEN_EXPIRED`: the 300-second TTL passed, the server restarted, or the token
  belongs to another subject. Start a new preview.
- `INVALID_PARAM` with "The request changed since it was previewed": one of the
  parameters differs from the preview. Call again with the original parameters.
  Defaults are applied before the hash, so omitting an optional field on the
  second call is fine if the default is the same.

A failed execution, such as a booking conflict, does not consume the token. A
new preview after a conflict is still the safer path because the user should see
the new time.

## A booking is refused as already booked

Availability is checked when the confirmed call executes, not during the
preview. Another booking may have taken the slot between the two calls. Use a
different time or room, run a new preview, and confirm again. The refused call
does not consume the token, but the preview no longer describes what the user
will get.

## The thermostat returns ok but nothing changed

That is intentional. A valid request that matches the current setpoint returns
`status: "ok"` with trace decision `no_change`. It is not a fake success and not
an error. The speech says the zone is already at that temperature.

## `ModuleNotFoundError: No module named 'app'`

Run commands from `backend/`, not from the repository root. The test suite adds
`backend` to `sys.path`; a plain `python -m app.cli` needs the same working
directory or an installed package.

## `uv run pytest` cannot start uvicorn

The HTTP suite starts a real server on a free port. Check for a local firewall,
a container that owns the port, or a proxy that intercepts loopback traffic. The
fixture waits ten seconds for the server to report started; a slow machine can
need more. Raise the deadline in `tests/conftest.py` rather than skipping the
test.

## The Docker image builds but App Runner returns 503

Check all three:

1. The container listens on port 8000. The Dockerfile exposes it and the CMD
   passes `--port 8000`.
2. The App Runner health check path is `/health`, not `/`.
3. `ALEXA_PUBLIC_URL` is the full HTTPS origin of the service, with no trailing
   `/mcp`. The server appends `/mcp` itself.

The image runs as UID 10001. It needs no writable volume. If a future change
writes a file, create a writable directory owned by that UID instead of running
as root.

## The image works locally but the metadata URL is wrong

The metadata and the 401 challenge are built from `ALEXA_PUBLIC_URL`, not from
the request Host header. That is deliberate: behind a proxy, Host can be
attacker-controlled. Set the public origin correctly before deploying.

## The leak scan refused a commit

The scanner found a deployment URL, an AWS account id, an Alexa skill id, a
tunnel host, a key, or an environment file in the staged changes. Move the value
to `.env` and unstage the file.

- Enable the hook once per clone: `git config core.hooksPath .githooks`.
- Run it yourself: `python3 scripts/check_leaks.py`.
- Scan the whole tree: `python3 scripts/check_leaks.py --all`.
- Check the rules: `python3 scripts/check_leaks.py --self-test`.

If the hit is a documented placeholder, add it to the exact match list in
`scripts/check_leaks.py`. Do not use `git commit --no-verify` to hide a real
value.

## `requirements.txt` differs from `uv.lock`

`requirements.txt` is generated, not edited by hand:

```bash
cd backend
uv export --frozen --no-dev --no-hashes -o requirements.txt
```

CI runs the same command and compares the result. If the diff is unexpected,
update `pyproject.toml`, run `uv lock`, then regenerate.

## State disappeared after a restart

All device state, pending confirmations, and the trace are in memory. A restart
or a redeploy clears them. That is documented and safe for the demo: a pending
confirmation becomes invalid and the user is asked again. The Day 3 audit table
will make the reset visible instead of silent.

## Still stuck

Collect the health response, the CLI output, and the startup log lines. The
structured logs include `tool`, `subject`, `decision`, `params_hash`, and
`trace_id`, which are enough to correlate a call without exposing what the user
said.

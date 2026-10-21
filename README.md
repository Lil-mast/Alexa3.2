# Alexa 3.5

**A deterministic rules and audit layer for Alexa+ agents.**

Alexa is a self-hosted MCP server that lets Alexa+ control real things (timers, alarms, lights, thermostats, media) and take consequential actions (bookings, payments, deletions) without letting the language model touch device state directly. The model interprets what the user meant. Rules decide what happens. Every action is previewed, confirmed when risky, logged, and reversible where possible.

## The problem

Voice assistants fail in two opposite ways. Simple commands become unreliable when a model is asked to do work a rule should do: a timer set to "ten minutes" should be exactly ten minutes every time. Consequential actions become unsafe when a misheard word triggers a purchase or deletes something with no record of who or what caused it.

Alexa separates those two concerns. The LLM handles ambiguity in language. Deterministic code handles state changes.

## What it does

> The build is in progress. The status section below says what runs today. The
> hash-chained audit, undo tools, concise mode, and privacy toggles are Day 3
> work; the console, voice proxy, and journeys are Day 4. The paragraphs in this
> section describe the target product, not the current binary.

**Deterministic actions.** Timers, alarms, lighting, thermostats, and media controls run through a rules engine. The model picks a tool and parameters. The engine validates them against explicit bounds (for example, thermostat setpoints between 16 and 28 °C) and applies the change. The same input always produces the same result.

**Confirmations before consequential actions.** Every tool declares a risk tier. Low-risk actions run immediately. Medium and high-risk actions return a structured preview naming the service, the tool, the exact parameters, and the expected effect. The server issues a single-use confirmation token that expires after five minutes. Nothing executes until a second call presents that token.

**Concise mode.** Responses default to terse, one-sentence answers. A `detail` flag in the tool response carries the longer explanation, and Alexa+ can offer it as a follow-up ("want the details?").

**Rollback and audit.** Every tool call is written to an append-only log with a hash chain, so tampering is detectable. Each entry records the tool name, the caller's scope, the parameters, the result, and the compensating action if one exists. Reversible actions (lights, thermostat, timers) expose an undo tool. Irreversible actions (deletions, payments) are marked as such before confirmation.

**Visible tool use.** Each response includes a trace of the tools called, which service each one touched, and whether it succeeded. The Alexa console shows the same trace so developers and reviewers can see exactly what happened.

**Privacy controls.** Four toggles, each stored per user and enforced by the server, not by convention: retention (how long audit entries and transcripts are kept), personalization (whether preferences are used), microphone behavior (wake-word only versus continuous, passed through as a declared requirement), and third-party sharing (whether tool results may leave the household's services).

**Developer standard.** Alexa ships as a reference implementation of an MCP developer standard: permission scopes per tool, a shared error taxonomy, simulated user journeys for testing, and a certification checklist that high-risk tools must pass before submission. See [STANDARD.md](STANDARD.md).

## Quick start

```bash
# Backend
cd backend
uv sync --dev
uv run uvicorn app.main:app --reload --port 8000
```

The frontend console lands on Day 4. A plain virtualenv works too:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

The MCP endpoint is served at `http://localhost:8000/mcp`. Inspect it with the
Alexa+ Local Inspector or the MCP Inspector before connecting it to Alexa+. The
development bearer token is `dev-token`; see [backend/README.md](backend/README.md)
for auth, endpoints, and configuration.

## Local CLI

`uv run python -m app.cli` is a thin MCP client for manual checks. It does not choose
tools or write speech; it sends exactly the call you type and prints the
structured result.

```bash
cd backend
uv run python -m app.cli tools
uv run python -m app.cli call timer_set '{"duration_seconds": 600, "label": "pasta"}'
uv run python -m app.cli call book_room '{"date": "2026-10-23", "guests": 4}'
uv run python -m app.cli bench --n 100
```

Set `ALEXA_MCP_URL` and `ALEXA_TOKEN` to point at a deployed instance. A tool
business error exits non-zero, so the command is usable in a script.

## Demo script (three minutes, target for Day 4)

1. Ask Alexa+ to set a ten-minute timer. It runs immediately. Show the audit entry.
2. Ask it to dim the living room lights to 30 percent. Show the rule that validated the value.
3. Ask it to set the thermostat to 35 degrees. The rules engine rejects it with a structured error, and Alexa+ asks a specific follow-up.
4. Ask it to book a room for Friday. The preview appears, naming the booking service and tool. Confirm, and show the token being consumed.
5. Say "undo that." Show the compensating action and the new audit entry linked to the original.
6. Show the privacy panel. Turn off third-party sharing and repeat step 4 to show the tool is refused.

## Scope

**In scope:** the MCP server, the rules engine, confirmations, the audit log,
concise mode, privacy enforcement, the console UI, the developer standard
documents, and a test harness with simulated journeys.

**Out of scope:** real device integrations beyond simulators, the visual
rendering of confirmations (owned by Alexa+), and the legacy Alexa skill
migration (owned by Alexa+).

## Connect from Alexa+

The server is an MCP resource server. Registration needs a public HTTPS origin
and a bearer token.

1. Deploy the container to App Runner. Set `ALEXA_PUBLIC_URL` to the service
   origin, for example `https://example.us-east-1.awsapprunner.com`, and set
   `ALEXA_ALLOWED_HOSTS` to the hostname without the scheme.
2. Replace `ALEXA_TOKENS_JSON` with a real token table. Use a pseudonym for the
   `subject`; a raw `amzn1.` id is refused at startup.
3. In the Alexa+ developer console, register the MCP server URL
   `https://<service>/mcp` with `Authorization: Bearer <token>`.
4. Verify with `uv run python -m app.cli --url https://<service>/mcp tools` that all
   four tools and their output schemas are visible.
5. Ask for a low-risk action, then a booking preview and confirmation.

Current limitation: the server publishes RFC 9728 protected-resource metadata
but does not run an OAuth 2.1 authorization server. If registration requires an
authorization-server metadata document or an authorization code flow, add one
before the device test. See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for the
failure modes we have already hit.

## Security and privacy

- **Tokens are capabilities.** Every token maps to a subject and a scope set.
  Treat a token like a password: it belongs in `.env` or a secret manager, never
  in a tracked file, a URL, or a log line.
- **The development token is public.** `dev-token` exists so a fresh clone can
  use the inspector. A public deployment must replace `ALEXA_TOKENS_JSON`.
  Startup logs a warning when it is still the shipped value.
- **Subjects are pseudonymous.** The token table takes a stable household or
  user pseudonym. A raw `amzn1.` id fails at startup, so it cannot spread into
  device state, traces, and the future audit chain.
- **Raw parameters stay out of the trace.** The console sees a parameter hash,
  the tool, the decision, and the speech. The full record belongs in the
  access-controlled audit table on Day 3.
- **State is in memory.** A restart clears timers, lights, bookings, pending
  confirmations, and the trace. A pending confirmation becomes invalid and the
  user is asked again. That is safe, not durable.
- **Booking is external.** `book_room` is marked `external=true` so the Day 3
  privacy gate can refuse it when third-party sharing is off.
- **Tool descriptions are trusted prompt text.** They are sent to Alexa+ to help
  it choose a tool. Review a change to a description as carefully as a change to
  a handler, and only expose tools whose behavior you control.
- **The image runs unprivileged.** The container uses UID 10001 and needs no
  writable volume. App Runner terminates TLS and adds the forwarded headers.
- **Leak scanning is enforced.** `scripts/check_leaks.py` refuses a commit that
  carries a deployment URL, an AWS account id, an Alexa skill id, a key, or an
  environment file. Enable the hook with `git config core.hooksPath .githooks`.

## Checks

```bash
cd backend
uv run ruff check .
uv run ruff format --check .
uv run pytest -q

cd ..
python3 scripts/check_leaks.py --self-test
python3 scripts/check_leaks.py --all
```

The test suite starts a real uvicorn server for the MCP round trip. It covers
auth, the 401 challenge, metadata, rules, defaults, confirmation tokens, replay,
expiry, cross-user use, booking conflicts, per-user isolation, the `NO_CHANGE`
path, tool annotations, the CLI, and a latency guard on the in-memory hot path.
CI runs the same checks, verifies that `requirements.txt` matches `uv.lock`, and
builds the Docker image with a live `/health` check.

## Status

Hackathon build. Day 2 is complete: four tools, versioned YAML rules,
single-use confirmation tokens, simulated adapters, a trace buffer, and 76
tests. See [BUILD_LOG.md](BUILD_LOG.md) for what is implemented and verified,
[DECISIONS.md](DECISIONS.md) for the choices and their revisit conditions, and
`TECHNICAL.md` for architecture and contracts. `AGENTS.md` is the short working
guide for a new contributor or coding agent.